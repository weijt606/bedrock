from app.orchestrator import _conduct_candidate
from app.schemas import Evidence, EvidenceSource


def evidence(claim: str) -> Evidence:
    return Evidence(claim=claim, scope="supply_chain", sources=[EvidenceSource(
        publisher="Source", url="https://example.org/source", query="q")])


def test_conduct_candidate_keeps_cala_claims_in_their_evidence_roles():
    product = [evidence("Nutella sources hazelnuts from Turkey.")]
    record = [
        evidence("Turkey produces most of the world's hazelnuts and Ferrero buys a large share."),
        evidence("Ferrero identified 3,020 children working on hazelnut farms in Turkey."),
        evidence("Ferrero partnered with the ILO on a child labour programme."),
    ]

    candidate = _conduct_candidate("Nutella", "hazelnuts", product, record)

    assert candidate is not None
    assert [chapter["role"] for chapter in candidate["chapters"]] == [
        "product_link", "commercial_link", "documented_impact", "response"]
    assert candidate["chapters"][2]["evidence"][0].claim.startswith("Ferrero identified 3,020")


def test_conduct_candidate_refuses_an_impact_without_the_product_bridge():
    candidate = _conduct_candidate("Nutella", "hazelnuts", [], [
        evidence("Ferrero identified 3,020 children working on hazelnut farms in Turkey."),
        evidence("Turkey produces most of the world's hazelnuts and Ferrero buys a large share."),
    ])
    assert candidate is None
