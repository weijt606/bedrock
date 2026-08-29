"""Bedrock API.

    POST /v1/samples              -> {sample_id}, then stream it
    GET  /v1/samples/{id}/events  -> SSE, one frame per finding
    GET  /v1/samples/{id}         -> the finished CoreSample
    POST /v1/samples:sync         -> blocking, returns a CoreSample (demo/tests only)
    GET  /v1/health               -> which providers are wired up

Interactive schema at /docs. That page is the contract with the front end.
"""
from __future__ import annotations

import asyncio
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
from .config import settings
from .orchestrator import Orchestrator
from .schemas import CoreSample, SampleRequest, StreamEvent

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
_samples: dict[str, CoreSample] = {}
_streams: dict[str, asyncio.Queue] = {}
_pending: dict[str, SampleRequest] = {}


@app.on_event("shutdown")
async def _shutdown() -> None:
    await _orc.aclose()


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


# The prototype front end is served from the same origin, so there is one
# command to run and no CORS to think about. Mounted last so it never shadows
# an API route.
_DEMO = pathlib.Path(__file__).resolve().parents[2] / "demo"
if _DEMO.is_dir():
    app.mount("/", StaticFiles(directory=str(_DEMO), html=True), name="demo")


def _sse(ev: StreamEvent) -> str:
    return (f"event: {ev.type.value}\n"
            f"id: {ev.seq}\n"
            f"data: {ev.model_dump_json()}\n\n")
