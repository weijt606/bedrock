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
from .base import ask_variants, gap_from, source_of
from .ladder import questions_to_ladders

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class RecorderAgent:
    name = "recorder"

    def __init__(self, cala: CalaClient) -> None:
        self.cala = cala

    async def run(self, subject: str, emit: Emit,
                  questions: list[str] | None = None) -> tuple[list[Flag], list[Gap]]:
        ladders: list[list[str]] = questions_to_ladders(questions) or [
            [f"What lawsuits has {subject} faced?",
             f"{subject}.lawsuits",
             f"{subject}.litigation"],
            [f"{subject}.regulatory_actions",
             f"What regulatory actions or fines has {subject} received?"],
        ]
        flags: list[Flag] = []
        gaps: list[Gap] = []
        for ladder in ladders:
            res, attempts = await ask_variants(self.cala, ladder, emit, self.name)
            if res.empty or res.error:
                gap = gap_from(res, attempts)
                gaps.append(gap)
                await emit("gap", gap.model_dump(mode="json"))
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
