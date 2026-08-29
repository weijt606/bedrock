"""The orchestrator.

Speed is the whole design problem. Cala costs 16-75s cold and ~0.5s warm, so:

  * the ownership chain is the only sequential path — hop N+1 is a question
    about hop N's answer — and it starts immediately;
  * supply, statute and public-record probes have no such dependency, so they
    are fanned out with asyncio.gather and race the chain;
  * every result is streamed the instant it lands, so the UI can animate the
    dig instead of showing a spinner;
  * a probe that exceeds its budget degrades into a Gap. A slow lookup never
    blocks the sample, and a Gap is content, not an error;
  * the planner is one small model call with a hard timeout and a static
    fallback ladder, so an LLM hiccup costs nothing.

Ground truth: the planner chooses *questions*. Cala answers them. The assay
model labels the answers. No model anywhere writes a fact into the sample.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncIterator

from .agents import (AuditorAgent, ExtractorAgent, IntakeAgent, ProspectorAgent,
                     ReaderAgent, RecorderAgent, StatuteAgent, SurveyorAgent)
from .clients import CalaClient, FalClient, LLMClient, PioneerClient
from .config import settings
from .schemas import (ConcernReport, CoreSample, EventType, Flag, Gap, Layer,
                      SampleRequest, Statute, StreamEvent, Subject, SupplyNode)


class Orchestrator:
    def __init__(self) -> None:
        self.cala = CalaClient()
        self.llm = LLMClient()
        self.pioneer = PioneerClient()
        self.fal = FalClient()
        self.intake = IntakeAgent(self.cala, self.llm, self.fal)
        self.reader = ReaderAgent(self.cala, self.pioneer)
        self.prospector = ProspectorAgent(self.cala, self.pioneer)
        self.surveyor = SurveyorAgent(self.cala)
        self.statute = StatuteAgent(self.cala)
        self.recorder = RecorderAgent(self.cala)
        self.auditor = AuditorAgent(self.cala)
        self.extractor = ExtractorAgent()

    async def aclose(self) -> None:
        for c in (self.cala, self.llm, self.pioneer, self.fal):
            await c.aclose()

    async def run(self, req: SampleRequest,
                  sample_id: str | None = None) -> AsyncIterator[StreamEvent]:
        sid = sample_id or uuid.uuid4().hex[:12]
        started = time.time()
        seq = 0
        queue: asyncio.Queue[tuple[str, dict[str, Any], str | None]] = asyncio.Queue()

        def frame(kind: str, payload: dict[str, Any], agent: str | None = None) -> StreamEvent:
            nonlocal seq
            seq += 1
            return StreamEvent(type=EventType(kind), sample_id=sid, seq=seq,
                               at=round(time.time() - started, 2), agent=agent,
                               payload=payload)

        yield frame("accepted", {"depth": req.depth, "include": req.include})

        # ---- 1. resolve the input -------------------------------------- #
        subject = await self.intake.run(req)
        yield frame("subject", subject.model_dump(mode="json"), self.intake.name)
        if not subject.resolved_name:
            yield frame("error", {"message": "Could not read a product name from that input."})
            return

        name = subject.resolved_name

        # ---- 2. plan (bounded; falls back to the static ladder) --------- #
        plan = None
        if settings.has_openai:
            try:
                plan = await asyncio.wait_for(
                    self.llm.plan(name, req.depth, req.include), settings.planner_timeout_s)
            except asyncio.TimeoutError:
                plan = None
        plan = plan or {}
        yield frame("plan", {"source": "planner" if plan else "static-ladder",
                             "probes": plan}, "orchestrator")

        # ---- 3. fan out -------------------------------------------------- #
        async def emit(kind: str, payload: dict[str, Any], agent: str | None = None) -> None:
            await queue.put((kind, payload, agent))

        layers: list[Layer] = []
        supply: list[SupplyNode] = []
        statutes: list[Statute] = []
        flags: list[Flag] = []
        gaps: list[Gap] = []
        siblings: list[str] = []
        prose_layers: list[Layer] = []
        concerns: list[ConcernReport] = []

        async def read_prose() -> None:
            """The fast path. Cala answers `knowledge/search` in about a second
            where the typed ladder takes a minute, and the extractor turns that
            paragraph into layers. Whatever it finds is on screen long before the
            first ladder hop lands; the ladder then supersedes it with rows that
            carry stakes and addresses."""
            if "ownership" not in req.include:
                return
            ls, gs = await self.reader.run(name, lambda k, p: emit(k, p, self.reader.name))
            prose_layers.extend(ls)
            gaps.extend(gs)

        async def dig_chain() -> None:
            ls, gs = await self.prospector.run(
                name, req.depth, lambda k, p: emit(k, p, self.prospector.name))
            layers.extend(ls)
            gaps.extend(gs)
            # siblings depend on the terminal owner, so this is chained, not parallel
            # Now that we know who is above the brand, ask the questions the
            # person actually came for — against every one of them, not just the
            # name on the packet.
            if req.concerns:
                names = [l.name for l in ls] + [n.name for n in supply]
                concerns.extend(await self.auditor.run(
                    name, names, req.concerns,
                    lambda k, p: emit(k, p, self.auditor.name)))

            if "siblings" in req.include and ls:
                owner = next((l.name for l in reversed(ls) if l.kind.value == "company"), ls[-1].name)
                q = f"List every brand owned by {owner}"
                await emit("probe", {"query": q, "agent": "prospector"})
                res = await self.cala.query(q)
                if res.rows:
                    siblings.extend(
                        [r.get("brand") or r.get("name") for r in res.rows
                         if isinstance(r.get("brand") or r.get("name"), str)])
                    await emit("siblings", {"items": siblings, "owner": owner,
                                            "latency_s": res.latency_s})
                else:
                    gaps.append(Gap(query=q, reason="no_rows", latency_s=res.latency_s))

        async def dig_supply() -> None:
            if "supply" not in req.include:
                return
            ns, gs = await self.surveyor.run(
                name, lambda k, p: emit(k, p, self.surveyor.name), plan.get("supply"))
            supply.extend(ns)
            gaps.extend(gs)

        async def dig_statute() -> None:
            if "statute" not in req.include:
                return
            ss, gs = await self.statute.run(
                name, lambda k, p: emit(k, p, self.statute.name), plan.get("statute"))
            statutes.extend(ss)
            gaps.extend(gs)

        async def dig_flags() -> None:
            if "flags" not in req.include:
                return
            fs, gs = await self.recorder.run(
                name, lambda k, p: emit(k, p, self.recorder.name), plan.get("flags"))
            flags.extend(fs)
            gaps.extend(gs)

        work = asyncio.gather(read_prose(), dig_chain(), dig_supply(),
                              dig_statute(), dig_flags())
        budget = asyncio.ensure_future(asyncio.wait_for(work, settings.total_budget_s))

        # drain the queue while the crew works
        while True:
            drain = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({drain, budget},
                                         return_when=asyncio.FIRST_COMPLETED)
            if drain in done:
                kind, payload, agent = drain.result()
                yield frame(kind, payload, agent)
                continue
            drain.cancel()
            break

        try:
            await budget
        except asyncio.TimeoutError:
            yield frame("gap", {"query": "*", "reason": "budget_exceeded",
                                "note": f"stopped after {settings.total_budget_s}s"})
        except Exception as exc:  # noqa: BLE001
            yield frame("error", {"message": str(exc)[:200]})

        while not queue.empty():
            kind, payload, agent = queue.get_nowait()
            yield frame(kind, payload, agent)

        # ---- 4. extract --------------------------------------------------- #
        if not layers and prose_layers:
            layers = prose_layers
        sources = [l.source for l in layers] + [s.source for s in supply] \
            + [s.source for s in statutes] + [f.source for f in flags]
        sample = self.extractor.build(
            sample_id=sid, started_at=started, subject=subject, layers=layers,
            supply=supply, statutes=statutes, flags=flags, concerns=concerns,
            siblings=siblings, gaps=gaps,
            queries_run=len(sources) + len(gaps),
            cache_hits=sum(1 for s in sources if s.cached),
            agents=["intake", "reader", "prospector", "surveyor", "statute",
                    "recorder", "auditor", "extractor"],
            models={
                "planner": settings.planner_model if settings.has_llm else "static-ladder",
                "vision": settings.vision_model if settings.has_llm else "unavailable",
                "reasoning_provider": settings.llm_provider,
                "assay": self.pioneer.backend,
                "reader": (settings.model_reader if settings.has_pioneer
                           else "unavailable"),
                "stt": settings.fal_stt_model if settings.has_fal else "unavailable",
                "facts": "cala/knowledge",
            },
        )
        yield frame("score", sample.score.model_dump(mode="json"), "extractor")
        yield frame("done", sample.model_dump(mode="json"), "extractor")
