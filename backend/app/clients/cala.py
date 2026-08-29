"""Cala — the only thing in Bedrock allowed to state a fact.

Measured behaviour this client is built around (see docs/AGENTS.md):
  * POST /v1/knowledge/query   -> {"results": [ ...typed rows... ]}
  * POST /v1/knowledge/search  -> {"content": md,
                                   "explainability": [{content, references}],
                                   "context": [{id, content, origins:[{source, document,
                                                breadcrumb}]}]}
    `context` is where the citations actually live. `explainability` names fact
    ids; `context[].origins[].document.url` resolves them to documents a reader
    can open - GLEIF LEI records, company registries, trade press. Without this
    every citation we render is a query string and nothing a person can click.
  * POST /v1/entities/{id}     -> properties, each carrying its own `sources` array
  * GET  /v1/entities?name=X   -> fuzzy *string* match, not semantic
  * Cold 16-75s, warm ~0.5s. Rate limited at roughly six rapid calls.
  * `knowledge/query` occasionally answers {"error": "This question is too
    complex to answer fully."} — ask something narrower rather than retrying.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import cache
from ..config import settings


@dataclass
class CalaResult:
    query: str
    endpoint: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    content: str | None = None
    fact_ids: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    latency_s: float = 0.0
    cached: bool = False
    error: str | None = None

    @property
    def empty(self) -> bool:
        return not self.rows and not self.content


class CalaClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=settings.probe_timeout_s)
        # Cala rate-limits hard; one shared semaphore keeps every agent polite.
        self._gate = asyncio.Semaphore(settings.max_concurrent_probes)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def query(self, text: str) -> CalaResult:
        return await self._call("query", text)

    async def search(self, text: str) -> CalaResult:
        return await self._call("search", text)

    async def _call(self, kind: str, text: str) -> CalaResult:
        endpoint = f"knowledge/{kind}"
        hit = cache.get(kind, text)
        if hit is not None:
            return self._shape(text, endpoint, hit["payload"], hit.get("latency", 0.0), True)

        if not settings.has_cala:
            return CalaResult(query=text, endpoint=endpoint, error="CALA_API_KEY not set")

        async with self._gate:
            t0 = time.perf_counter()
            try:
                r = await self._client.post(
                    f"{settings.cala_base}/v1/{endpoint}",
                    json={"input": text},
                    headers={"X-API-KEY": settings.cala_key, "Content-Type": "application/json"},
                    timeout=settings.probe_timeout_s,
                )
                elapsed = time.perf_counter() - t0
                if r.status_code == 429:
                    await asyncio.sleep(8)
                    return CalaResult(query=text, endpoint=endpoint, latency_s=elapsed,
                                      error="rate_limited")
                r.raise_for_status()
                payload = r.json()
            except httpx.TimeoutException:
                return CalaResult(query=text, endpoint=endpoint,
                                  latency_s=time.perf_counter() - t0, error="timeout")
            except Exception as exc:  # noqa: BLE001 - a failed probe becomes a Gap, never a 500
                return CalaResult(query=text, endpoint=endpoint,
                                  latency_s=time.perf_counter() - t0, error=str(exc)[:200])

        cache.put(kind, text, payload, round(elapsed, 2))
        return self._shape(text, endpoint, payload, elapsed, False)

    @staticmethod
    def _shape(query: str, endpoint: str, payload: Any, latency: float, cached: bool) -> CalaResult:
        res = CalaResult(query=query, endpoint=endpoint,
                         latency_s=round(latency, 2), cached=cached)
        if not isinstance(payload, dict):
            res.error = "unexpected payload"
            return res

        rows = payload.get("results")
        if isinstance(rows, list):
            # Cala signals an over-broad question as a single {"error": ...} row.
            if len(rows) == 1 and isinstance(rows[0], dict) and set(rows[0]) == {"error"}:
                res.error = "too_complex"
            else:
                res.rows = [r for r in rows if isinstance(r, dict)]

        if isinstance(payload.get("content"), str):
            res.content = payload["content"]

        for item in payload.get("explainability") or []:
            for ref in (item or {}).get("references") or []:
                if ref not in res.fact_ids:
                    res.fact_ids.append(ref)

        # `context[]` is the only place Cala returns a citable URL, and each entry
        # carries the publisher next to the document. Keep them paired: a bare URL
        # cannot be rendered as "The Guardian", and a citation nobody can attribute
        # is barely a citation. `documents` stays as the flat list callers already
        # use; `citations` is the same information with its provenance intact.
        for ctx in payload.get("context") or []:
            if not isinstance(ctx, dict):
                continue
            cid = ctx.get("id")
            if isinstance(cid, str) and cid not in res.fact_ids:
                res.fact_ids.append(cid)
            for origin in ctx.get("origins") or []:
                if not isinstance(origin, dict):
                    continue
                doc = origin.get("document") if isinstance(origin.get("document"), dict) else {}
                src = origin.get("source") if isinstance(origin.get("source"), dict) else {}
                # Fall back to the source URL: some origins carry a publisher
                # without a resolvable document, and half a citation beats none.
                url = doc.get("url") or src.get("url")
                if not isinstance(url, str) or not url.startswith("http"):
                    continue
                if url in res.documents:
                    continue
                res.documents.append(url)
                res.citations.append({
                    "id": cid or "",
                    "publisher": src.get("name") or doc.get("name") or "",
                    "url": url,
                })

        # rows sometimes carry a comma-joined `source` column of fact ids
        for row in res.rows:
            src = row.get("source")
            if isinstance(src, str):
                for fid in (s.strip() for s in src.split(",")):
                    if fid and fid not in res.fact_ids:
                        res.fact_ids.append(fid)
        return res
