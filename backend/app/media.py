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

from . import cache

# Bump when PROMPT, PALETTE or the route logic in falvideo.py changes. Old loops
# were made from a different brief and should not be served as if they were not.
STYLE_VERSION = "1"


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
