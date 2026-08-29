"""fal — speech to text.

Voice input is transcribed to a brand name and then thrown away. As with vision,
the model reads; it does not assert.
"""
from __future__ import annotations

import base64

import httpx

from ..config import settings


class FalClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=60.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, audio_b64: str, mime: str = "audio/webm") -> str | None:
        if not settings.has_fal:
            return None
        try:
            r = await self._client.post(
                f"https://fal.run/{settings.fal_stt_model}",
                json={"audio_url": f"data:{mime};base64,{audio_b64}", "task": "transcribe"},
                headers={"Authorization": f"Key {settings.fal_key}",
                         "Content-Type": "application/json"},
                timeout=60.0,
            )
            r.raise_for_status()
            data = r.json()
            text = data.get("text") or ""
            if not text and isinstance(data.get("chunks"), list):
                text = " ".join(c.get("text", "") for c in data["chunks"])
            return text.strip() or None
        except Exception:
            return None
