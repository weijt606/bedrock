"""Who physically makes the thing, and who else uses the same floor.

Runs concurrently with the prospector: supply questions do not depend on the
ownership chain, so there is no reason to wait for it.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from ..clients.cala import CalaClient
from ..schemas import Gap, SupplyNode
from .ladder import questions_to_ladders
from .base import ask_variants, first_name, gap_from, source_of

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class SurveyorAgent:
    name = "surveyor"

    def __init__(self, cala: CalaClient) -> None:
        self.cala = cala

    async def run(self, subject: str, emit: Emit,
                  questions: list[str] | None = None) -> tuple[list[SupplyNode], list[Gap]]:
        # Each entry is one *question*, expressed as several phrasings. Cala
        # answers whichever wording it recognises; only a question that stays
        # empty across all of them is a real gap. See base.ask_variants.
        ladders: list[list[str]] = questions_to_ladders(questions) or [
            [f"{subject}.manufactured_by",
             f"Who manufactures {subject}?",
             f"Which company physically makes {subject}?"],
            [f"{subject}.ingredients",
             f"{subject}.raw_material_origin",
             f"What are {subject} made of and where do the ingredients come from?"],
        ]
        nodes: list[SupplyNode] = []
        gaps: list[Gap] = []

        for ladder in ladders:
            res, attempts = await ask_variants(self.cala, ladder, emit, self.name)
            if res.empty or res.error:
                gap = gap_from(res, attempts)
                gaps.append(gap)
                await emit("gap", gap.model_dump(mode="json"))
                continue
            src = source_of(res)
            for row in res.rows[:12]:
                node = SupplyNode(
                    name=first_name(row),
                    role=row.get("category") or row.get("role") or row.get("producto_categoria"),
                    country=row.get("country") or row.get("location"),
                    detail=row.get("description") or row.get("details")
                    or row.get("datos_relevantes") or row.get("products"),
                    source=src,
                )
                nodes.append(node)
                await emit("supply", node.model_dump(mode="json"))
        return nodes, gaps

    async def shared_factories(self, region: str = "Bangladesh") -> dict[str, list[str]]:
        """Which brands sit in the same factory group. Powers the 'same floor,
        different price tag' reveal in the game layer."""
        res = await self.cala.query(
            f"Which brands share the same manufacturing factories in {region}?")
        groups: dict[str, list[str]] = {}
        for row in res.rows:
            g, b = row.get("factory_group"), row.get("brand")
            if g and b:
                groups.setdefault(g, []).append(b)
        return groups
