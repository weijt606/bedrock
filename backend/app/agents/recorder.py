"""Matters of public record.

Bedrock reports what is *filed* — a lawsuit, a sanctions listing, a regulator
action — and never characterises a company. "X is a defendant in Y" is a fact
with a source. "X is unethical" is an opinion, is defamatory if wrong, and is
not something this system will ever emit.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..clients.cala import CalaClient
from ..schemas import Flag, Gap
from .base import source_of

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class RecorderAgent:
    name = "recorder"

    def __init__(self, cala: CalaClient) -> None:
        self.cala = cala

    async def run(self, subject: str, emit: Emit,
                  questions: list[str] | None = None) -> tuple[list[Flag], list[Gap]]:
        qs = questions or [f"What lawsuits has {subject} faced?"]
        flags: list[Flag] = []
        gaps: list[Gap] = []
        for q in qs:
            await emit("probe", {"query": q, "agent": self.name})
            res = await self.cala.query(q)
            if res.empty or res.error:
                gaps.append(Gap(query=q, reason="too_complex" if res.error == "too_complex"
                                else ("no_rows" if res.empty else "error"),
                                note=res.error, latency_s=res.latency_s))
                await emit("gap", {"query": q, "reason": res.error or "no_rows",
                                   "latency_s": res.latency_s})
                continue
            src = source_of(res)
            for row in res.rows[:8]:
                flag = Flag(
                    kind=_kind(row),
                    title=row.get("name") or row.get("title") or "record",
                    parties=row.get("parties"),
                    summary=row.get("description"),
                    source=src,
                )
                flags.append(flag)
                await emit("flag", flag.model_dump(mode="json"))
        return flags, gaps


def _kind(row: dict[str, Any]) -> str:
    blob = " ".join(str(v) for v in row.values() if isinstance(v, str)).lower()
    if "sanction" in blob:
        return "sanctions"
    if "recall" in blob:
        return "recall"
    if "lawsuit" in blob or "court" in blob or "litigation" in blob or "rico" in blob:
        return "litigation"
    return "regulatory"
