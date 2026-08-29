"""OpenAI — the reasoning engine.

Hard boundary, enforced by review and by the schema: this client is allowed to
*plan*, *parse* and *read a label*. It is never allowed to assert a fact about a
company. Nothing it returns is placed in a field that carries a `Source`.

  plan()    -> which Cala probes to run for this subject
  parse()   -> turn Cala's loosely-typed rows into our Layer shape
  read()    -> OCR a brand name off a photograph
"""
from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from ..config import settings

_PLANNER_SYSTEM = (
    "You plan database lookups. You never answer from your own knowledge and you "
    "never state a fact about a company. You only choose which questions to ask.\n"
    "Return JSON only."
)


class LLMClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=settings.planner_timeout_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _chat(self, messages: list[dict[str, Any]], *, model: str,
                    timeout: float, json_mode: bool = True) -> dict[str, Any] | None:
        if not settings.has_openai:
            return None
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = await self._client.post(
                f"{settings.openai_base}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {settings.openai_key}"},
                timeout=timeout,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            return json.loads(text) if json_mode else {"text": text}
        except Exception:
            return None

    # ----------------------------------------------------------------- plan
    async def plan(self, subject: str, depth: int, include: list[str]) -> dict[str, Any] | None:
        """Choose the probe set for this subject. Falls back to the static ladder."""
        prompt = (
            f'Subject: "{subject}". Sections requested: {include}. Max ownership hops: {depth}.\n'
            "Produce lookup questions for a corporate-registry knowledge graph.\n"
            'Return {"ownership_seed": str, "supply": [str], "statute": [str], '
            '"flags": [str], "siblings": str}.\n'
            "Rules: each string is a single narrow question or a dotted path such as "
            '"Brand.manufactured_by". Broad questions are rejected by the graph, so keep '
            "each one to a single fact. At most 2 items per list."
        )
        return await self._chat(
            [{"role": "system", "content": _PLANNER_SYSTEM}, {"role": "user", "content": prompt}],
            model=settings.model_planner,
            timeout=settings.planner_timeout_s,
        )

    # ---------------------------------------------------------------- parse
    async def parse_rows(self, question: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Normalise Cala's variable columns. Reshaping only — no new facts."""
        prompt = (
            f"Question asked: {question}\n"
            f"Rows returned verbatim: {json.dumps(rows, ensure_ascii=False)[:4000]}\n\n"
            "Reshape into JSON, copying values across unchanged. Invent nothing; if a "
            "field is absent from the rows, use null.\n"
            '{"name": str, "kind": "company|person|family|fund|foundation|unknown", '
            '"country": ISO-3166-alpha-2 or null, "city": str|null, "address": str|null, '
            '"stake_percent": number|null, "relationship": str|null, "detail": [str]}'
        )
        return await self._chat(
            [{"role": "system", "content": _PLANNER_SYSTEM}, {"role": "user", "content": prompt}],
            model=settings.model_planner,
            timeout=settings.planner_timeout_s,
        )

    # ----------------------------------------------------------------- read
    async def read_label(self, image_b64: str, mime: str = "image/jpeg") -> str | None:
        """Vision does exactly one job: transcribe the brand name printed on a package."""
        if not settings.has_openai:
            return None
        try:
            r = await self._client.post(
                f"{settings.openai_base}/chat/completions",
                json={
                    "model": settings.model_vision,
                    "max_tokens": 40,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text":
                            "Transcribe the brand name printed on this product. Reply with the "
                            "brand name alone. If none is legible reply exactly: UNKNOWN"},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    ]}],
                },
                headers={"Authorization": f"Bearer {settings.openai_key}"},
                timeout=30.0,
            )
            r.raise_for_status()
            out = r.json()["choices"][0]["message"]["content"].strip()
            return None if out.upper() == "UNKNOWN" else out
        except Exception:
            return None
