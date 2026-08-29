"""fal — hearing a product name.

The model is `nvidia/nemotron-3-nano-omni/audio`, an audio-understanding model
rather than a plain transcriber: it takes a prompt alongside the clip and answers
in text. That suits us better than raw transcription, because what we need out of
a voice note is not every word — it is the one brand name in it.

The boundary is identical to vision's. The model **listens and reads back**; it
never states a fact about the thing it heard. What comes out of here is a string
that then goes to Cala like any typed one.

    POST https://fal.run/nvidia/nemotron-3-nano-omni/audio
    Authorization: Key $FAL_KEY
    {"prompt": …, "audio_url": …, "reasoning_mode": "no_think", …}  ->  {"output": …}

Two things measured the hard way:

  * A data URI is rejected. The model reads the **file extension** off the URL,
    so `data:audio/wav;base64,…` comes back 422 "Unsupported audio format" even
    though the bytes are a valid wav. The clip has to be uploaded to fal storage
    first and referenced by its returned URL.
  * Only `.wav` and `.mp3` are accepted — not the `audio/webm` a browser's
    MediaRecorder produces by default. The page therefore encodes wav itself.
"""
from __future__ import annotations

import base64
import logging
import re

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Kept deliberately narrow. A wider instruction invites the model to describe the
# recording, and everything after the brand name is noise we would have to strip.
LISTEN_PROMPT = (
    "The speaker names one product or brand. Reply with that name alone — no "
    "punctuation, no sentence, no explanation. If no product or brand is "
    "audible, reply exactly: UNKNOWN"
)
SYSTEM_PROMPT = "You transcribe a single product name. You never add information."

_STRIP = re.compile(r'^[\s"\'`]+|[\s"\'`.!?]+$')

# The model matches on extension, so the name we upload under decides whether the
# request is even considered.
_EXT = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
        "audio/mpeg": "mp3", "audio/mp3": "mp3"}
UPLOAD_INITIATE = "https://rest.alpha.fal.ai/storage/upload/initiate"


class FalClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=90.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _upload(self, raw: bytes, mime: str, ext: str) -> str | None:
        """Put the clip in fal storage and return a URL the model will accept."""
        try:
            init = await self._client.post(
                UPLOAD_INITIATE,
                json={"content_type": mime, "file_name": f"clip.{ext}"},
                headers={"Authorization": f"Key {settings.fal_key}",
                         "Content-Type": "application/json"},
                timeout=60.0)
            init.raise_for_status()
            slot = init.json()
            put = await self._client.put(slot["upload_url"], content=raw,
                                         headers={"Content-Type": mime}, timeout=120.0)
            put.raise_for_status()
            return slot["file_url"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("fal upload failed: %s", type(exc).__name__)
            return None

    async def transcribe(self, audio_b64: str, mime: str = "audio/wav") -> str | None:
        """Return the brand name heard in the clip, or None."""
        if not settings.has_fal:
            return None

        ext = _EXT.get((mime or "").split(";")[0].strip().lower())
        if ext is None:
            logger.warning("fal audio: unsupported container %r; send wav or mp3", mime)
            return None
        try:
            raw = base64.b64decode(audio_b64, validate=False)
        except Exception:
            return None

        url = await self._upload(raw, mime, ext)
        if not url:
            return None

        try:
            r = await self._client.post(
                f"https://fal.run/{settings.fal_stt_model}",
                json={
                    "prompt": LISTEN_PROMPT,
                    "system_prompt": SYSTEM_PROMPT,
                    "audio_url": url,
                    "reasoning_mode": "no_think",   # a name needs no deliberation
                    "temperature": 0,
                    "max_tokens": 32,
                },
                headers={"Authorization": f"Key {settings.fal_key}",
                         "Content-Type": "application/json"},
                timeout=90.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("fal audio request failed: %s", type(exc).__name__)
            return None
        return self._read(data)

    @staticmethod
    def _read(data: dict) -> str | None:
        """Pull the answer out, tolerating the older transcription shape.

        nemotron answers in `output`; whisper answered in `text`/`chunks`, and
        FAL_STT_MODEL can still be pointed back at it.
        """
        text = data.get("output") or data.get("text") or ""
        if not text and isinstance(data.get("chunks"), list):
            text = " ".join(c.get("text", "") for c in data["chunks"] if isinstance(c, dict))
        text = _STRIP.sub("", str(text)).strip()
        if not text or text.upper() == "UNKNOWN":
            return None
        # A name, not a paragraph. Anything longer is the model narrating.
        return text if len(text) <= 80 else None
