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

# The two parsers below are pinned to shapes captured from the live API, not to
# a guess at the contract:
#
#   classification  result.data.{task}   = {label, confidence}
#   extraction      result.data.entities = {label: [{text, confidence, start, end}]}

def test_extraction_parser_reads_the_measured_shape():
    from app.clients.pioneer import _parse_entities
    out = _parse_entities({"result": {"data": {"entities": {
        "company": [{"text": "Henkell & Co.", "confidence": 0.94, "start": 30, "end": 43},
                    {"text": "Nestlé S.A.", "confidence": 0.96, "start": 0, "end": 11}],
        "family": [{"text": "Oetker family", "confidence": 0.91, "start": 60, "end": 73}],
        "wormhole": [{"text": "nonsense", "confidence": 0.99}],
    }}}})
    # off-schema labels are dropped, and spans come back in document order
    assert [e["text"] for e in out["entities"]] == [
        "Nestlé S.A.", "Henkell & Co.", "Oetker family"]


def test_extraction_parser_deduplicates():
    from app.clients.pioneer import _parse_entities
    out = _parse_entities({"result": {"data": {"entities": {"family": [
        {"text": "Oetker family", "confidence": 0.9, "start": 0},
        {"text": "oetker family", "confidence": 0.8, "start": 40},
    ]}}}})
    assert len(out["entities"]) == 1


def test_classification_parser_reads_the_measured_shape():
    from app.clients.pioneer import _parse_inference
    out = _parse_inference({"type": "encoder", "inference_id": "4f86e30a",
        "result": {"data": {"entity_kind": {"label": "company", "confidence": 0.6723},
                            "chain_terminates": {"label": "yes", "confidence": 0.817}}}})
    assert out == {"kind": "company", "confidence": 0.67, "terminal": True}


def test_parsers_return_nothing_rather_than_a_guess():
    """An unrecognised body must fall back to the heuristic, never corrupt the chain."""
    from app.clients.pioneer import _parse_entities, _parse_inference
    assert _parse_inference({}) is None
    assert _parse_inference({"result": {"data": {"entity_kind": {"label": "wormhole"}}}}) is None
    assert _parse_entities({}) == {"entities": [], "classifications": {}}


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


# --------------------------------------------------------------------------- #
#  auditor — reading a compliance answer without turning a denial into a claim
# --------------------------------------------------------------------------- #

def test_an_explicit_no_is_never_a_finding():
    """Cala answers a direct question with a boolean column. Filing a "no" as a
    flag would turn a denial into an accusation — the exact failure this agent
    exists to avoid."""
    from app.agents.auditor import _verdict
    assert _verdict({"name": "Nestlé", "accused_of_child_labour": "yes"})[:2] == (True, True)
    assert _verdict({"name": "Chupa Chups", "accused_of_child_labour": "no"})[:2] == (True, False)
    assert _verdict({"company": "Apple", "sector": "Technology"})[:2] == (False, False)


def test_flag_context_copies_values_and_computes_nothing():
    from app.agents.auditor import _context, _title
    row = {"incident": "Nestlé Waters — Illegal Water Drilling", "location": "France",
           "year": 2024, "fine_amount": "2 million", "fine_currency": "EUR",
           "description": "Fined over allegations of illegal water drilling."}
    assert _title(row) == "Nestlé Waters — Illegal Water Drilling"
    ctx = _context(row)
    assert "France" in ctx and "2024" in ctx and "2 million EUR" in ctx


def test_entity_matching_survives_legal_suffixes_and_accents():
    from app.agents.auditor import _matches
    assert _matches("Nestle", "Nestlé S.A.")
    assert _matches("Perfetti Van Melle", "Perfetti Van Melle Group B.V.")
    assert not _matches("Apple", "Chupa Chups")
    # too short to be safe — must not fire
    assert not _matches("BP", "BP p.l.c.")


def test_every_concern_has_both_probes():
    """A concern with a missing template would silently never be checked."""
    from app.agents.auditor import DIRECT_QUERY, LIST_QUERY
    from app.schemas import Concern
    for c in Concern:
        assert c in LIST_QUERY and c in DIRECT_QUERY, c
        assert "{e}" in DIRECT_QUERY[c], c


def test_a_registry_placeholder_survives_a_confident_model():
    """Observed live: the encoder called "(Largest institutional holder — name
    truncated in data)" a company at 0.60, which put an entity that does not
    exist in the middle of the chain and spent a cold Cala query asking for its
    shareholders. Whether a string is a placeholder is a fact about the scrape,
    not a judgement, so no model gets a vote on it."""
    import asyncio

    from app.clients.pioneer import PioneerClient

    client = PioneerClient()
    rows = [{"name": "(Largest institutional holder — name truncated in data)"},
            {"name": "Vanguard Capital Management LLC"}]
    got = asyncio.run(client.assay(rows))
    assert got[0]["kind"] == "not_an_entity" and got[0]["terminal"] is False
    assert got[1]["kind"] != "not_an_entity"


def test_reader_layers_are_marked_provisional():
    """The reader and the prospector both emit `layer` frames. Without a marker a
    front end appends two independent readings as if they were one chain — seen
    live on Nespresso, where the prose gave "Nestlé S.A." while the ladder was
    still walking to it."""
    import asyncio

    from app.agents.reader import ReaderAgent
    from app.clients.cala import CalaResult

    class FakeCala:
        async def search(self, q):
            return CalaResult(query=q, endpoint="knowledge/search",
                              content="Nespresso is owned by Nestlé S.A.", latency_s=0.8)

    class FakePioneer:
        async def extract(self, text, schema=None):
            return {"entities": [
                {"text": "Nespresso", "label": "company", "score": 0.9},        # the subject
                {"text": "Nestlé S.A.", "label": "company", "score": 0.95},
                {"text": "Nestlé", "label": "company", "score": 0.9},           # same company
                {"text": "Free float", "label": "company", "score": 0.8},       # a placeholder
            ], "classifications": {}, "latency_s": 0.1}

    async def emit(kind, payload, *a):
        return None

    layers, _ = asyncio.run(
        ReaderAgent(FakeCala(), FakePioneer()).run("Nespresso", emit))

    assert [l.name for l in layers] == ["Nestlé S.A."]   # subject, dupe, placeholder all dropped
    assert all(l.provisional for l in layers)


def test_search_citations_resolve_to_documents_a_reader_can_open():
    """`explainability` names fact ids; `context[].origins[].document.url` resolves
    them. Reading only the first leaves every citation a query string with nothing
    to click, which is not a citation."""
    from app.clients.cala import CalaClient
    res = CalaClient._shape("q", "knowledge/search", {
        "content": "…",
        "explainability": [{"content": "…", "references": ["b0595ee6"]}],
        "context": [{"id": "b0595ee6", "content": "…", "origins": [
            {"source": {"name": "wikiwand.com", "url": "https://www.wikiwand.com/en/articles/X"},
             "document": {"name": "X", "url": "https://www.wikiwand.com/en/articles/X"}},
            {"document": {"name": "LEI", "url": "https://search.gleif.org/#/record/8755"}},
            {"document": {"name": "no url"}},
        ]}],
    }, 0.8, False)
    assert res.documents == ["https://www.wikiwand.com/en/articles/X",
                             "https://search.gleif.org/#/record/8755"]
    assert "b0595ee6" in res.fact_ids


def test_a_beat_never_asserts_a_relationship_the_ladder_did_not_confirm():
    """Observed live on Nespresso: the reader lifted "SIX Swiss Exchange" out of
    the prose — the venue Nestlé lists on — and the story template turned mention
    order into "Nestlé S.A. answers to SIX Swiss Exchange". A beat asserts a
    relationship, so it may only be built from a confirmed layer."""
    from app.agents.extractor import build_story
    from app.schemas import Score, Source, Subject

    src = Source(query="q", latency_s=0.5)
    sketch = Layer(index=0, name="SIX Swiss Exchange", kind="company",
                   provisional=True, source=src)
    real = Layer(index=0, name="Nestlé S.A.", kind="company", source=src)
    subject = Subject(raw_input="Nespresso", resolved_name="Nespresso")

    beats = build_story(subject, [sketch, real], Score(hops_to_human=1), [], [], [])
    said = " ".join(b.headline for b in beats)
    assert "SIX Swiss Exchange" not in said
    assert "Nestlé S.A." in said


def test_handover_wording_follows_the_data():
    """"answers to" is right for a parent and wrong for a passive index fund
    holding two per cent. Overstating a relationship damages the piece as much as
    inventing one, so the verb comes from the row."""
    from app.agents.extractor import _handover
    from app.schemas import Source
    src = Source(query="q", latency_s=0.5)
    parent = Layer(index=0, name="Perfetti Van Melle", kind="company",
                   relationship="direct parent", source=src)
    holder = Layer(index=0, name="Vanguard Total International Stock Index Fund",
                   kind="fund", stake_percent=2.1, source=src)
    listed = Layer(index=0, name="Some Nominee", kind="company", source=src)
    assert _handover("Chupa Chups", parent) == "Chupa Chups answers to Perfetti Van Melle."
    assert "holds 2.1% of Nestlé" in _handover("Nestlé", holder)
    assert "appears on the share register" in _handover("Nestlé", listed)


# --------------------------------------------------------------------------- #
#  voice input
# --------------------------------------------------------------------------- #

def test_audio_reader_takes_a_name_and_refuses_a_narration():
    """The model answers a prompt rather than transcribing, so it can return a
    sentence about the recording. A name is short; anything long is the model
    narrating and is not a product name."""
    from app.clients.falstt import FalClient
    read = FalClient._read
    assert read({"output": "Nespresso"}) == "Nespresso"
    assert read({"output": '  "Chupa Chups." '}) == "Chupa Chups"
    assert read({"output": "UNKNOWN"}) is None
    assert read({"text": "Estrella Damm"}) == "Estrella Damm"          # whisper shape
    assert read({"output": "The speaker appears to be naming " * 5}) is None


def test_only_containers_the_model_accepts_are_sent():
    """Measured: the model reads the extension off the URL and returns 422 for
    anything but .wav/.mp3 — including the audio/webm a browser produces by
    default, and including a data URI of valid wav bytes."""
    from app.clients.falstt import _EXT
    assert _EXT["audio/wav"] == "wav" and _EXT["audio/mpeg"] == "mp3"
    assert "audio/webm" not in _EXT


def test_editorial_reaches_the_wire():
    """Task 7: the routes were built and tested but nothing called them, so
    `CoreSample` never carried an `editorial` field. This pins the assembly."""
    from app.agents.extractor import ExtractorAgent
    from app.schemas import EditorialRoutes, Source, StructureRoute, Subject

    sample = ExtractorAgent().build(
        sample_id="t", started_at=0.0,
        subject=Subject(raw_input="x", resolved_name="x"),
        layers=[Layer(index=0, name="Ferrero Group", kind="company",
                      source=Source(query="q", latency_s=0.5))],
        supply=[], statutes=[], flags=[], siblings=[], gaps=[],
        editorial=EditorialRoutes(structure=StructureRoute(status="partial")),
        queries_run=1, cache_hits=0, agents=[], models={})

    assert sample.editorial is not None
    assert sample.editorial.structure.status == "partial"
