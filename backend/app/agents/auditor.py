"""What the person actually wanted to know.

Somebody picking up a packet does not care about corporate structure for its own
sake. They care whether the thing in their hand implicates them in something.
Child labour. Forced labour. Deforestation. A tax structure. Bedrock's answer to
that has to be usable *and* has to stay on the right side of the one rule, so:

    the person declares the concern
    Bedrock reports what is on the public record
    the person judges

Bedrock never scores a company, never grades it, never calls it good or bad.
"X appears on the UFLPA Entity List" is a sourced fact. "X is unethical" is an
opinion, is defamatory if wrong, and is not something this system will emit.

## Why this checks the whole chain

This is the part a shopper cannot do alone, and the reason the ownership dig
exists at all. A brand can be spotless while its parent's factory group is on a
forced-labour list. So every concern is checked against **every entity the dig
found** — the brand, each company up the ownership chain, and each supplier —
not just the name on the front of the packet.

## Why it is one query per concern, not one per entity

Cala answers "which companies have been accused of child labour in their supply
chains?" with a list — 30 rows on the run that motivated this agent. So rather
than asking N entity-specific questions, the auditor asks the *list* question
once and intersects the answer with the chain it already has.

That is one Cala call instead of N, and because these list queries are identical
for every player, the first person to care about child labour warms that answer
for everybody who comes after — 16-75s once, then ~0.5s forever.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

from ..clients.cala import CalaClient
from ..schemas import Concern, ConcernReport, Flag
from .base import source_of
from .depuration import normalise_name as _key

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

# One shared list question per concern, plus a targeted one for the brand itself.
# Phrased narrowly: Cala rejects broad questions with `too_complex`.
LIST_QUERY: dict[Concern, str] = {
    Concern.child_labour:
        "Which companies have been accused of using child labour in their supply chains?",
    Concern.forced_labour:
        "Which companies are on the UFLPA Entity List for forced labour?",
    Concern.environment:
        "Which companies have received the largest environmental fines?",
    Concern.deforestation:
        "Which companies are linked to deforestation in palm oil supply chains?",
    Concern.labour_rights:
        "Which companies have faced lawsuits over labour rights violations?",
    Concern.tax:
        "Which multinational companies have been investigated for tax avoidance in Luxembourg?",
    Concern.governance:
        "Which companies have been sanctioned by financial regulators for governance failures?",
    Concern.animal_welfare:
        "Which companies have faced legal action over animal welfare?",
}

# Phrasing matters more than it should. Measured against the live API:
#
#   "What labour rights violations has Inditex been accused of?"  -> too_complex
#   "{e}.environmental_violations"                                -> 6 rows with
#       incident, location, year, fine_amount, description
#   "What environmental fines has Nestle received?"               -> 2 rows
#
# Cala rejects a question that asks it to characterise, and answers a dotted path
# that asks it to enumerate. So the direct probes are dotted paths wherever a
# dotted path exists, and narrow yes/no questions where one does not.
DIRECT_QUERY: dict[Concern, str] = {
    Concern.child_labour: "Has {e} been accused of child labour in its supply chain?",
    Concern.forced_labour: "Has {e} been linked to forced labour?",
    Concern.environment: "{e}.environmental_violations",
    Concern.deforestation: "Has {e} been linked to deforestation?",
    Concern.labour_rights: "{e}.labour_disputes",
    Concern.tax: "Has {e} been investigated for tax avoidance?",
    Concern.governance: "{e}.regulatory_actions",
    Concern.animal_welfare: "Has {e} faced legal action over animal welfare?",
}

_KIND: dict[Concern, str] = {
    Concern.forced_labour: "sanctions",
    Concern.governance: "regulatory",
    Concern.tax: "regulatory",
}



def _matches(a: str, b: str) -> bool:
    ka, kb = _key(a), _key(b)
    if not ka or not kb or min(len(ka), len(kb)) < 4:
        return False
    return ka == kb or ka in kb or kb in ka


class AuditorAgent:
    name = "auditor"

    def __init__(self, cala: CalaClient) -> None:
        self.cala = cala

    async def run(self, brand: str, entities: list[str], concerns: list[Concern],
                  emit: Emit) -> list[ConcernReport]:
        if not concerns:
            return []
        # brand first — it is the name the person actually typed
        checked = list(dict.fromkeys([brand] + [e for e in entities if e]))
        reports = await asyncio.gather(
            *(self._one(brand, checked, c, emit) for c in concerns))
        return list(reports)

    async def _one(self, brand: str, checked: list[str], concern: Concern,
                   emit: Emit) -> ConcernReport:
        report = ConcernReport(concern=concern, entities_checked=checked)

        # 1. the shared list question — warm for everyone after the first person asks
        lq = LIST_QUERY[concern]
        report.queries.append(lq)
        await emit("probe", {"query": lq, "agent": self.name, "concern": concern.value})
        listed = await self.cala.query(lq)

        if listed.rows:
            src = source_of(listed)
            for row in listed.rows:
                named = (row.get("company") or row.get("name") or "").strip()
                if not named:
                    continue
                hit = next((e for e in checked if _matches(named, e)), None)
                if not hit:
                    continue
                report.flags.append(Flag(
                    kind=_KIND.get(concern, "report"),  # type: ignore[arg-type]
                    title=f"{named} appears on: {lq.rstrip('?')}",
                    summary=row.get("sector") or row.get("description")
                    or row.get("details"),
                    concern=concern,
                    about=hit,
                    source=src,
                ))

        # 2. a targeted question about the brand, which catches what a list misses
        dq = DIRECT_QUERY[concern].format(e=brand)
        report.queries.append(dq)
        await emit("probe", {"query": dq, "agent": self.name, "concern": concern.value})
        direct = await self.cala.query(dq)
        if direct.rows and direct.error != "too_complex":
            src = source_of(direct)
            for row in direct.rows[:5]:
                answered, positive, label = _verdict(row)
                if answered and not positive:
                    # An explicit "no" is an answer, not a finding. Recording it as a
                    # flag would turn "we asked and the record says no" into an
                    # accusation, which is the exact failure mode this agent exists
                    # to avoid.
                    continue
                title = label or _title(row)
                if not title:
                    continue
                report.flags.append(Flag(
                    kind=_KIND.get(concern, "report"),  # type: ignore[arg-type]
                    title=title[:200],
                    parties=row.get("parties"),
                    summary=_context(row),
                    concern=concern,
                    about=row.get("name") if isinstance(row.get("name"), str) else brand,
                    source=src,
                ))

        report.status = "found" if report.flags else "clear"
        await emit("concern", report.model_dump(mode="json"))
        return report


# --------------------------------------------------------------------------- #
#  reading a targeted answer
# --------------------------------------------------------------------------- #

_YES = {"yes", "true", "confirmed", "y"}
_NO = {"no", "false", "none", "n", "not found", "no records", "no known"}


def _verdict(row: dict[str, Any]) -> tuple[bool, bool, str | None]:
    """Cala often answers a direct question with a boolean column.

        {"name": "Nestlé", "accused_of_child_labour": "yes"}

    Returns (answered, positive, human label). A "no" must never become a flag.
    """
    for k, v in row.items():
        if not isinstance(v, str):
            continue
        low = v.strip().lower()
        if low in _YES:
            return True, True, k.replace("_", " ").capitalize() + ": yes"
        if low in _NO:
            return True, False, None
    return False, False, None


_TITLE_KEYS = ("incident", "title", "case", "violation", "violation_type",
               "investigation_type", "action", "policy", "policy_name",
               "description", "summary")


def _title(row: dict[str, Any]) -> str | None:
    """A row is only worth surfacing if it says something beyond the entity name."""
    for k in _TITLE_KEYS:
        v = row.get(k)
        if isinstance(v, str) and len(v.strip()) > 8:
            return v.strip()
    name, desc = row.get("name"), row.get("details")
    if isinstance(name, str) and isinstance(desc, str) and len(desc) > 8:
        return f"{name} — {desc}"
    return None


def _context(row: dict[str, Any]) -> str | None:
    """Fines, dates and places, when Cala returned them as their own columns.

        {"incident": "Nestlé Waters — Illegal Water Drilling", "location": "France",
         "year": 2024, "fine_amount": "2 million", "fine_currency": "EUR"}

    becomes "France · 2024 · 2 million EUR". Values are copied, never computed.
    """
    bits: list[str] = []
    for k in ("location", "country", "year", "date", "investigation_opened"):
        v = row.get(k)
        if v not in (None, ""):
            bits.append(str(v))
    amount = row.get("fine_amount") or row.get("amount") or row.get("fine")
    if amount not in (None, ""):
        cur = row.get("fine_currency") or row.get("currency") or ""
        bits.append(f"{amount} {cur}".strip())
    for k in ("outcome", "reason", "details", "description"):
        v = row.get(k)
        if isinstance(v, str) and len(v) > 8 and v != _title(row):
            bits.append(v)
            break
    return " · ".join(bits) if bits else None
