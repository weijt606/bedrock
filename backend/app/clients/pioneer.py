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
import time
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

# ---------------------------------------------------------------------------- #
#  the extraction task
# ---------------------------------------------------------------------------- #
#
# Cala answers `knowledge/search` in prose, and that prose is frequently richer
# and far faster than the typed rows from `knowledge/query` — 0.85s against 73s
# for the same chain, and current where the rows were stale. We were throwing it
# away because it was not a table.
#
# GLiNER2 is a zero-shot NER encoder, so it can turn that paragraph back into a
# table. This is the general-purpose LLM call the specialist replaces: a
# structured-extraction prompt to a frontier model, doing NER, at 100x the cost
# and 20x the latency.

OWNERSHIP_ENTITIES = ["company", "person", "family", "jurisdiction", "stake",
                      "date", "brand"]

READER_SCHEMA: dict[str, Any] = {
    "entities": OWNERSHIP_ENTITIES,
    "classifications": [
        {"task": "chain_position",
         "labels": ["ultimate_parent", "direct_parent", "subsidiary",
                    "acquirer", "target", "shareholder"]},
    ],
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
    r"^\s*(\(|\[)"                       # a parenthetical is an annotation, not a name
    r"|^(free float|floating stock|treasury (shares|stock)|other shareholders?"
    r"|public (shareholders?|float)|minority (shareholders?|interests?)|various"
    r"|not disclosed|undisclosed|n/?a|unknown|none)\b", re.I)
# Registries and scrapes leave behind placeholders where a name should be. They
# read like entities and they are not; following one costs a 40-second Cala
# query and puts a non-existent company in the middle of the chain.
_PLACEHOLDER = re.compile(
    r"\b(truncated|not available|unavailable|name withheld|redacted|see note"
    r"|largest (institutional )?holder|institutional holders?|nominee)\b", re.I)


def _heuristic(name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Cheap, instant, and deliberately unwilling to guess.

    Biased towards `company`, and on a genuinely ambiguous name it returns
    `unknown` with `terminal=False` so the dig continues and the next hop
    resolves it. Ending the chain early is the expensive mistake.
    """
    n = (name or "").strip()
    has_person_signal = bool(row.get("role") or row.get("ownership_percent"))

    if _NOT_ENTITY.match(n) or _PLACEHOLDER.search(n):
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

    # ---------------------------------------------------------------- extract
    async def extract(self, text: str,
                      schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Pull structured entities out of a paragraph of Cala prose.

        Returns {"entities": [{text, label, score}], "classifications": {...},
        "inference_id": str, "latency_s": float} or None when Pioneer is not
        configured — callers must handle None rather than receive a guess.
        """
        if not settings.has_pioneer or not text.strip():
            return None
        t0 = time.perf_counter()
        async with self._gate:
            try:
                r = await self._client.post(
                    f"{settings.pioneer_base}/inference",
                    json={
                        "model_id": settings.model_reader,
                        "text": text[:6000],
                        "schema": schema or READER_SCHEMA,
                        "threshold": settings.assay_threshold,
                    },
                    headers=self._headers(),
                    timeout=settings.reader_timeout_s,
                )
                r.raise_for_status()
                body = r.json()
            except Exception:
                return None
        out = _parse_entities(body)
        out["inference_id"] = body.get("id") or body.get("inference_id")
        out["latency_s"] = round(time.perf_counter() - t0, 3)
        return out

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
    """Read a classification response. Measured shape:

        {"type": "encoder",
         "inference_id": "4f86e30a-…",
         "result": {"data": {"entity_kind":       {"label": "company", "confidence": 0.67},
                             "chain_terminates":  {"label": "yes",     "confidence": 0.82}}},
         "model_id": "fastino/gliner2-base-v1", "latency_ms": 271}

    A task keyed dict, not a list. Returns None rather than a wrong label so an
    unrecognised response falls back to the heuristic instead of corrupting the
    chain.
    """
    data = ((body.get("result") or {}).get("data")
            if isinstance(body.get("result"), dict) else None)
    if not isinstance(data, dict):
        return None

    def pick(task: str) -> tuple[str | None, float]:
        v = data.get(task)
        if isinstance(v, dict):
            return (str(v.get("label")).lower() if v.get("label") else None,
                    float(v.get("confidence") or 0.0))
        if isinstance(v, str):
            return v.lower(), 0.0
        return None, 0.0

    kind, conf = pick("entity_kind")
    if kind not in KINDS:
        return None
    terminates, _ = pick("chain_terminates")
    terminal = (terminates == "yes" if terminates in ("yes", "no")
                else kind in ("person", "family", "foundation"))
    return {"kind": kind, "confidence": round(conf or 0.5, 2), "terminal": bool(terminal)}


def _parse_entities(body: dict[str, Any]) -> dict[str, Any]:
    """Read an extraction response. Measured shape:

        {"result": {"data": {"entities": {"company": [{"text": "Nestlé S.A.",
                                                       "confidence": 0.96,
                                                       "start": 0, "end": 11}]}}}}

    Entities come back keyed by label, classifications keyed by task name, side
    by side under the same `data`. Anything unrecognised yields nothing rather
    than a hallucinated span.
    """
    data = ((body.get("result") or {}).get("data")
            if isinstance(body.get("result"), dict) else None)
    ents: list[dict[str, Any]] = []
    cls: dict[str, str] = {}
    if not isinstance(data, dict):
        return {"entities": ents, "classifications": cls}

    by_label = data.get("entities")
    if isinstance(by_label, dict):
        for label, spans in by_label.items():
            if label not in OWNERSHIP_ENTITIES or not isinstance(spans, list):
                continue
            for span in spans:
                if not isinstance(span, dict):
                    continue
                text = str(span.get("text") or "").strip()
                if text:
                    ents.append({"text": text, "label": label,
                                 "score": float(span.get("confidence") or 0.0),
                                 "start": span.get("start"), "end": span.get("end")})

    for task, v in data.items():
        if task == "entities":
            continue
        if isinstance(v, dict) and v.get("label"):
            cls[task] = str(v["label"])

    seen, uniq = set(), []
    for e in ents:
        k = (e["text"].lower(), e["label"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    uniq.sort(key=lambda e: (e["start"] if isinstance(e.get("start"), int) else 1 << 30))
    return {"entities": uniq, "classifications": cls}
