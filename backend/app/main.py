"""Bedrock API.

    POST /v1/samples              -> {sample_id}, then stream it
    GET  /v1/samples/{id}/events  -> SSE, one frame per finding
    GET  /v1/samples/{id}         -> the finished CoreSample
    POST /v1/samples:sync         -> blocking, returns a CoreSample (tests, cache warming)
    GET  /v1/health               -> which providers are wired up

Interactive schema at /docs. That page is the contract with the front end.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from typing import Any

import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import cache
from .clients.packshot import PackshotClient
from .config import settings
from .orchestrator import Orchestrator
from .schemas import CoreSample, ImageDescriptionRequest, SampleRequest, StreamEvent, TranscriptionRequest

app = FastAPI(
    title="Bedrock",
    version="0.1.0",
    description=(
        "One drill through everything behind a product.\n\n"
        "Bedrock resolves any input — typed, photographed or spoken — to a product, "
        "then mines Cala's verified entity graph for who owns it, who makes it, which "
        "laws govern its label, and what is on the public record about it.\n\n"
        "**No language model states a fact.** LLMs plan lookups, reshape rows and read "
        "labels; every claim in a response carries a `Source` pointing back at the Cala "
        "query that produced it, with the latency it took."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_orc = Orchestrator()
_shots = PackshotClient()
_samples: dict[str, CoreSample] = {}
_streams: dict[str, asyncio.Queue] = {}
_pending: dict[str, SampleRequest] = {}


@app.on_event("shutdown")
async def _shutdown() -> None:
    await _orc.aclose()
    await _shots.aclose()


@app.get("/v1/health", tags=["meta"])
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": app.version,
        "providers": {
            "cala": settings.has_cala,
            "openai": settings.has_openai,
            "pioneer": settings.has_pioneer,
            "fal": settings.has_fal,
            # what the front end actually needs to know before offering a button
            "vision": settings.has_llm,
            "speech": settings.has_fal,
        },
        "reasoning": {
            "provider": settings.llm_provider,
            "planner": settings.planner_model if settings.has_llm else None,
            "vision": settings.vision_model if settings.has_llm else None,
        },
        "assay": {
            "backend": _orc.pioneer.backend,
            "adaptive": settings.pioneer_adaptive and settings.has_pioneer,
            "corrections_posted": _orc.pioneer.taught,
        },
        "cached_answers": cache.size(),
        "budget": {
            "probe_timeout_s": settings.probe_timeout_s,
            "total_budget_s": settings.total_budget_s,
            "max_concurrent_probes": settings.max_concurrent_probes,
        },
    }


@app.post("/v1/samples", tags=["samples"], status_code=202)
async def create_sample(req: SampleRequest) -> dict[str, str]:
    """Register a dig. Connect to /v1/samples/{id}/events to watch it happen."""
    if not (req.text or req.image_b64 or req.audio_b64):
        raise HTTPException(400, "provide text, image_b64 or audio_b64")
    sid = uuid.uuid4().hex[:12]
    _pending[sid] = req
    return {"sample_id": sid, "events": f"/v1/samples/{sid}/events",
            "result": f"/v1/samples/{sid}"}


@app.post("/v1/transcribe", tags=["input"])
async def transcribe_audio(req: TranscriptionRequest) -> dict[str, str]:
    """Turn a voice note into text with fal before it becomes a sample."""
    if not settings.has_fal:
        raise HTTPException(503, "FAL_KEY is not configured")
    text = await _orc.fal.transcribe(req.audio_b64, req.mime)
    if not text:
        raise HTTPException(422, "audio could not be transcribed")
    return {"text": text}


@app.post("/v1/describe-image", tags=["input"])
async def describe_image(req: ImageDescriptionRequest) -> dict[str, str]:
    """Read a product label with OpenAI vision before the user starts a dig."""
    if not settings.has_llm:
        raise HTTPException(
            503, "No reasoning provider configured — set OPENAI_API_KEY or PIONEER_API_KEY")
    text = await _orc.llm.read_label(req.image_b64, req.mime)
    if not text:
        raise HTTPException(422, "image could not be read")
    return {"text": text}


@app.get("/v1/packshot", tags=["input"])
async def packshot(name: str) -> dict[str, Any]:
    """A picture of the named product, background removed, with attribution.

    The hero stands the product on the strata it is made of, so it needs the
    thing itself and no box around it. Open Food Facts first — its front image is
    the photograph off the actual packet — then Wikipedia for anything that is a
    brand rather than a barcode.

    `cutout` is null when fal is not configured; the original still renders, just
    with its background.
    """
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    found = await _shots.find(name)
    if not found:
        raise HTTPException(404, f"no picture found for {name!r}")
    found["cutout"] = await _shots.cut_out(found["url"])
    return found


@app.post("/v1/cutout", tags=["input"])
async def cutout(req: ImageDescriptionRequest) -> dict[str, Any]:
    """Remove the background from a photograph the person just took.

    BiRefNet decides which of the photographer's pixels are the subject. It does
    not invent one — a generated product image in a piece about verified facts
    would undo the whole argument.
    """
    if not settings.has_fal:
        raise HTTPException(503, "FAL_KEY is not configured")
    try:
        raw = base64.b64decode(req.image_b64, validate=False)
    except Exception:
        raise HTTPException(400, "image_b64 is not valid base64")
    hosted = await _shots.upload(raw, req.mime or "image/jpeg")
    if not hosted:
        raise HTTPException(502, "could not stage the image")
    cut = await _shots.cut_out(hosted)
    if not cut:
        raise HTTPException(502, "background removal failed")
    return {"url": cut, "original": hosted}


@app.get("/v1/samples/{sample_id}/events", tags=["samples"])
async def stream_sample(sample_id: str) -> StreamingResponse:
    """Server-sent events. Frame shape is `StreamEvent`; `event:` is the type.

    Cold digs take 30-90s and warm ones a couple of seconds, so the UI should
    render every frame as it arrives rather than waiting for `done`.
    """
    req = _pending.pop(sample_id, None)
    if req is None:
        raise HTTPException(404, "unknown or already-streamed sample")

    async def gen():
        try:
            async for ev in _orc.run(req, sample_id=sample_id):
                if ev.type.value == "done":
                    _samples[sample_id] = CoreSample.model_validate(ev.payload)
                yield _sse(ev)
        except Exception as exc:  # noqa: BLE001
            yield ("event: error\n"
                   f"data: {json.dumps({'message': str(exc)[:200]})}\n\n")

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.get("/v1/samples/{sample_id}", response_model=CoreSample, tags=["samples"])
async def get_sample(sample_id: str) -> CoreSample:
    s = _samples.get(sample_id)
    if not s:
        raise HTTPException(404, "not finished, or unknown sample")
    return s


@app.post("/v1/samples:sync", response_model=CoreSample, tags=["samples"])
async def sync_sample(req: SampleRequest) -> CoreSample:
    """Blocking variant. Handy for tests and for warming the cache; do not put a
    demo on it — a cold dig can take a minute and a half."""
    final: CoreSample | None = None
    async for ev in _orc.run(req):
        if ev.type.value == "done":
            final = CoreSample.model_validate(ev.payload)
    if final is None:
        raise HTTPException(502, "dig produced no sample")
    _samples[final.meta.sample_id] = final
    return final


# The front end is served from the same origin, so there is one command to run
# and no CORS to think about in development. Mounted last so it never shadows an
# API route. In production the two are deployed separately and the page falls
# back to /api — see the top of frontend/app.js.
_FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")


def _sse(ev: StreamEvent) -> str:
    return (f"event: {ev.type.value}\n"
            f"id: {ev.seq}\n"
            f"data: {ev.model_dump_json()}\n\n")
