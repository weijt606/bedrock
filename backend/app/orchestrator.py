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

from .agents.depuration import resolve_row_type
from .clients.falvideo import build_prompt
from .agents import (AuditorAgent, EnricherAgent, ExtractorAgent, IntakeAgent,
                     ProspectorAgent, ReaderAgent, RecorderAgent, StatuteAgent,
                     SurveyorAgent)
from .agents.editorial import build_conduct, build_structure
from .clients import (CalaClient, FalClient, FalVideoClient, LLMClient,
                      PioneerClient)
from . import media
from .config import settings
from .schemas import (ConcernReport, CoreSample, EditorialRoutes, EventType,
                      Flag, Gap, Layer, SampleRequest, Statute, StreamEvent,
                      Subject, SupplyNode)


# request ids by sample, so /media can be polled after the stream closes.
VIDEO_JOBS: dict[str, tuple[str, str]] = {}

# Only a shape hint for the camera. Not a claim about the product.
_FORM = {"product": "product", "company": "package", "organization": "package"}


class Orchestrator:
    def __init__(self) -> None:
        self.cala = CalaClient()
        self.llm = LLMClient()
        self.pioneer = PioneerClient()
        self.fal = FalClient()
        self.video = FalVideoClient()
        self.intake = IntakeAgent(self.cala, self.llm, self.fal)
        self.reader = ReaderAgent(self.cala, self.pioneer)
        self.prospector = ProspectorAgent(self.cala, self.pioneer)
        self.surveyor = SurveyorAgent(self.cala)
        self.statute = StatuteAgent(self.cala)
        self.recorder = RecorderAgent(self.cala)
        self.auditor = AuditorAgent(self.cala)
        self.enricher = EnricherAgent(self.cala)
        self.extractor = ExtractorAgent()

    async def aclose(self) -> None:
        for c in (self.cala, self.llm, self.pioneer, self.fal, self.video):
            await c.aclose()


    async def _submit_video(self, req: SampleRequest, subject: Subject,
                            supply: list[SupplyNode], emit) -> None:
        """Queue the illustrative loop. Never awaited by the dig.

        The prompt is one fixed template; only the *materials* come from data,
        and only from supply rows the depuration step typed as an ingredient —
        so the loop is filled with things Cala actually returned rather than
        anything a model imagined. No claim, number or location goes near it.

        A photograph takes the image-to-video route and keeps the reader's own
        packaging. Without one we go text-to-video and describe material and
        light only: inventing a branded packshot is the visual equivalent of
        inventing a fact.
        """
        if not self.video.ready:
            return
        motifs = [n.name for n in supply
                  if resolve_row_type({"ingredient": n.name} if n.role == "ingredient"
                                      else {"supplier": n.name}) == "ingredient"]
        if not motifs:
            motifs = [n.name for n in supply if (n.role or "").lower() == "ingredient"]
        form = _FORM.get((subject.entity_type or "").lower(), None)

        photo = req.image_b64 if req.kind.value == "image" else None
        k = media.key(subject.resolved_name, photo)
        media.bind(self._sid, k)

        # Generated once per product and style, then served from disk forever.
        # A second search costs nothing and returns the same loop.
        seen = media.recall(k)
        if seen and seen.get("url"):
            VIDEO_JOBS[self._sid] = ("", "")
            await emit("media", {"status": "ready", "url": seen["url"], "cached": True})
            return
        if seen and seen.get("request_id"):
            VIDEO_JOBS[self._sid] = (seen["model"], seen["request_id"])
            await emit("media", {"status": "pending", "resumed": True})
            return

        image_url = None
        if photo:
            image_url = await self.video.upload(photo, req.mime or "image/jpeg")

        prompt = build_prompt(motifs, form, bool(image_url))
        job = await self.video.submit(prompt, image_url)
        if job:
            VIDEO_JOBS[self._sid] = job
            media.remember_job(k, *job)
            await emit("media", {"status": "pending",
                                 "route": "image-to-video" if image_url else "text-to-video"})

    async def _editorial(self, subject: str, layers: list[Layer],
                         concerns: list[ConcernReport], emit) -> EditorialRoutes | None:
        """Build the two routes, asking knowledge/search for citable evidence.

        One enrichment question per entity in the chain, fired together. Each is a
        cold Cala call the first time anybody asks it and about half a second
        after that, so this costs one round of latency rather than one per hop.
        """
        names = [l.name for l in layers]
        questions = [f"Who owns {n}?" for n in names]
        for q in questions:
            await emit("probe", {"query": q, "agent": self.enricher.name})
        got = await asyncio.gather(
            *(self.enricher.evidence_for(q, "parent") for q in questions),
            return_exceptions=True)
        by_entity = {n: (e if isinstance(e, list) else []) for n, e in zip(names, got)}

        # A conduct candidate needs a documented bridge between the product and
        # whatever is on the record - that is `commercial_link`, and without it a
        # parent's lawsuit would be attributed to a product it may have nothing to
        # do with. The ownership chain is that bridge, so it is only offered where
        # the enricher actually found a citation for it.
        candidates = []
        for report in concerns:
            for i, flag in enumerate(report.flags):
                about = flag.about or subject
                bridge = by_entity.get(about, [])
                chapters = []
                if bridge:
                    chapters.append({"role": "commercial_link", "evidence": bridge[:1]})
                impact = await self.enricher.evidence_for(
                    f"{flag.title}", "supply_chain")
                if impact:
                    chapters.append({"role": "documented_impact", "evidence": impact[:2]})
                if not chapters:
                    continue
                candidates.append({
                    "id": f"{report.concern.value}-{i}",
                    "topic": _TOPIC.get(report.concern.value, "legal"),
                    "scope": "supply_chain" if about != subject else "brand",
                    "chapters": chapters,
                })

        return EditorialRoutes(structure=build_structure(layers, by_entity),
                               conduct=build_conduct(candidates))

    async def run(self, req: SampleRequest,
                  sample_id: str | None = None) -> AsyncIterator[StreamEvent]:
        sid = sample_id or uuid.uuid4().hex[:12]
        self._sid = sid
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
        editorial_holder: list[EditorialRoutes] = []

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

            # The editorial routes need the chain and the records, so they run
            # once both are in rather than racing them. The enricher is the only
            # thing that can move a route from `partial` to `evidenced`: it asks
            # knowledge/search, which is the sole endpoint that returns a URL.
            if "editorial" in req.include and ls:
                nonlocal_editorial = await self._editorial(name, ls, concerns, emit)
                if nonlocal_editorial is not None:
                    editorial_holder.append(nonlocal_editorial)

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
            # Queued, never awaited. The loop takes 30-120s and the dig does not
            # wait for it; if it is late the interface simply never shows it.
            asyncio.create_task(self._submit_video(req, subject, list(supply), emit))

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
        editorial = editorial_holder[0] if editorial_holder else None
        sources = [l.source for l in layers] + [s.source for s in supply] \
            + [s.source for s in statutes] + [f.source for f in flags]
        sample = self.extractor.build(
            sample_id=sid, started_at=started, subject=subject, layers=layers,
            supply=supply, statutes=statutes, flags=flags, concerns=concerns,
            editorial=editorial, siblings=siblings, gaps=gaps,
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
        if editorial is not None:
            yield frame("editorial", editorial.model_dump(mode="json"), "enricher")
        yield frame("score", sample.score.model_dump(mode="json"), "extractor")
        yield frame("done", sample.model_dump(mode="json"), "extractor")


# Concern names map to the topics the conduct route understands. Both vocabularies
# are deliberate: `Concern` is what a person says they care about, `topic` is how
# the record is filed.
_TOPIC = {
    "child_labour": "labor", "forced_labour": "labor", "labour_rights": "labor",
    "environment": "environment", "deforestation": "environment",
    "animal_welfare": "health", "tax": "regulatory", "governance": "regulatory",
}
