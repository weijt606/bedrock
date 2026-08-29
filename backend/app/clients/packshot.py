"""Finding a picture of the thing, and cutting it out.

The hero puts the product on top of the strata it is made of, so the page needs
a picture of whatever the person just named — with no background, or the illusion
breaks and it looks like a sticker.

Two jobs, and both of them are *reading*, never asserting:

    find(name)      -> an official packshot from Open Food Facts, else Wikipedia
    cut_out(bytes)  -> the same image with its background removed, via fal

Open Food Facts first because it is a food database: its `image_front_url` is the
photograph off the actual packet, contributed and checked by people, under an
open licence. Wikipedia is the fallback for anything that is a brand rather than
a barcode. Both are attributed in the response — a picture we did not take is a
citation like any other.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

OFF_SEARCH = "https://world.openfoodfacts.org/api/v2/search"
OFF_CGI = "https://world.openfoodfacts.org/cgi/search.pl"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
UA = "Bedrock/0.1 (TechEurope Barcelona hackathon)"

BIREFNET = "fal-ai/birefnet/v2"
UPLOAD_INITIATE = "https://rest.alpha.fal.ai/storage/upload/initiate"


class PackshotClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ find
    async def find(self, name: str) -> dict[str, Any] | None:
        """An official picture of the named product, with its attribution."""
        return await self._open_food_facts(name) or await self._wikipedia(name)

    async def _open_food_facts(self, name: str) -> dict[str, Any] | None:
        products = await self._off_query(OFF_SEARCH, {
            "search_terms": name, "page_size": 20,
            "fields": "product_name,brands,image_front_url",
        })
        if not products:
            # v2 is intermittently unavailable; the older CGI endpoint answers the
            # same question and is the one that has never been down on us.
            products = await self._off_query(OFF_CGI, {
                "search_terms": name, "search_simple": 1, "action": "process",
                "json": 1, "page_size": 20,
            })

        wanted = _fold(name)
        for product in products:
            blob = _fold(f"{product.get('product_name') or ''} "
                         f"{product.get('brands') or ''}")
            # A full-text search will cheerfully return a biscuit for "Coca-Cola".
            # Showing the wrong packshot is worse than showing none: the hero says
            # "this is the thing you asked about", so a near miss is a lie. If
            # nothing actually matches, fall through to Wikipedia.
            if wanted not in blob:
                continue
            url = product.get("image_front_url")
            if isinstance(url, str) and url.startswith("http"):
                return {"url": url,
                        "title": product.get("product_name") or name,
                        "publisher": "Open Food Facts",
                        "attribution": "openfoodfacts.org · CC BY-SA"}
        return None

    async def _off_query(self, endpoint: str, params: dict) -> list[dict[str, Any]]:
        try:
            r = await self._client.get(endpoint, params=params,
                                       headers={"User-Agent": UA}, timeout=20.0)
            r.raise_for_status()
            return [p for p in (r.json().get("products") or []) if isinstance(p, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("open food facts (%s) failed: %s",
                           endpoint.rsplit("/", 1)[-1], type(exc).__name__)
            return []

    async def _wikipedia(self, name: str) -> dict[str, Any] | None:
        try:
            r = await self._client.get(WIKI_SEARCH, params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": name, "gsrlimit": 3, "prop": "pageimages",
                "piprop": "original", "pilicense": "any",
            }, headers={"User-Agent": UA}, timeout=20.0)
            r.raise_for_status()
            pages = (r.json().get("query") or {}).get("pages") or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("wikipedia lookup failed: %s", type(exc).__name__)
            return None

        for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
            url = (page.get("original") or {}).get("source")
            if isinstance(url, str) and url.startswith("http"):
                return {"url": url, "title": page.get("title") or name,
                        "publisher": "Wikipedia",
                        "attribution": "wikipedia.org"}
        return None

    # --------------------------------------------------------------- cut out
    async def cut_out(self, image_url: str) -> str | None:
        """Remove the background so the product sits on the rock, not in a box.

        BiRefNet is the honest use of a generative-media API here: it does not
        invent a pixel, it decides which of the photographer's pixels are the
        subject. A generated product image in a piece about verified facts would
        undo the entire argument.
        """
        if not settings.has_fal:
            return None
        try:
            r = await self._client.post(
                f"https://fal.run/{BIREFNET}",
                json={"image_url": image_url,
                      # Heavy keeps thin structures — a bottle neck, a straw, a
                      # lollipop stick — that Light shears off.
                      "model": "General Use (Heavy)",
                      "operating_resolution": "1024x1024",
                      "refine_foreground": True,
                      "output_format": "png"},
                headers={"Authorization": f"Key {settings.fal_key}",
                         "Content-Type": "application/json"},
                timeout=90.0)
            r.raise_for_status()
            return ((r.json().get("image") or {}).get("url")) or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("birefnet cut-out failed: %s", type(exc).__name__)
            return None

    async def upload(self, raw: bytes, mime: str = "image/jpeg") -> str | None:
        """Put a browser upload in fal storage so BiRefNet can reach it by URL."""
        if not settings.has_fal:
            return None
        ext = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
        try:
            init = await self._client.post(
                UPLOAD_INITIATE,
                json={"content_type": mime, "file_name": f"shot.{ext}"},
                headers={"Authorization": f"Key {settings.fal_key}",
                         "Content-Type": "application/json"}, timeout=30.0)
            init.raise_for_status()
            slot = init.json()
            put = await self._client.put(slot["upload_url"], content=raw,
                                         headers={"Content-Type": mime}, timeout=90.0)
            put.raise_for_status()
            return slot["file_url"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("fal upload failed: %s", type(exc).__name__)
            return None


def _fold(text: str) -> str:
    """Ignore case, hyphens and spacing so "coca-cola" matches "Coca Cola"."""
    return "".join(c for c in (text or "").lower() if c.isalnum())
