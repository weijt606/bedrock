"""fal — a short loop to sit beside the findings.

The video is **illustrative and carries no facts**. It never receives a claim,
a number, a location or an allegation as an instruction: those are rendered as
selectable text next to it, which is the boundary `docs/EXTRACTOR_OUTPUT.md`
draws and the reason a generated frame can never be mistaken for evidence.

Two routes, decided by whether the person gave us a photograph:

    photo   -> image-to-video, keeping their real packaging recognisable
    no photo-> text-to-video, abstract material only, no branded packshot

Inventing a branded packshot is the visual equivalent of inventing a fact, so
the text route describes materials and light and never a product.

Generation takes 30-120s, far longer than a request should wait, so this uses
fal's queue: submit returns a request id immediately and the dig carries on.
By the time the reader reaches the end of the deck the loop is usually there,
and when it is not the interface simply never shows it.
"""
from __future__ import annotations

import base64
import logging

import httpx

from ..config import settings

logger = logging.getLogger("bedrock.falvideo")

QUEUE = "https://queue.fal.run"
UPLOAD_INITIATE = "https://rest.alpha.fal.ai/storage/upload/initiate"

# One template, filled from values Cala returned. The negative list is the
# guardrail: no people, no farms, no factories, and no text of any kind, because
# a video model cannot spell and a misspelt citation is worse than none.
PROMPT = (
    "A 6-second seamless editorial motion loop{ref}. "
    "{subject_line}"
    "Around and behind it, subtle abstract material textures inspired by "
    "{motifs} emerge as translucent layers. Fine warm filaments extend outward "
    "like an invisible network, then return.\n\n"
    "Art direction: {palette}; premium investigative magazine; quiet, precise, "
    "elegant, restrained camera motion. The animation is metaphorical, not "
    "documentary.\n\n"
    "No people, workers, children, farms, factories, maps, flags, captions, "
    "numbers, charts, voice, music, invented text, or invented logos."
)

WITH_PHOTO = (
    "Keep the product packaging recognizable, stable and physically realistic; "
    "do not alter its label or logo. The {form} sits on a dark, tactile "
    "editorial surface. "
)
WITHOUT_PHOTO = (
    "A dark, tactile editorial surface lit like a still life, with no product "
    "and no subject in frame. "
)

PALETTE = "deep brown, cream, muted red"


def build_prompt(motifs: list[str], form: str | None, has_photo: bool) -> str:
    """Fill the template. `motifs` are ingredients Cala actually returned."""
    return PROMPT.format(
        ref=" based on the supplied reference image" if has_photo else "",
        subject_line=(WITH_PHOTO.format(form=form or "product") if has_photo
                      else WITHOUT_PHOTO),
        motifs=", ".join(motifs[:3]) if motifs else "raw natural materials",
        palette=PALETTE,
    )


class FalVideoClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def ready(self) -> bool:
        return bool(settings.fal_key and settings.fal_video_model)

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Key {settings.fal_key}"}

    async def upload(self, raw_b64: str, mime: str = "image/jpeg") -> str | None:
        """Put the reader's photo in fal storage. The model reads the extension
        off the URL, so a data URI is rejected — measured in falstt.py."""
        ext = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
        try:
            r = await self._client.post(
                UPLOAD_INITIATE, headers=self._auth,
                json={"content_type": mime, "file_name": f"subject.{ext}"})
            r.raise_for_status()
            slot = r.json()
            put = await self._client.put(
                slot["upload_url"], content=base64.b64decode(raw_b64),
                headers={"Content-Type": mime})
            put.raise_for_status()
            return slot["file_url"]
        except Exception as exc:  # noqa: BLE001 - no video is not an error
            logger.warning("fal image upload failed: %s", type(exc).__name__)
            return None

    async def submit(self, prompt: str, image_url: str | None = None) -> str | None:
        """Queue the job. Returns a request id, or None if we cannot start."""
        if not self.ready:
            return None
        body: dict[str, object] = {
            "prompt": prompt,
            "duration": settings.fal_video_seconds,
            "aspect_ratio": "16:9",
        }
        if image_url:
            body["image_url"] = image_url
        try:
            r = await self._client.post(
                f"{QUEUE}/{settings.fal_video_model}", headers=self._auth, json=body)
            r.raise_for_status()
            return r.json().get("request_id")
        except Exception as exc:  # noqa: BLE001
            logger.warning("fal video submit failed: %s", type(exc).__name__)
            return None

    async def poll(self, request_id: str) -> tuple[str, str | None]:
        """('pending'|'ready'|'unavailable', url). Never raises: a loop that
        does not arrive is a loop the interface does not show."""
        if not self.ready or not request_id:
            return ("unavailable", None)
        model = settings.fal_video_model
        try:
            st = await self._client.get(
                f"{QUEUE}/{model}/requests/{request_id}/status", headers=self._auth)
            st.raise_for_status()
            status = st.json().get("status")
            if status in {"IN_QUEUE", "IN_PROGRESS"}:
                return ("pending", None)
            if status != "COMPLETED":
                return ("unavailable", None)
            res = await self._client.get(
                f"{QUEUE}/{model}/requests/{request_id}", headers=self._auth)
            res.raise_for_status()
            return ("ready", _video_url(res.json()))
        except Exception as exc:  # noqa: BLE001
            logger.warning("fal video poll failed: %s", type(exc).__name__)
            return ("unavailable", None)


def _video_url(data: dict) -> str | None:
    """fal wraps the file differently per model; take the first url we recognise."""
    for key in ("video", "output", "result"):
        node = data.get(key)
        if isinstance(node, dict) and isinstance(node.get("url"), str):
            return node["url"]
        if isinstance(node, str) and node.startswith("http"):
            return node
    videos = data.get("videos")
    if isinstance(videos, list) and videos and isinstance(videos[0], dict):
        return videos[0].get("url")
    return None
