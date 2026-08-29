from __future__ import annotations

from typing import Any

from typing import Awaitable, Callable

from ..clients.cala import CalaResult
from ..schemas import Gap, Source

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


def source_of(res: CalaResult) -> Source:
    return Source(
        query=res.query,
        endpoint=res.endpoint,  # type: ignore[arg-type]
        latency_s=res.latency_s,
        cached=res.cached,
        documents=res.documents,
        fact_ids=res.fact_ids,
    )


def first_name(row: dict[str, Any]) -> str:
    for k in ("owner", "ultimate_owner", "shareholder", "name", "brand", "manufacturer",
              "empresa", "factory_group"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return next((str(v) for v in row.values() if isinstance(v, str) and v.strip()), "unknown")


def detail_lines(rows: list[dict[str, Any]], limit: int = 8) -> list[str]:
    """Flatten Cala rows into readable lines without inventing anything."""
    out: list[str] = []
    for row in rows[:limit]:
        name = first_name(row)
        extras = []
        for k in ("role", "type", "relationship", "products", "producto_categoria",
                  "datos_relevantes", "description", "detail", "category"):
            v = row.get(k)
            if isinstance(v, str) and v.strip() and v.strip() != name:
                extras.append(v.strip())
        for k in ("ownership_percent", "stake_percent"):
            v = row.get(k)
            if v not in (None, ""):
                extras.insert(0, f"{v}%" if not str(v).endswith("%") else str(v))
        out.append(f"{name} — {' · '.join(extras)}" if extras else name)
    return out


# --------------------------------------------------------------------------- #
#  asking the same question several ways
# --------------------------------------------------------------------------- #

# Cala answers a *phrasing*, not an intent. Measured on the live API:
#
#   Chupa Chups.raw_material_origin                              ->  0 rows
#   Chupa Chups.ingredients                                      ->  5 rows
#   "What are Chupa Chups made of and where do the ..."          -> 23 rows
#
#   Estrella Damm.barley_supplier                                ->  0 rows
#   Estrella Damm.raw_material_origin                            ->  4 rows
#
# A single empty answer therefore says nothing about the world; it says we
# guessed the wrong key. Only a question that stays empty across a dotted probe,
# a differently-named dotted probe and a natural-language sentence is evidence
# that the record is actually silent.


async def ask_variants(cala: Any, variants: list[str], emit: Emit | None = None,
                       agent: str | None = None) -> tuple[CalaResult, list[str]]:
    """Ask the same question several ways; stop at the first phrasing that answers.

    Returns the winning `CalaResult` and the list of phrasings that came back
    empty before it. When every variant fails, the last result is returned with
    every attempt recorded, and the caller may honestly call it a gap.
    """
    attempts: list[str] = []
    res: CalaResult | None = None
    for q in variants:
        if emit is not None:
            await emit("probe", {"query": q, "agent": agent, "attempt": len(attempts) + 1})
        res = await cala.query(q)
        # A hard failure is about us, not about the record: stop and report it as
        # itself rather than burning the remaining phrasings.
        if res.error in {"rate_limited", "timeout"}:
            return res, attempts
        if not res.empty:
            return res, attempts
        attempts.append(q)
    return res, attempts  # type: ignore[return-value]


def gap_from(res: CalaResult, attempts: list[str]) -> Gap:
    """Build a Gap that can prove its own silence.

    `reason` distinguishes what happened to us (`rate_limited`, `error`,
    `too_complex`) from what is true of the public record (`no_rows`). Only the
    last one is content the UI may present as a finding.
    """
    if res.error in {"rate_limited", "timeout"}:
        reason = "rate_limited"
    elif res.error == "too_complex":
        reason = "too_complex"
    elif res.error:
        reason = "error"
    else:
        reason = "no_rows"
    return Gap(query=res.query, reason=reason, note=res.error,
               latency_s=res.latency_s, attempts=attempts or [res.query])
