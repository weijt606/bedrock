"""Input of any kind becomes one Subject.

  text   passthrough
  image  OpenAI vision reads the brand name off the packaging
  audio  fal Whisper transcribes it

Then Cala's entity search is asked to resolve that string to a real entity, so
that everything downstream is anchored on an id rather than on a guess.
"""
from __future__ import annotations

import re

import httpx

from ..clients.cala import CalaClient
from ..clients.falstt import FalClient
from ..clients.llm import LLMClient
from ..config import settings
from ..schemas import InputKind, SampleRequest, Subject

_STRIP = re.compile(r"^(what is|who owns|tell me about|the)\s+", re.I)


class IntakeAgent:
    name = "intake"

    def __init__(self, cala: CalaClient, llm: LLMClient, fal: FalClient) -> None:
        self.cala, self.llm, self.fal = cala, llm, fal

    async def run(self, req: SampleRequest) -> Subject:
        raw, how = "", "text"

        if req.kind is InputKind.image and req.image_b64:
            raw = await self.llm.read_label(req.image_b64, req.mime or "image/jpeg") or ""
            how = "vision"
        elif req.kind is InputKind.audio and req.audio_b64:
            raw = await self.fal.transcribe(req.audio_b64, req.mime or "audio/webm") or ""
            how = "speech"
        else:
            raw = (req.text or "").strip()

        cleaned = _STRIP.sub("", raw).strip(" ?.!\"'")
        if not cleaned:
            return Subject(raw_input=raw, resolved_name="", confidence=0.0,
                           identified_by=how)  # type: ignore[arg-type]

        subject = Subject(raw_input=raw or cleaned, resolved_name=cleaned,
                          confidence=0.55, identified_by=how)  # type: ignore[arg-type]

        ent = await self._resolve(cleaned)
        if ent:
            subject.entity_id = ent.get("id")
            subject.entity_type = ent.get("entity_type")
            subject.description = ent.get("description")
            subject.resolved_name = ent.get("name") or cleaned
            subject.confidence = 0.9
        return subject

    async def _resolve(self, name: str) -> dict | None:
        """entity_search is a fuzzy *string* match, so prefer Product/Company/Brand
        rows over the pile of unrelated shell companies that share a substring."""
        if not settings.has_cala:
            return None
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.get(f"{settings.cala_base}/v1/entities",
                                params={"name": name},
                                headers={"X-API-KEY": settings.cala_key})
                r.raise_for_status()
                ents = r.json().get("entities") or []
        except Exception:
            return None

        low = name.lower()
        ranked = sorted(
            ents,
            key=lambda e: (
                0 if (e.get("name") or "").lower() == low else 1,
                {"Product": 0, "Company": 1, "Organization": 2, "WorkOfArt": 3}.get(
                    e.get("entity_type") or "", 4),
            ),
        )
        return ranked[0] if ranked else None
