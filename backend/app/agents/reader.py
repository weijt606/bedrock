"""Read Cala's prose back into a table.

Cala answers `knowledge/search` in markdown. We had been ignoring it because it
was not rows — which turned out to be an expensive mistake:

    Who ultimately owns Chupa Chups?     search 0.85s   ·   query ladder 73s
    Who ultimately owns Freixenet?       search names the 2021 Oetker family
                                         split and the buy-out of the remaining
                                         Ferrer/Bonet shares; the typed rows
                                         still showed Ferrer at 42%.

So the prose is often both faster and more current than the table. The only
reason not to use it was that somebody has to turn a paragraph back into
structure — and that is a named-entity problem, not a reasoning problem.

That is the job this agent hands to GLiNER2. It is also, precisely, the
general-purpose LLM call being replaced: a structured-extraction prompt to a
frontier model, doing NER, at far higher latency and cost. `scripts/bench.py`
measures the swap.

The prose is a Cala answer with Cala's own fact ids attached, so everything this
agent emits still carries a `Source`. The extractor model decides *where the
spans are*; it never decides what is true.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from ..clients.cala import CalaClient
from ..clients.pioneer import PioneerClient, is_placeholder
from ..schemas import EntityKind, Gap, Layer
from .base import source_of

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

# GLiNER2 entity label -> our EntityKind
_KIND = {
    "company": EntityKind.company,
    "person": EntityKind.person,
    "family": EntityKind.family,
    "brand": EntityKind.unknown,
}
_TERMINAL = {EntityKind.person, EntityKind.family, EntityKind.foundation}


class ReaderAgent:
    """A fast first pass over the prose, before the slow ladder even starts."""

    name = "reader"

    def __init__(self, cala: CalaClient, pioneer: PioneerClient) -> None:
        self.cala, self.pioneer = cala, pioneer

    async def run(self, subject: str, emit: Emit) -> tuple[list[Layer], list[Gap]]:
        question = f"Who ultimately owns {subject}?"
        await emit("probe", {"query": question, "agent": self.name})

        res = await self.cala.search(question)
        if not res.content or res.error:
            return [], [Gap(query=question,
                            reason="no_rows" if not res.content else "error",
                            note=res.error, latency_s=res.latency_s)]

        got = await self.pioneer.extract(res.content)
        if not got or not got.get("entities"):
            # No extractor configured, or nothing recognised. The prospector's
            # ladder still runs; this agent simply contributes nothing.
            return [], []

        src = source_of(res)
        jurisdictions = [e["text"] for e in got["entities"] if e["label"] == "jurisdiction"]
        stakes = [e["text"] for e in got["entities"] if e["label"] == "stake"]
        dates = [e["text"] for e in got["entities"] if e["label"] == "date"]

        # The extractor returns every span it recognises, which includes the
        # subject itself, the same company under two spellings, and placeholders.
        # A span is not a link in a chain; filter before promoting one to a Layer.
        layers: list[Layer] = []
        seen: set[str] = {_key(subject)}
        for e in got["entities"]:
            kind = _KIND.get(e["label"])
            if kind is None:
                continue
            key = _key(e["text"])
            if not key or key in seen or is_placeholder(e["text"]):
                continue
            seen.add(key)
            detail = [d for d in (
                f"jurisdictions named in the same answer: {', '.join(jurisdictions[:4])}"
                if jurisdictions else "",
                f"stakes named: {', '.join(stakes[:4])}" if stakes else "",
                f"dates named: {', '.join(dates[:4])}" if dates else "",
            ) if d]

            layer = Layer(
                index=len(layers),
                name=e["text"],
                kind=kind,
                relationship=got.get("classifications", {}).get("chain_position"),
                detail=detail,
                confidence=round(float(e.get("score") or 0.0), 2),
                terminal=kind in _TERMINAL,
                provisional=True,
                source=src,
            )
            layers.append(layer)
            await emit("layer", layer.model_dump(mode="json"))

        await emit("plan", {
            "agent": self.name,
            "note": "prose read by the extractor before the ladder ran",
            "search_latency_s": res.latency_s,
            "extract_latency_s": got.get("latency_s"),
            "entities_found": len(got["entities"]),
        })
        return layers, []


_NOISE = re.compile(
    r"\b(group|holdings?|company|co|corp|inc|ltd|limited|plc|llc|s\.?a\.?u?|"
    r"s\.?l\.?|b\.?v\.?|n\.?v\.?|gmbh|kg|spa|ag|sa|the)\b\.?", re.I)


def _key(name: str) -> str:
    """Fold a name hard enough that "Nestlé", "Nestlé S.A." and "Nestlé Nespresso
    SA" do not each become their own layer."""
    n = (name or "").lower()
    for a, b in (("é", "e"), ("è", "e"), ("ñ", "n"), ("ü", "u"), ("ö", "o"), ("á", "a")):
        n = n.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", _NOISE.sub(" ", n)).strip()
