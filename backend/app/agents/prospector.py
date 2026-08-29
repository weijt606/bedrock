"""The ownership chain, one hop at a time.

This is the only sequential part of the dig — hop N+1 is a question about the
answer to hop N, so it cannot be parallelised. It is also the part the game
layer animates, which is why every hop is streamed the moment it lands rather
than held back until the chain is complete.

Termination: a hop whose subject the assay marks `terminal` (a person, a family,
a foundation) ends the chain. So does a repeat, an empty result, or the depth cap.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Awaitable

from ..clients.cala import CalaClient
from ..clients.pioneer import PioneerClient
from ..schemas import EntityKind, Gap, Layer
from .base import detail_lines, first_name, source_of

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class ProspectorAgent:
    name = "prospector"

    def __init__(self, cala: CalaClient, assay: PioneerClient) -> None:
        self.cala, self.assay = cala, assay

    async def run(self, subject: str, depth: int, emit: Emit) -> tuple[list[Layer], list[Gap]]:
        layers: list[Layer] = []
        gaps: list[Gap] = []
        marks_by_layer: list[dict[str, Any]] = []
        current = subject
        seen = {subject.lower()}

        for i in range(depth):
            stem = current.rstrip(". ")
            question = f"Who owns {current}?" if i == 0 else f"{stem}.shareholders"
            await emit("probe", {"query": question, "agent": self.name, "hop": i})

            res = await self.cala.query(question)
            if res.error == "too_complex":
                res = await self.cala.query(f"Who owns {current}?")

            if res.empty or res.error:
                gaps.append(Gap(query=question,
                                reason="no_rows" if res.empty else "error",
                                note=res.error, latency_s=res.latency_s))
                await emit("gap", {"query": question, "reason": res.error or "no_rows",
                                   "latency_s": res.latency_s})
                break

            marks = await self.assay.assay(res.rows)
            # A share register frequently leads with 'Free float' or 'Treasury
            # shares'. Those name a category, not an owner, so walk past them to
            # the first row that is actually somebody.
            pick = next((j for j, m in enumerate(marks)
                         if m.get("kind") != "not_an_entity"), 0)
            head = res.rows[pick] if pick < len(res.rows) else res.rows[0]
            mark = marks[pick] if pick < len(marks) else {
                "kind": "unknown", "confidence": 0.4, "terminal": False}
            name = first_name(head)

            layer = Layer(
                index=i,
                name=name,
                kind=EntityKind(mark["kind"]),
                country=_iso(head) or _iso_from_text(" ".join(detail_lines(res.rows))),
                city=head.get("city"),
                address=head.get("address") or head.get("registered_address"),
                stake_percent=_pct(head),
                relationship=head.get("relationship") or head.get("type"),
                detail=detail_lines(res.rows),
                confidence=round(float(mark["confidence"]), 2),
                terminal=bool(mark["terminal"]),
                source=source_of(res),
            )
            layers.append(layer)
            marks_by_layer.append(mark)
            await emit("layer", layer.model_dump(mode="json"))

            if layer.terminal or name.lower() in seen:
                break
            seen.add(name.lower())
            current = name

        await self._teach(layers, marks_by_layer)
        return layers, gaps

    async def _teach(self, layers: list[Layer], marks: list[dict[str, Any]]) -> None:
        """Feed Adaptive Inference the labels Cala just proved for us.

        Any node the chain walked *past* demonstrably had shareholders, so it was a
        company and it did not terminate the chain — whatever the classifier said.
        We only post where the model disagreed, because a correction that confirms
        the prediction carries no signal. Nothing here is hand-labelled: the
        verified graph is the supervisor.
        """
        for i in range(len(layers) - 1):
            mark = marks[i] if i < len(marks) else {}
            wrong = mark.get("terminal") or mark.get("kind") not in ("company", "fund")
            if wrong and mark.get("inference_id"):
                await self.assay.teach(mark["inference_id"], "company", False)


def _pct(row: dict[str, Any]) -> float | None:
    for k in ("stake_percent", "ownership_percent"):
        v = row.get(k)
        if v in (None, ""):
            continue
        try:
            return float(str(v).replace("%", "").strip())
        except ValueError:
            continue
    return None


_COUNTRY_HINTS = {
    "luxembourg": "LU", "netherlands": "NL", "spain": "ES", "germany": "DE",
    "italy": "IT", "france": "FR", "switzerland": "CH", "belgium": "BE",
    "united kingdom": "GB", "england": "GB", "ireland": "IE", "denmark": "DK",
    "sweden": "SE", "united states": "US", "portugal": "PT", "austria": "AT",
    # cities, only where the mapping is unambiguous
    "barcelona": "ES", "madrid": "ES", "valencia": "ES", "bielefeld": "DE",
    "wiesbaden": "DE", "amsterdam": "NL", "schiphol": "NL", "rotterdam": "NL",
    "milan": "IT", "lainate": "IT", "turin": "IT", "paris": "FR", "lisbon": "PT",
}


def _iso_from_text(text: str) -> str | None:
    low = (text or "").lower()
    for word, iso in _COUNTRY_HINTS.items():
        if word in low:
            return iso
    return None


def _iso(row: dict[str, Any]) -> str | None:
    """Only ever *reads* a country out of what Cala returned. Never guesses one."""
    for k in ("country", "cc", "jurisdiction", "headquarters", "headquarters_city",
              "address", "registered_address", "location"):
        v = row.get(k)
        if not isinstance(v, str):
            continue
        if len(v) == 2 and v.isalpha():
            return v.upper()
        low = v.lower()
        for word, iso in _COUNTRY_HINTS.items():
            if word in low:
                return iso
    return None
