"""Conduct route status rules and ordering."""
from app.agents.editorial import build_conduct
from app.schemas import Evidence, EvidenceSource


def ev(claim, url="https://example.org/a", date=None, scope="supply_chain"):
    return Evidence(claim=claim, scope=scope, date=date,
                    sources=[EvidenceSource(publisher="P", url=url, query="q")])


FULL = {
    "id": "hazelnuts-turkiye-child-labour", "topic": "labor", "scope": "supply_chain",
    "chapters": [
        {"role": "product_link", "evidence": [ev("Nutella contains hazelnuts.")]},
        {"role": "commercial_link", "evidence": [ev("Ferrero buys a quarter of the crop.")]},
        {"role": "documented_impact", "evidence": [ev("3,020 children identified.", date="2024")]},
    ],
}


def test_a_complete_cited_chain_is_evidenced():
    out = build_conduct([FULL])
    assert out[0].status == "evidenced"
    assert [c.role for c in out[0].chapters] == [
        "product_link", "commercial_link", "documented_impact"]


def test_an_impact_without_a_commercial_link_is_partial():
    """Rule 5: a parent-company record cannot become product conduct without
    a documented bridge."""
    broken = {**FULL, "chapters": [FULL["chapters"][0], FULL["chapters"][2]]}
    assert build_conduct([broken])[0].status == "partial"


def test_an_uncited_impact_is_partial():
    uncited = {**FULL, "chapters": FULL["chapters"][:2] + [
        {"role": "documented_impact",
         "evidence": [Evidence(claim="x", scope="supply_chain",
                               sources=[EvidenceSource(query="q")])]}]}
    assert build_conduct([uncited])[0].status == "partial"


def test_paths_order_by_completeness_then_recency_never_by_severity():
    older = {**FULL, "id": "older",
             "chapters": FULL["chapters"][:2] + [
                 {"role": "documented_impact", "evidence": [ev("older", date="2019")]}]}
    partial = {**FULL, "id": "partial", "chapters": [FULL["chapters"][0]]}
    out = build_conduct([partial, older, FULL])
    assert [p.id for p in out] == ["hazelnuts-turkiye-child-labour", "older", "partial"]


def test_chapters_are_emitted_in_the_specified_role_order():
    shuffled = {**FULL, "chapters": list(reversed(FULL["chapters"]))}
    assert [c.role for c in build_conduct([shuffled])[0].chapters] == [
        "product_link", "commercial_link", "documented_impact"]
