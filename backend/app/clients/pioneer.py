"""Pioneer — the assay.

Cala tells us *who* owns a company. It does not tell us *what kind of thing* the
answer is, and that distinction decides whether the dig continues. A row reading
"Perfetti Van Melle" and a row reading "Juan Roig" are indistinguishable to a
regex: three capitalised words, no legal suffix. Guess "person" on the first and
the chain stops one hop in; guess "company" on the second and it never stops.

That is a narrow, high-volume classification problem over short strings — exactly
what a small fine-tuned encoder beats a large general model at, on accuracy,
latency and cost all at once. So Bedrock puts Pioneer here and nowhere else.

  POST /inference          schema-based extraction on GLiNER2 (~100ms, not seconds)
  POST /inferences/{id}/feedback   corrections, which drive Adaptive Inference

**The feedback loop is the interesting part.** We never label anything by hand.
When the prospector walks one hop further, Cala's own verified graph reveals what
the previous node really was — a name that turns out to have shareholders was a
company, a name that terminates the chain was a person. We post that back as a
correction, so *Cala's ground truth supervises Pioneer's classifier*, and every
dig a player runs produces free labelled training data.

Without a key this degrades to a deterministic classifier that refuses to guess
on ambiguous names, so the pipeline runs end to end and simply digs less
accurately.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import settings

# --------------------------------------------------------------------------- #
#  the classification task
# --------------------------------------------------------------------------- #

# `not_an_entity` earns its place: share registers are full of rows that name a
# category rather than an owner — "Free float", "Treasury shares", "Other
# shareholders". Following one of those up the chain is nonsense, so the
# classifier has to be able to say that a row is not a thing.
KINDS = ["company", "person", "family", "fund", "foundation", "not_an_entity"]

ASSAY_SCHEMA: dict[str, Any] = {
    "classifications": [
        {"task": "entity_kind", "labels": KINDS},
        {"task": "chain_terminates", "labels": ["yes", "no"]},
    ]
}

# --------------------------------------------------------------------------- #
#  deterministic fallback
# --------------------------------------------------------------------------- #

_FAMILY = re.compile(r"\b(family|families|clan|heirs|estate of)\b", re.I)
_FUND = re.compile(r"\b(capital|partners|equity|fund|invest)\b", re.I)
_FOUNDATION = re.compile(r"\b(foundation|stichting|trust|fundaci[oó]n|interogo)\b", re.I)
_COMPANY = re.compile(
    r"\b(s\.?a\.?u?|b\.?v\.?|n\.?v\.?|gmbh|kg|ltd|limited|llc|inc|plc|s\.?l\.?|s\.?p\.?a\.?|"
    r"oyj|ab|a/s|group|corp|co\.)\b", re.I)
_CORPORATE_WORD = re.compile(
    r"\b(company|industries|foods?|brands?|international|holdings?|beheer|"
    r"group|groep|gruppo|grupo|sektkellerei|kellerei|verwaltung|konzern)\b", re.I)
_PERSON = re.compile(r"^[A-ZÁÉÍÓÚÑÜ][\w'’\-]+(?:\s+[A-ZÁÉÍÓÚÑÜ][\w'’\-]+){1,3}$")
_NOT_ENTITY = re.compile(
    r"^(free float|floating stock|treasury (shares|stock)|other shareholders?|public (shareholders?|float)|minority (shareholders?|interests?)|various|not disclosed|undisclosed|n/?a|unknown)\b", re.I)


def _heuristic(name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Cheap, instant, and deliberately unwilling to guess.

    Biased towards `company`, and on a genuinely ambiguous name it returns
    `unknown` with `terminal=False` so the dig continues and the next hop
    resolves it. Ending the chain early is the expensive mistake.
    """
    n = (name or "").strip()
    has_person_signal = bool(row.get("role") or row.get("ownership_percent"))

    if _NOT_ENTITY.match(n):
        kind, conf, terminal = "not_an_entity", 0.9, False
    elif _FAMILY.search(n):
        kind, conf, terminal = "family", 0.86, True
    elif _FOUNDATION.search(n):
        kind, conf, terminal = "foundation", 0.80, True
    elif _COMPANY.search(n) or _CORPORATE_WORD.search(n):
        kind, conf, terminal = "company", 0.88, False
    elif _FUND.search(n):
        kind, conf, terminal = "fund", 0.74, False
    elif has_person_signal and _PERSON.match(n) and len(n.split()) <= 3:
        kind, conf, terminal = "person", 0.76, True
    elif _PERSON.match(n) and len(n.split()) <= 3:
        kind, conf, terminal = "unknown", 0.50, False
    else:
        kind, conf, terminal = "company", 0.60, False

    if has_person_signal:
        conf = min(0.95, conf + 0.06)
    return {"kind": kind, "confidence": round(conf, 2), "terminal": terminal,
            "inference_id": None, "backend": "heuristic"}


def row_text(name: str, row: dict[str, Any]) -> str:
    """One line of context per row. The classifier sees the name *and* the columns
    Cala returned alongside it, because 'role: co-owner' is the tell."""
    bits = [name]
    for k in ("role", "type", "relationship", "ownership_percent", "stake_percent",
              "address", "registered_address"):
        v = row.get(k)
        if v not in (None, ""):
            bits.append(f"{k}: {v}")
    return " | ".join(str(b) for b in bits)[:400]


# --------------------------------------------------------------------------- #
#  client
# --------------------------------------------------------------------------- #


@dataclass
class AssayResult:
    kind: str
    confidence: float
    terminal: bool
    inference_id: str | None = None
    backend: str = "heuristic"
    text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class PioneerClient:
    """Assay rows, and teach the model from what Cala proves afterwards."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=settings.assay_timeout_s)
        self._gate = asyncio.Semaphore(8)
        self._taught = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def backend(self) -> str:
        return f"pioneer:{settings.model_assay}" if settings.has_pioneer else "heuristic"

    @property
    def taught(self) -> int:
        """How many corrections this process has fed back to Adaptive Inference."""
        return self._taught

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": settings.pioneer_key, "Content-Type": "application/json"}

    # ------------------------------------------------------------------ assay
    async def assay(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Classify a batch of registry rows. Returns one dict per row, in order.

        Rows are classified concurrently — GLiNER2 answers in ~100ms and Pioneer
        allows 5,000 requests a minute, so the whole batch costs about as much
        wall-clock as one row.
        """
        names = [
            (r.get("owner") or r.get("name") or r.get("shareholder")
             or r.get("ultimate_owner") or "").strip()
            for r in rows
        ]
        fallback = [_heuristic(n, r) for n, r in zip(names, rows)]
        if not settings.has_pioneer or not names:
            return fallback

        texts = [row_text(n, r) for n, r in zip(names, rows)]
        results = await asyncio.gather(
            *(self._infer(t) for t in texts), return_exceptions=True)

        out: list[dict[str, Any]] = []
        for fb, res, text in zip(fallback, results, texts):
            if isinstance(res, dict) and res.get("kind"):
                res["text"] = text
                out.append(res)
            else:
                fb = dict(fb)
                fb["text"] = text
                out.append(fb)
        return out

    async def _infer(self, text: str) -> dict[str, Any] | None:
        async with self._gate:
            try:
                r = await self._client.post(
                    f"{settings.pioneer_base}/inference",
                    json={
                        "model_id": settings.model_assay,
                        "text": text,
                        "schema": ASSAY_SCHEMA,
                        "threshold": settings.assay_threshold,
                    },
                    headers=self._headers(),
                    timeout=settings.assay_timeout_s,
                )
                r.raise_for_status()
                body = r.json()
            except Exception:
                return None

        parsed = _parse_inference(body)
        if parsed:
            parsed["inference_id"] = body.get("id") or body.get("inference_id")
            parsed["backend"] = f"pioneer:{settings.model_assay}"
            parsed["raw"] = body
        return parsed

    # --------------------------------------------------------------- feedback
    async def teach(self, inference_id: str | None, kind: str, terminal: bool) -> bool:
        """Post a correction that Cala later proved.

        This is the whole adaptive story: nobody hand-labels anything. A node the
        prospector walked *past* was a company; a node the chain stopped at was a
        person. Cala's verified graph is the supervisor.
        """
        if not (settings.has_pioneer and settings.pioneer_adaptive and inference_id):
            return False
        try:
            r = await self._client.post(
                f"{settings.pioneer_base}/inferences/{inference_id}/feedback",
                json={"correction": {"classifications": [
                    {"task": "entity_kind", "label": kind},
                    {"task": "chain_terminates", "label": "yes" if terminal else "no"},
                ]}},
                headers=self._headers(),
                timeout=settings.assay_timeout_s,
            )
            r.raise_for_status()
        except Exception:
            return False
        self._taught += 1
        return True

    # ------------------------------------------------------------ diagnostics
    async def base_models(self) -> list[dict[str, Any]]:
        if not settings.has_pioneer:
            return []
        try:
            r = await self._client.get(
                f"{settings.pioneer_base}/base-models",
                params={"supports_inference": "true"},
                headers=self._headers(), timeout=15.0)
            r.raise_for_status()
            body = r.json()
            return body if isinstance(body, list) else body.get("models", [])
        except Exception:
            return []


# --------------------------------------------------------------------------- #
#  response parsing
# --------------------------------------------------------------------------- #


def _parse_inference(body: dict[str, Any]) -> dict[str, Any] | None:
    """Pull our two classification tasks out of a Pioneer /inference response.

    The result array shape varies with the base model, so this reads defensively
    and returns None rather than a wrong label — a None falls back to the
    heuristic instead of corrupting the chain.
    """
    result = body.get("result") or body.get("results") or body
    items: list[dict[str, Any]] = []
    if isinstance(result, list):
        items = [i for i in result if isinstance(i, dict)]
    elif isinstance(result, dict):
        for key in ("classifications", "classification", "labels"):
            v = result.get(key)
            if isinstance(v, list):
                items = [i for i in v if isinstance(i, dict)]
                break
        else:
            items = [result]

    kind, kind_conf, terminal = None, 0.0, None
    for item in items:
        task = str(item.get("task") or item.get("name") or item.get("type") or "").lower()
        label = item.get("label") or item.get("value") or item.get("prediction")
        score = item.get("confidence") or item.get("score") or item.get("probability")
        if label is None:
            continue
        label = str(label).lower()
        if task in ("entity_kind", "kind") or label in KINDS:
            kind, kind_conf = label, float(score or 0.0)
        elif task in ("chain_terminates", "terminates") or label in ("yes", "no"):
            terminal = label == "yes"

    if kind not in KINDS:
        return None
    if terminal is None:
        terminal = kind in ("person", "family", "foundation")
    return {"kind": kind, "confidence": round(kind_conf or 0.5, 2), "terminal": bool(terminal)}
