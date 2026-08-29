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


@pytest.mark.parametrize("name", [
    "Free float", "Treasury shares", "Other shareholders", "Public float",
])
def test_register_categories_are_not_owners(name):
    """A share register leads with rows that name a category, not a person. Walking
    up from "Free float" produces nonsense, so the assay has to reject them."""
    out = _heuristic(name, {})
    assert out["kind"] == "not_an_entity"
    assert out["terminal"] is False


def test_assay_schema_matches_the_labels_we_train_on():
    from app.clients.pioneer import ASSAY_SCHEMA, KINDS
    tasks = {c["task"]: c["labels"] for c in ASSAY_SCHEMA["classifications"]}
    assert tasks["entity_kind"] == KINDS
    assert tasks["chain_terminates"] == ["yes", "no"]


def test_row_text_carries_the_columns_that_disambiguate():
    from app.clients.pioneer import row_text
    t = row_text("Juan Roig", {"role": "executive chairman", "ownership_percent": "50.66%"})
    assert "Juan Roig" in t and "role" in t and "50.66" in t


# --------------------------------------------------------------------------- #
#  reader / extraction
# --------------------------------------------------------------------------- #

def test_extraction_parser_rejects_labels_it_does_not_know():
    """A model returning something off-schema must yield nothing, never a guess."""
    from app.clients.pioneer import _parse_entities
    out = _parse_entities({"result": {"entities": [
        {"text": "Perfetti Van Melle", "label": "company", "score": 0.91},
        {"text": "nonsense", "label": "wormhole", "score": 0.99},
    ]}})
    assert [e["text"] for e in out["entities"]] == ["Perfetti Van Melle"]


def test_extraction_parser_deduplicates():
    from app.clients.pioneer import _parse_entities
    out = _parse_entities({"result": {"entities": [
        {"text": "Oetker family", "label": "family", "score": 0.9},
        {"text": "oetker family", "label": "family", "score": 0.8},
    ]}})
    assert len(out["entities"]) == 1


def test_bench_scoring_treats_a_longer_legal_name_as_a_hit():
    """"Henkell & Co. Sektkellerei KG" and "Henkell & Co." are one company;
    scoring that as a miss would flatter whichever system is terser."""
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "bench", pathlib.Path(__file__).parents[1] / "scripts" / "bench.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)  # type: ignore[union-attr]
    tp, fp, fn = bench.score(
        [{"text": "Henkell & Co. Sektkellerei KG"}, {"text": "Oetker family"}],
        ["Henkell & Co.", "Oetker family"])
    assert (tp, fn) == (2, 0)


# --------------------------------------------------------------------------- #
#  reader path, end to end, without the network
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_reader_turns_prose_into_layers():
    """Everything between a GLiNER2 response and a CoreSample, proven offline.

    When the account is unblocked the only remaining unknown is the wire format
    itself; this pins the behaviour on either side of it.
    """
    from app.agents.reader import ReaderAgent
    from app.clients.cala import CalaResult

    prose = ("Freixenet S.A., the Spanish cava producer founded in 1928, is ultimately "
             "owned by the Oetker family. Henkell & Co. Sektkellerei KG, based in "
             "Wiesbaden, Germany, is the direct parent.")

    class FakeCala:
        async def search(self, q):
            return CalaResult(query=q, endpoint="knowledge/search", content=prose,
                              latency_s=0.85, cached=True, fact_ids=["fact-1"])

    class FakePioneer:
        async def extract(self, text, schema=None):
            assert prose[:40] in text
            return {"entities": [
                {"text": "Henkell & Co. Sektkellerei KG", "label": "company", "score": 0.94},
                {"text": "Oetker family", "label": "family", "score": 0.91},
                {"text": "Wiesbaden, Germany", "label": "jurisdiction", "score": 0.88},
                {"text": "1928", "label": "date", "score": 0.8},
            ], "classifications": {"chain_position": "direct_parent"},
                "latency_s": 0.09}

    seen = []

    async def emit(kind, payload, *a):
        seen.append((kind, payload))

    layers, gaps = await ReaderAgent(FakeCala(), FakePioneer()).run("Freixenet", emit)

    assert not gaps
    assert [l.name for l in layers] == ["Henkell & Co. Sektkellerei KG", "Oetker family"]
    assert layers[1].kind.value == "family" and layers[1].terminal is True
    assert layers[0].terminal is False
    # jurisdictions and dates ride along as detail, never as their own layer
    assert any("Wiesbaden" in d for d in layers[0].detail)
    # the one rule: every layer still carries the Cala query that produced the prose
    assert all(l.source.query.startswith("Who ultimately owns") for l in layers)
    assert all(l.source.endpoint == "knowledge/search" for l in layers)
    assert [k for k, _ in seen].count("layer") == 2


@pytest.mark.asyncio
async def test_reader_stays_silent_without_pioneer():
    """No extractor configured must mean no contribution — never a guess."""
    from app.agents.reader import ReaderAgent
    from app.clients.cala import CalaResult

    class FakeCala:
        async def search(self, q):
            return CalaResult(query=q, endpoint="knowledge/search",
                              content="Some prose.", latency_s=0.5)

    class NoPioneer:
        async def extract(self, text, schema=None):
            return None

    layers, gaps = await ReaderAgent(FakeCala(), NoPioneer()).run("X", lambda *a: _noop())
    assert layers == [] and gaps == []


async def _noop():
    return None


@pytest.mark.parametrize("name", [
    "(Largest institutional holder — name truncated in data)",
    "Name not available",
    "Nominee account",
    "[redacted]",
])
def test_registry_placeholders_are_not_entities(name):
    """Scrapes leave placeholders where a name should be. Following one costs a
    40-second Cala query and puts a company that does not exist into the chain —
    observed live on a Nespresso dig."""
    assert _heuristic(name, {})["kind"] == "not_an_entity"
