"""Contract tests. No network: these guard the shapes the front end builds on."""
import pytest

from app.agents.extractor import ExtractorAgent
from app.clients.pioneer import _heuristic
from app.schemas import CoreSample, Layer, Source, Subject


def _layer(i, name, kind="company", cc=None, terminal=False) -> Layer:
    return Layer(index=i, name=name, kind=kind, country=cc, terminal=terminal,
                 source=Source(query="q", latency_s=0.5, cached=True))


def test_source_is_required():
    """The central guarantee: no agent can emit an unsourced fact."""
    with pytest.raises(Exception):
        Layer(index=0, name="X")  # type: ignore[call-arg]


def test_extractor_scores_a_chain():
    subject = Subject(raw_input="Chupa Chups", resolved_name="Chupa Chups",
                      description="An iconic lollipop brand founded in Barcelona in 1958.")
    layers = [_layer(0, "Perfetti Van Melle", cc="NL"),
              _layer(1, "C+F Confectionery and Foods S.A.", cc="LU"),
              _layer(2, "Perfetti family", kind="family", cc="IT", terminal=True)]
    s = ExtractorAgent().build(
        sample_id="t", started_at=0.0, subject=subject, layers=layers, supply=[],
        statutes=[], flags=[], siblings=["Mentos"], gaps=[], queries_run=3,
        cache_hits=3, agents=["extractor"], models={})

    assert isinstance(s, CoreSample)
    assert s.score.hops_to_human == 3
    assert s.score.origin_country == "ES"
    assert s.score.ends_in == "IT"
    assert s.score.left_home is True
    assert s.score.countries == ["ES", "NL", "LU", "IT"]


def test_guess_answers_are_present_on_the_finished_sample():
    subject = Subject(raw_input="x", resolved_name="x", description="A Spanish brand.")
    s = ExtractorAgent().build(
        sample_id="t", started_at=0.0, subject=subject,
        layers=[_layer(0, "Something S.A.", cc="DE", terminal=True)], supply=[],
        statutes=[], flags=[], siblings=[], gaps=[], queries_run=1, cache_hits=1,
        agents=[], models={})
    by_id = {g.id: g for g in s.guesses}
    assert by_id["ends_in_country"].answer == "Germany"
    assert by_id["hops_to_human"].answer == "1-2"
    assert by_id["still_domestic"].answer == "No"


@pytest.mark.parametrize("name,expected,terminal", [
    ("C+F Confectionery and Foods S.A.", "company", False),
    ("Perfetti family", "family", True),
    ("Inter IKEA Foundation", "foundation", True),
    ("Meridia Capital Partners", "fund", False),
])
def test_assay_fallback(name, expected, terminal):
    out = _heuristic(name, {})
    assert out["kind"] == expected
    assert out["terminal"] is terminal


def test_a_person_needs_an_explicit_signal():
    """Two capitalised words alone are ambiguous — keep digging rather than stop."""
    assert _heuristic("Juan Roig", {})["terminal"] is False
    assert _heuristic("Juan Roig", {"ownership_percent": "50.66%"})["terminal"] is True


def test_ambiguous_names_never_end_the_dig():
    """"Perfetti Van Melle" and "Juan Roig" are indistinguishable to a regex, so the
    fallback refuses to guess and keeps digging. Labelling that company a person is
    the failure that used to end the chain one hop in. This is precisely the case
    the Pioneer assay model exists to resolve."""
    for name in ("Perfetti Van Melle", "Juan Roig", "Dr. h.c. August Oetker"):
        out = _heuristic(name, {})
        assert out["terminal"] is False, name
        assert out["kind"] != "person", name
