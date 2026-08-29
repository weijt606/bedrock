"""A gap must be able to prove its own silence.

Cala answers a phrasing, not an intent. These tests pin the rule that one empty
answer is not evidence of anything: only a question that stays empty across
every phrasing we tried may be shown to a reader as a finding, and a failure
that is about *us* (a rate limit, a timeout) must never wear that costume.

No network: a fake client replays the row counts we measured live.
"""
import pytest

from app.agents.base import ask_variants, gap_from
from app.agents.ladder import natural_language_variant, questions_to_ladders
from app.clients.cala import CalaResult


class FakeCala:
    """Answers from a {query: rows} table, and records what it was asked."""

    def __init__(self, table):
        self.table = table
        self.asked = []

    async def query(self, text):
        self.asked.append(text)
        spec = self.table.get(text, [])
        if isinstance(spec, str):                      # an error string
            return CalaResult(query=text, endpoint="knowledge/query", error=spec)
        return CalaResult(query=text, endpoint="knowledge/query", rows=spec)


# The real numbers this whole change exists for.
CHUPA = {
    "Chupa Chups.raw_material_origin": [],
    "Chupa Chups.ingredients": [{"ingredient": "Sugar"}] * 5,
}
DAMM = {
    "Estrella Damm.barley_supplier": [],
    "Estrella Damm.raw_material_origin": [{"raw_material": "Barley malt"}] * 4,
}


@pytest.mark.asyncio
async def test_a_second_phrasing_rescues_a_false_gap():
    """The headline case: the first probe is empty, the second is not."""
    cala = FakeCala(CHUPA)
    res, attempts = await ask_variants(
        cala, ["Chupa Chups.raw_material_origin", "Chupa Chups.ingredients"])
    assert len(res.rows) == 5
    assert attempts == ["Chupa Chups.raw_material_origin"]


@pytest.mark.asyncio
async def test_it_stops_at_the_first_phrasing_that_answers():
    """No wasted probes — Cala is 16-75s cold and rate limits at ~6 calls."""
    cala = FakeCala(DAMM)
    await ask_variants(cala, ["Estrella Damm.raw_material_origin",
                              "Estrella Damm.barley_supplier"])
    assert cala.asked == ["Estrella Damm.raw_material_origin"]


@pytest.mark.asyncio
async def test_a_real_gap_records_every_attempt():
    """Silence is only reportable once every rung came back empty."""
    cala = FakeCala({})
    res, attempts = await ask_variants(cala, ["A.x", "A.y", "Is there an x for A?"])
    gap = gap_from(res, attempts)
    assert gap.reason == "no_rows"
    assert gap.attempts == ["A.x", "A.y", "Is there an x for A?"]


@pytest.mark.asyncio
async def test_a_rate_limit_is_never_dressed_up_as_silence():
    """The bug this guards: an empty payload from a 429 used to reach the reader
    as `rows = 0`, i.e. as 'nobody published this'. It is our failure, not the
    record's."""
    cala = FakeCala({"A.x": "rate_limited"})
    res, attempts = await ask_variants(cala, ["A.x", "A.y"])
    gap = gap_from(res, attempts)
    assert gap.reason == "rate_limited"
    assert cala.asked == ["A.x"]          # and it did not burn the other rungs


def test_dotted_probes_gain_a_plain_language_sibling():
    assert (natural_language_variant("Estrella Damm.barley_supplier")
            == "What is the barley supplier of Estrella Damm?")
    assert natural_language_variant("Who owns X?") is None


def test_planner_output_normalises_to_ladders():
    assert questions_to_ladders(None) == []
    assert questions_to_ladders([["A", "B"]]) == [["A", "B"]]
    assert questions_to_ladders(["X.lawsuits"])[0][0] == "X.lawsuits"
    assert len(questions_to_ladders(["X.lawsuits"])[0]) == 2
