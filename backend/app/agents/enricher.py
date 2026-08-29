"""Turning a question into citable Evidence.

`knowledge/query` returns typed rows and no sources. `knowledge/search` returns
prose plus the chain that makes a claim citable:

    explainability[i].content     the claim
    explainability[i].references  -> context[j].id
    context[j].origins[k]         -> document.url + source.name

This agent walks that chain. It selects and pairs; it never writes a claim.
"""
from __future__ import annotations

from typing import Any

from ..schemas import Evidence, EvidenceSource


class EnricherAgent:
    name = "enricher"

    def __init__(self, cala: Any) -> None:
        self.cala = cala

    async def evidence_for(self, question: str, scope: str,
                           date: str | None = None) -> list[Evidence]:
        res = await self.cala.search(question)
        by_id = {c["id"]: c for c in getattr(res, "citations", []) if c.get("id")}
        out: list[Evidence] = []
        for item in getattr(res, "explainability", []):
            claim = (item or {}).get("content")
            if not isinstance(claim, str) or not claim.strip():
                continue
            sources = [
                EvidenceSource(publisher=by_id[ref].get("publisher") or None,
                               url=by_id[ref].get("url") or None,
                               query=question)
                for ref in (item or {}).get("references") or [] if ref in by_id
            ]
            # No resolvable citation means no user-facing fact.
            if not sources:
                continue
            out.append(Evidence(claim=claim.strip(), scope=scope,
                                date=date, sources=sources))
        return out
