"""Where the loop is remembered.

Three things were wrong with keeping the job in a dict:

  * the file lives on fal's CDN and we held only a request id, so a restart
    lost every video that had already been paid for and generated;
  * the id was keyed by sample, so the *same product* searched twice generated
    twice — two waits, two invoices, two different loops;
  * warming the cache before a demo did nothing for media at all.

So this reuses the same disk cache the Cala answers use: permanent, shared, and
warmed on purpose. The key is the one `docs/EXTRACTOR_OUTPUT.md` asks for —
resolved product, style version, reference image — so changing the prompt
invalidates every loop without anybody having to clear a directory.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib

import httpx

from . import cache

logger = logging.getLogger("bedrock.media")

# Bump when PROMPT, PALETTE or the route logic in falvideo.py changes. Old loops
# were made from a different brief and should not be served as if they were not.
STYLE_VERSION = "3"


def key(product: str, image_b64: str | None = None) -> str:
    """resolved product + style version + reference image hash."""
    img = hashlib.sha1(image_b64.encode()).hexdigest()[:12] if image_b64 else "none"
    return f"{(product or '').strip().lower()}|{STYLE_VERSION}|{img}"


def remember_job(k: str, model: str, request_id: str) -> None:
    """A job in flight. Kept so a restart resumes polling instead of resubmitting."""
    cache.put("video", k, {"model": model, "request_id": request_id}, 0.0)


def remember_url(k: str, url: str) -> None:
    """The finished file. From here the same product never generates again."""
    cache.put("video", k, {"url": url}, 0.0)


def recall(k: str) -> dict | None:
    hit = cache.get("video", k)
    return (hit or {}).get("payload") if hit else None


def bind(sample_id: str, k: str) -> None:
    """Point a sample at its video key, on disk, so `/media` still answers
    after the process that started the dig is gone."""
    cache.put("video-sample", sample_id, {"key": k}, 0.0)


def key_for(sample_id: str) -> str | None:
    hit = cache.get("video-sample", sample_id)
    payload = (hit or {}).get("payload") if hit else None
    return (payload or {}).get("key")


# --------------------------------------------------------------------------- #
#  the file itself
# --------------------------------------------------------------------------- #
#
# Holding fal's CDN link is not the same as having the video. Those URLs expire,
# and a demo runs on whatever network the venue has. So the bytes come down once
# and are served from here; the remote link stays in the cache only as the thing
# we fetched from.


def slug(k: str) -> str:
    """A stable, path-safe name for a key. Same hash the JSON cache uses."""
    return hashlib.sha1(k.encode()).hexdigest()[:16]


def file_path(k: str) -> pathlib.Path:
    # One notion of "the cache directory", the same one the JSON answers use.
    return cache._dir / f"video-{slug(k)}.mp4"


def local_url(k: str) -> str:
    return f"/v1/media/{slug(k)}.mp4"


def file_for_slug(name: str) -> pathlib.Path | None:
    """Resolve a served name back to a file, refusing anything that is not one
    of ours — the name comes off the URL, so it is never trusted as a path."""
    if not name.isalnum() or len(name) != 16:
        return None
    p = cache._dir / f"video-{name}.mp4"
    return p if p.exists() else None


async def download(k: str, url: str) -> bool:
    """Fetch the loop once. Returns False and leaves no file behind on failure,
    so the caller can keep serving the remote link instead."""
    dest = file_path(k)
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.rename(dest)          # atomic, so a half file is never served
        return True
    except Exception as exc:  # noqa: BLE001 - a missing file is not an error
        logger.warning("video download failed: %s", type(exc).__name__)
        return False
