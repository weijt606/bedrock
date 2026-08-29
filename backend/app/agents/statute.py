"""The law layer.

Measured constraint: Cala's Law entities have no incoming relationships, so you
cannot traverse product -> statute. You have to *ask*, and you have to ask
narrowly — a conceptual question like "nutrition and health claims" returns a
list of companies with those words in their name. Questions here are therefore
phrased as single, concrete lookups.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..clients.cala import CalaClient
from ..schemas import Gap, Statute
from .base import source_of

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

DEFAULT_QUESTIONS = [
    "Which EU regulations govern food labelling and allergen declaration?",
]


class StatuteAgent:
    name = "statute"

    def __init__(self, cala: CalaClient) -> None:
        self.cala = cala

    async def run(self, subject: str, emit: Emit,
                  questions: list[str] | None = None) -> tuple[list[Statute], list[Gap]]:
        out: list[Statute] = []
        gaps: list[Gap] = []
        for q in (questions or DEFAULT_QUESTIONS):
            await emit("probe", {"query": q, "agent": self.name})
            res = await self.cala.query(q)
            if res.empty or res.error:
                gaps.append(Gap(query=q, reason="no_rows" if res.empty else "error",
                                note=res.error, latency_s=res.latency_s))
                await emit("gap", {"query": q, "reason": res.error or "no_rows",
                                   "latency_s": res.latency_s})
                continue
            src = source_of(res)
            for row in res.rows[:6]:
                st = Statute(
                    name=row.get("name") or row.get("regulation_number") or "regulation",
                    number=row.get("regulation_number"),
                    title=row.get("title"),
                    summary=row.get("description"),
                    provisions=[row["provision"]] if row.get("provision") else [],
                    source=src,
                )
                out.append(st)
                await emit("statute", st.model_dump(mode="json"))
        return out, gaps
