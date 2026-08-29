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
# One template, filled from values Cala returned.
#
# Rewritten after watching the first output. Video models render concrete nouns
# and fail at metaphor: the first draft said "no product in frame" and then
# "around and behind it", leaving `it` with no referent, and asked for an
# "invisible network" — so the model invented whatever it liked. It also carried
# the whole negative list in the positive field, where a model is as likely to
# draw a factory as to omit one.
#
# So: one subject, one light, one camera move, and the materials named plainly.
PROMPT_WITH_PHOTO = (
    "The {form} in the reference image stays exactly as it is — sharp, centred "
    "and unchanged, its label and logo untouched. {motif_line}"
    "Very slow push-in. Shallow depth of field, one soft key light. "
    "Editorial product photography, {palette}. No cuts, no text, no people."
)

PROMPT_NO_PHOTO = (
    "Extreme close-up of {motifs}. Slow steady push-in. Shallow depth of field, "
    "one soft key light, fine dust in the air. Editorial product photography, "
    "{palette}. Static composition, no cuts, no text, no people."
)

MOTIF_LINE = "Raw {motifs} drift slowly into frame around it, catching the light. "

# Was "deep brown, cream, muted red" — Nutella's own colours, which made every
# other product look like it had been shot on the wrong set. The look is now
# described by light and restraint, and the product supplies the colour.
PALETTE = "muted, low-saturation editorial colour, natural light"


# Not every ingredient is a thing you can photograph. Cala returns Pepsi's list
# as "Carbonated Water, High Fructose Corn Syrup, Caramel Color, Phosphoric
# Acid" — all true, none filmable, and asking a renderer for a close-up of
# phosphoric acid produces exactly the mush it sounds like.
#
# This is a *visual* filter, not a factual one: it decides what can appear on
# screen, never what is true. An ingredient that fails it is still in the data
# and still on the cards; it just does not get filmed.
FILMABLE = (
    "hazelnut", "almond", "peanut", "cocoa", "coffee", "bean", "nut",
    "barley", "wheat", "rice", "oat", "corn", "maize", "grain", "malt", "hop",
    "sugar", "salt", "milk", "cream", "butter", "honey", "vanilla",
    "olive", "palm", "seed", "leaf", "tea", "fruit", "orange", "lemon",
    "apple", "cherry", "grape", "berry", "tomato", "potato", "pepper", "spice",
)

# A word above is not enough on its own: both "corn" and "palm" occur in
# ingredients that are chemically accurate but do not give the renderer a
# tangible subject (corn syrup, palm oil).  Prefer a short, honest motif list
# to asking the model to visualise a liquid additive.
NON_VISUAL_FORMS = ("acid", "color", "colour", "caffeine", "water", "syrup", "oil")


def filmable(motifs: list[str]) -> list[str]:
    """Keep only the materials that exist as objects in front of a camera."""
    out = []
    for m in motifs:
        low = m.lower()
        if (any(w in low for w in FILMABLE)
                and not any(form in low for form in NON_VISUAL_FORMS)):
            out.append(m)
    return out


def build_prompt(motifs: list[str], form: str | None, has_photo: bool) -> str:
    """Fill the template. `motifs` are ingredients Cala actually returned."""
    named = ", ".join(filmable(motifs)[:3])
    if has_photo:
        # No ingredients from Cala means no ingredients on screen. The earlier
        # fallback named cocoa and hazelnuts, so a Pepsi search was filmed with
        # Nutella's ingredients — an invented fact, in pictures.
        return PROMPT_WITH_PHOTO.format(
            form=form or "product",
            motif_line=MOTIF_LINE.format(motifs=named) if named else "",
            palette=PALETTE)
    return PROMPT_NO_PHOTO.format(
        motifs=named or "a plain dark surface under a single soft light",
        palette=PALETTE)


class FalVideoClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def ready(self) -> bool:
        return settings.has_video

    @staticmethod
    def model_for(has_image: bool) -> str:
        """fal splits the two routes across two models; fall back to the other
        when only one is configured, so a half-configured setup still works."""
        i2v, t2v = settings.fal_video_i2v, settings.fal_video_t2v
        return (i2v or t2v) if has_image else (t2v or i2v)

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

    async def mirror(self, url: str) -> str | None:
        """Fetch a third-party picture and re-host it on fal storage.

        Handing fal someone else's URL fails: Wikimedia blocks its user agent,
        and the job completes with `file_download_error` rather than an obvious
        failure at submit. Fetching the bytes ourselves — with a browser-shaped
        user agent, which is what Wikimedia asks for — sidesteps the whole class
        of problem, whatever the packshot source turns out to be.
        """
        try:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as c:
                r = await c.get(url, headers={"User-Agent": "Bedrock/0.1 (hackathon project)"})
                r.raise_for_status()
                mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
                if mime not in {"image/jpeg", "image/png", "image/webp"}:
                    # Wikipedia often answers with an SVG — that is the brand's
                    # logo, not a photograph of the thing. Feeding a flat vector
                    # to image-to-video produces exactly the mush it sounds like,
                    # so we decline and let the text route handle it.
                    logger.info("packshot is %s, not a photograph; skipping", mime)
                    return None
                return await self.upload(base64.b64encode(r.content).decode(), mime)
        except Exception as exc:  # noqa: BLE001 - no picture is not an error
            logger.warning("packshot mirror failed: %s", type(exc).__name__)
            return None

    async def submit(self, prompt: str,
                     image_url: str | None = None) -> tuple[str, str] | None:
        """Queue the job. Returns (model, request_id) — the model travels with
        the id because polling happens on the same endpoint that accepted it."""
        if not self.ready:
            return None
        model = self.model_for(bool(image_url))
        if not model:
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
                f"{QUEUE}/{model}", headers=self._auth, json=body)
            r.raise_for_status()
            rid = r.json().get("request_id")
            return (model, rid) if rid else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("fal video submit failed: %s", type(exc).__name__)
            return None

    @staticmethod
    def _status_base(model: str) -> str:
        """fal submits to the full endpoint but reports status on the app id.

            submit  queue.fal.run/minimax/h3-max/text-to-video
            status  queue.fal.run/minimax/h3-max/requests/{id}/status

        Polling the submit path returns a 404, which is how this was found.
        """
        return "/".join(model.split("/")[:2])

    async def poll(self, model: str, request_id: str) -> tuple[str, str | None]:
        """('pending'|'ready'|'unavailable', url). Never raises: a loop that
        does not arrive is a loop the interface does not show."""
        if not self.ready or not request_id or not model:
            return ("unavailable", None)
        base = self._status_base(model)
        try:
            st = await self._client.get(
                f"{QUEUE}/{base}/requests/{request_id}/status", headers=self._auth)
            st.raise_for_status()
            payload = st.json()
            status = payload.get("status")
            if status in {"IN_QUEUE", "IN_PROGRESS"}:
                return ("pending", None)
            if status != "COMPLETED":
                return ("unavailable", None)
            # Take the address fal hands back rather than reassembling it: the
            # result path is not always the status path minus /status, and
            # guessing it returned 422.
            where = payload.get("response_url") or f"{QUEUE}/{base}/requests/{request_id}"
            res = await self._client.get(where, headers=self._auth)
            res.raise_for_status()
            return ("ready", _video_url(res.json()))
        except httpx.HTTPStatusError as exc:
            # A job is not in the queue index the instant submit returns, so an
            # early 404 means "not yet", not "gone". Treating it as dead threw
            # away finished videos that were merely a second young.
            if exc.response.status_code == 404:
                return ("pending", None)
            logger.warning("fal video poll failed: %s", exc.response.status_code)
            return ("unavailable", None)
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
