"""Everything the crew found, folded into one CoreSample.

The extractor is the only agent the front end has to understand. It computes the
derived numbers the game layer plays with — hops to a human, countries crossed,
whether ownership left the country of origin — and builds the guess prompts.

It adds no facts. Every claim it forwards still carries the Source the agent
that found it attached.
"""
from __future__ import annotations

import time

from ..schemas import (CoreSample, Flag, Gap, GuessPrompt, Layer, Meta, Score,
                       Statute, Subject, SupplyNode)

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
            siblings=siblings,
            gaps=gaps,
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
