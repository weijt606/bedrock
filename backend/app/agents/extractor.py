"""Everything the crew found, folded into one CoreSample.

The extractor is the only agent the front end has to understand. It computes the
derived numbers the game layer plays with — hops to a human, countries crossed,
whether ownership left the country of origin — and builds the guess prompts.

It adds no facts. Every claim it forwards still carries the Source the agent
that found it attached.
"""
from __future__ import annotations

import time

from ..schemas import (Beat, BeatKind, ConcernReport, CoreSample, EditorialRoutes,
                       Flag, Gap, GuessPrompt, Layer, Meta, Score, Statute,
                       Subject, SupplyNode)

COUNTRY_NAMES = {
    "ES": "Spain", "NL": "Netherlands", "LU": "Luxembourg", "DE": "Germany",
    "IT": "Italy", "FR": "France", "GB": "United Kingdom", "US": "United States",
    "CH": "Switzerland", "BE": "Belgium", "IE": "Ireland", "PT": "Portugal",
    "SE": "Sweden", "DK": "Denmark", "AT": "Austria",
}
GUESS_COUNTRIES = ["ES", "NL", "LU", "DE", "IT", "US", "GB"]


class ExtractorAgent:
    name = "extractor"

    def build(self, *, sample_id: str, started_at: float, subject: Subject,
              layers: list[Layer], supply: list[SupplyNode], statutes: list[Statute],
              flags: list[Flag], siblings: list[str], gaps: list[Gap],
              concerns: list[ConcernReport] | None = None,
              editorial: EditorialRoutes | None = None,
              queries_run: int, cache_hits: int, agents: list[str],
              models: dict[str, str]) -> CoreSample:

        origin = _origin(subject, layers)
        countries: list[str] = []
        for cc in ([origin] + [l.country for l in layers]):
            if cc and cc not in countries:
                countries.append(cc)

        ends_in = next((l.country for l in reversed(layers) if l.country), None)
        score = Score(
            hops_to_human=len(layers),
            countries=countries,
            ends_in=ends_in,
            origin_country=origin,
            left_home=bool(origin and ends_in and origin != ends_in),
            siblings_count=len(siblings),
            gaps_count=len(gaps),
        )

        band = "1-2" if len(layers) <= 2 else ("3-4" if len(layers) <= 4 else "5+")
        guesses = [
            GuessPrompt(
                id="ends_in_country",
                question="Which country does the ownership end in?",
                options=[COUNTRY_NAMES[c] for c in GUESS_COUNTRIES],
                answer=COUNTRY_NAMES.get(ends_in) if ends_in else None,
            ),
            GuessPrompt(
                id="hops_to_human",
                question="How many steps until you reach a person?",
                options=["1-2", "3-4", "5+"],
                answer=band if layers else None,
            ),
        ]
        if origin:
            guesses.append(GuessPrompt(
                id="still_domestic",
                question=f"Is it still owned in {COUNTRY_NAMES.get(origin, origin)}?",
                options=["Yes", "No"],
                answer=("No" if score.left_home else "Yes") if ends_in else None,
            ))

        now = time.time()
        return CoreSample(
            subject=subject,
            layers=layers,
            supply=supply,
            statutes=statutes,
            flags=flags,
            concerns=concerns or [],
            editorial=editorial,
            siblings=siblings,
            gaps=gaps,
            story=build_story(subject, layers, score, siblings, gaps,
                              concerns or []),
            guesses=guesses,
            score=score,
            meta=Meta(
                sample_id=sample_id,
                started_at=started_at,
                finished_at=now,
                queries_run=queries_run,
                cache_hits=cache_hits,
                total_latency_s=round(now - started_at, 2),
                agents=agents,
                models=models,
            ),
        )


def _origin(subject: Subject, layers: list[Layer]) -> str | None:
    """Country of origin, read out of Cala's own entity description. Never guessed."""
    blob = (subject.description or "").lower()
    for cc, nm in COUNTRY_NAMES.items():
        if nm.lower() in blob:
            return cc
    for city, cc in (("barcelona", "ES"), ("madrid", "ES"), ("valencia", "ES"),
                     ("sant sadurn", "ES"), ("bielefeld", "DE"), ("milan", "IT"),
                     ("amsterdam", "NL"), ("schiphol", "NL"), ("paris", "FR"),
                     ("london", "GB"), ("lisbon", "PT"), ("zurich", "CH")):
        if city in blob:
            return cc
    for adj, cc in (("spanish", "ES"), ("catalan", "ES"), ("dutch", "NL"),
                    ("german", "DE"), ("italian", "IT"), ("french", "FR"),
                    ("british", "GB"), ("american", "US"), ("swiss", "CH"),
                    ("belgian", "BE"), ("irish", "IE")):
        if adj in blob:
            return cc
    return layers[0].country if layers else None


# --------------------------------------------------------------------------- #
#  the story
# --------------------------------------------------------------------------- #
#
# The game layer needs a shape to tell, not a pile of rows. It must not need a
# language model to write prose about a real company either, so every beat below
# is a sentence with values dropped into it, carrying the source behind it.
#
# `weight` decides what gets the screen, and it comes out of the facts: a record
# filed against a company four steps above the label beats the year the brand was
# founded. Sort by weight, take three, and you have the story.

def build_story(subject: Subject, layers: list[Layer], score: Score,
                siblings: list[str], gaps: list[Gap],
                concerns: list[ConcernReport]) -> list[Beat]:
    beats: list[Beat] = []
    name = subject.resolved_name
    origin = score.origin_country
    origin_name = COUNTRY_NAMES.get(origin or "", origin or "")

    # --- where it started ------------------------------------------------- #
    if subject.description:
        beats.append(Beat(
            kind=BeatKind.origin,
            headline=f"{name}",
            detail=subject.description,
            weight=0.30,
            entities=[name],
            at_step=0,
        ))

    # --- each time it changed hands ---------------------------------------- #
    #
    # Only from layers the ladder confirmed. A provisional layer is a name the
    # extractor lifted out of a paragraph, and the order names appear in is not
    # an order of ownership - "Nestlé S.A. answers to SIX Swiss Exchange" is a
    # sentence this template will happily build out of a listing venue. A beat
    # asserts a relationship, so it may only be built from a confirmed one.
    prev = name
    for layer in [l for l in layers if not l.provisional]:
        crossed = bool(origin and layer.country and layer.country != origin)
        beats.append(Beat(
            kind=BeatKind.border if crossed else BeatKind.handover,
            headline=(_handover(prev, layer)
                      if not crossed else
                      f"At step {layer.index + 1} the trail leaves "
                      f"{origin_name} for {COUNTRY_NAMES.get(layer.country or '', layer.country)}."),
            detail=(layer.relationship or (layer.detail[0] if layer.detail else None)),
            weight=0.45 + (0.15 if crossed else 0.0)
                   + (0.05 if layer.stake_percent else 0.0),
            entities=[prev, layer.name],
            at_step=layer.index,
            source=layer.source,
        ))
        prev = layer.name

    # --- where it stopped --------------------------------------------------- #
    confirmed = [l for l in layers if not l.provisional]
    if confirmed:
        last = confirmed[-1]
        if last.address:
            head = f"It ends at an address: {last.address}."
        elif last.kind.value in ("person", "family"):
            head = f"It ends with {last.name}."
        else:
            head = f"As far as the record goes, it ends at {last.name}."
        beats.append(Beat(
            kind=BeatKind.terminus,
            headline=head,
            detail=(f"{score.hops_to_human} steps from the thing in your hand."
                    if score.hops_to_human else None),
            weight=0.75 + (0.15 if score.left_home else 0.0),
            entities=[last.name],
            at_step=last.index,
            source=last.source,
        ))

    # --- how far it went ---------------------------------------------------- #
    if len(score.countries) > 1:
        beats.append(Beat(
            kind=BeatKind.scale,
            headline=f"This object has been to {len(score.countries)} countries.",
            detail=" → ".join(score.countries),
            weight=0.40 + 0.08 * len(score.countries),
            entities=[name],
        ))

    # --- what else lands in the same place ---------------------------------- #
    if len(siblings) > 1:
        others = [b for b in siblings if b.lower() != name.lower()][:6]
        beats.append(Beat(
            kind=BeatKind.convergence,
            headline=f"{len(siblings)} brands end in the same place.",
            detail=("You have been choosing between " + ", ".join(others) + "…"
                    if others else None),
            weight=min(0.9, 0.45 + 0.015 * len(siblings)),
            entities=siblings[:8],
        ))

    # --- what the person actually asked about -------------------------------- #
    for report in concerns:
        label = report.concern.value.replace("_", " ")
        if report.status == "found":
            for flag in report.flags[:2]:
                about = flag.about or name
                step = next((l.index + 1 for l in layers if l.name == about), None)
                # a record against something *above* the brand is the finding a
                # shopper cannot reach on their own — weight it highest
                indirect = about.lower() != name.lower()
                beats.append(Beat(
                    kind=BeatKind.concern,
                    headline=(f"{about} — {step} step{'' if step == 1 else 's'} above "
                              f"the label — has a {label} record."
                              if indirect and step else
                              f"{about} has a {label} record."),
                    detail=flag.title,
                    weight=1.0 if indirect else 0.9,
                    entities=[about],
                    at_step=step,
                    source=flag.source,
                ))
        elif report.status == "clear":
            beats.append(Beat(
                kind=BeatKind.concern,
                headline=f"Nothing on the public record about {label}.",
                detail=(f"We asked about {len(report.entities_checked)} companies in "
                        f"this chain. An empty record is not a clean record."),
                weight=0.35,
                entities=report.entities_checked[:6],
            ))

    # --- what nobody wrote down ---------------------------------------------- #
    empty = [g for g in gaps if g.reason == "no_rows"]
    if empty:
        beats.append(Beat(
            kind=BeatKind.silence,
            headline="And then it goes quiet.",
            detail=" · ".join(f"{g.query} → rows = 0" for g in empty[:3]),
            weight=0.70,
            entities=[name],
        ))

    return sorted(beats, key=lambda b: (_ORDER[b.kind], -b.weight))


def _handover(prev: str, layer: Layer) -> str:
    """Say exactly what the row said.

    "answers to" is right for a parent and wrong for a passive index fund holding
    two per cent, and a beat that overstates a relationship is as damaging as one
    that invents it. So the verb comes from the data: a stated relationship, then
    a stated stake, then the neutral fact that a name is on the register.
    """
    rel = (layer.relationship or "").strip().lower()
    if any(w in rel for w in ("parent", "owner", "controll", "majority")):
        return f"{prev} answers to {layer.name}."
    if layer.stake_percent is not None:
        return f"{layer.name} holds {layer.stake_percent:g}% of {prev}."
    return f"{layer.name} appears on the share register of {prev}."


# Telling order. Weight decides emphasis; this decides sequence.
_ORDER = {
    BeatKind.origin: 0,
    BeatKind.handover: 1,
    BeatKind.border: 1,
    BeatKind.terminus: 2,
    BeatKind.scale: 3,
    BeatKind.convergence: 4,
    BeatKind.concern: 5,
    BeatKind.silence: 6,
}
