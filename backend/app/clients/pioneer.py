"""Pioneer — the fine-tuned specialist.

Pioneer serves an OpenAI-compatible endpoint, so this is deliberately a thin
adapter: swap the base URL and the model id and the same call shape works.
Bedrock uses it for the one job a small adaptively-retrained model is genuinely
better at than a large general one — **classifying and scoring the messy rows a
knowledge graph returns**: is this row a company, a person, a family office, a
foundation; how confident are we; is this the end of the chain.

Two properties matter for us:
  * `extra_body={"adaptive": True}` lets Pioneer retrain on our production
    traffic, and every dig produces labelled examples for free.
  * the response carries `adaptive_score`, which we surface as Layer.confidence.

Until a key is present this falls back to a deterministic heuristic, so the whole
pipeline runs end to end without Pioneer and gains accuracy when it is plugged in.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import settings

_ASSAY_SYSTEM = (
    "You classify rows returned by a corporate registry. You never add facts. "
    "For each row decide what kind of entity it names and whether it terminates an "
    "ownership chain. Return JSON only."
)

_FAMILY = re.compile(r"\b(family|families|clan|heirs|estate of)\b", re.I)
_FUND = re.compile(r"\b(capital|partners|equity|fund|holdings? (ltd|llc|lp)|invest)\b", re.I)
_FOUNDATION = re.compile(r"\b(foundation|stichting|trust|fundaci[oó]n)\b", re.I)
_COMPANY = re.compile(
    r"\b(s\.?a\.?u?|b\.?v\.?|n\.?v\.?|gmbh|kg|ltd|limited|llc|inc|plc|s\.?l\.?|s\.?p\.?a\.?|"
    r"oyj|ab|a/s|group|corp|co\.)\b", re.I)
_PERSON = re.compile(r"^[A-ZÁÉÍÓÚÑÜ][\w'’\-]+(?:\s+[A-ZÁÉÍÓÚÑÜ][\w'’\-]+){1,3}$")
_CORPORATE_WORD = re.compile(
    r"\b(company|industries|foods?|brands?|international|holdings?|beheer|"
    r"group|groep|gruppo|grupo|sektkellerei|kellerei|verwaltung|konzern)\b", re.I)


def _heuristic(name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback. Cheap, instant, good enough to ship without Pioneer.

    Biased towards `company`: in an ownership chain most nodes are corporate, and
    mislabelling a company as a person ends the dig one hop in. A chain only
    terminates on an explicit signal — a family, a foundation, or a row that
    carries a personal role or a stake percentage.
    """
    n = (name or "").strip()
    has_person_signal = bool(row.get("role") or row.get("ownership_percent"))

    if _FAMILY.search(n):
        kind, conf, terminal = "family", 0.86, True
    elif _FOUNDATION.search(n):
        kind, conf, terminal = "foundation", 0.8, True
    elif _COMPANY.search(n) or _CORPORATE_WORD.search(n):
        kind, conf, terminal = "company", 0.88, False
    elif _FUND.search(n):
        kind, conf, terminal = "fund", 0.74, False
    elif has_person_signal and _PERSON.match(n) and len(n.split()) <= 3:
        kind, conf, terminal = "person", 0.76, True
    elif _PERSON.match(n) and len(n.split()) <= 3:
        # Two or three capitalised words with no corporate marker: ambiguous.
        # "Juan Roig" and "Perfetti Van Melle" look identical to a regex, so we
        # keep digging and let the next hop disambiguate.
        kind, conf, terminal = "unknown", 0.5, False
    else:
        kind, conf, terminal = "company", 0.6, False

    if has_person_signal:
        conf = min(0.95, conf + 0.06)
    return {"kind": kind, "confidence": round(conf, 2), "terminal": terminal}


class PioneerClient:
    """Classification and extraction. Falls back to `_heuristic` without a key."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=settings.assay_timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def backend(self) -> str:
        return f"pioneer:{settings.model_assay}" if settings.has_pioneer else "heuristic"

    async def assay(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """One call for the whole batch — never one call per row."""
        names = [
            (r.get("owner") or r.get("name") or r.get("shareholder") or "").strip()
            for r in rows
        ]
        fallback = [_heuristic(n, r) for n, r in zip(names, rows)]
        if not settings.has_pioneer or not names:
            return fallback

        try:
            r = await self._client.post(
                f"{settings.pioneer_base}/chat/completions",
                json={
                    "model": settings.model_assay,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "adaptive": settings.pioneer_adaptive,
                    "messages": [
                        {"role": "system", "content": _ASSAY_SYSTEM},
                        {"role": "user", "content":
                            f"Rows: {json.dumps(rows, ensure_ascii=False)[:4000]}\n"
                            'Return {"items":[{"kind":"company|person|family|fund|foundation|unknown",'
                            '"confidence":0-1,"terminal":bool}]} in the same order.'},
                    ],
                },
                headers={"Authorization": f"Bearer {settings.pioneer_key}"},
                timeout=settings.assay_timeout_s,
            )
            r.raise_for_status()
            body = r.json()
            items = json.loads(body["choices"][0]["message"]["content"]).get("items") or []
            score = body.get("adaptive_score")
            out: list[dict[str, Any]] = []
            for i, fb in enumerate(fallback):
                it = items[i] if i < len(items) and isinstance(items[i], dict) else {}
                out.append({
                    "kind": it.get("kind", fb["kind"]),
                    "confidence": float(it.get("confidence", score if score is not None else fb["confidence"])),
                    "terminal": bool(it.get("terminal", fb["terminal"])),
                })
            return out
        except Exception:
            return fallback
