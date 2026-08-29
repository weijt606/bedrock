"""Structure route rules 1-4 of docs/EXTRACTOR_OUTPUT.md."""
from app.agents.editorial import build_structure
from app.schemas import Evidence, EvidenceSource, Layer, Source

CITED = [Evidence(claim="Ferrero Group owns Nutella.", scope="brand",
                  sources=[EvidenceSource(publisher="Reuters",
                                          url="https://example.org/a",
                                          query="Who owns Nutella?")])]
UNCITED = [Evidence(claim="Ferrero Group owns Nutella.", scope="brand",
                    sources=[EvidenceSource(query="Nutella.parent_company")])]


def _layer(i, name, kind="company", cc=None, terminal=False):
    return Layer(index=i, name=name, kind=kind, country=cc, terminal=terminal,
                 source=Source(query="q", latency_s=0.5, cached=True))


def test_a_chain_without_urls_is_partial_not_evidenced():
    """Rule 4. This is the normal case today, not an edge case."""
    route = build_structure([_layer(1, "Ferrero Group", cc="IT")],
                            {"Ferrero Group": UNCITED})
    assert route.status == "partial"
    assert route.chapters[0].entity == "Ferrero Group"


def test_a_cited_chain_ending_in_a_family_is_evidenced():
    route = build_structure(
        [_layer(1, "Ferrero Group", cc="IT"),
         _layer(2, "Ferrero family", kind="family", cc="IT", terminal=True)],
        {"Ferrero Group": CITED, "Ferrero family": CITED})
    assert route.status == "evidenced"
    assert route.ending.kind == "family"
    assert route.ending.name == "Ferrero family"


def test_cala_order_is_preserved():
    """Rule 1: never reorder by country, confidence or visual effect."""
    route = build_structure(
        [_layer(1, "B", cc="LU"), _layer(2, "A", cc="ES")],
        {"B": CITED, "A": CITED})
    assert [c.entity for c in route.chapters] == ["B", "A"]


def test_no_layers_is_not_found_and_never_invents_an_owner():
    route = build_structure([], {})
    assert route.status == "not_found"
    assert route.chapters == []
    assert route.ending is None


def test_an_unterminated_chain_is_partial():
    """Rule 2: a depth cap ends with partial, never with an invented owner."""
    route = build_structure([_layer(1, "Ferrero Group", cc="IT")],
                            {"Ferrero Group": CITED})
    assert route.status == "partial"
    assert route.ending is None
