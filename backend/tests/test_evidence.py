"""knowledge/search is the only endpoint that returns document URLs."""
from app.clients.cala import CalaClient

SEARCH_PAYLOAD = {
    "content": "## Child labour in the hazelnut supply chain",
    "explainability": [
        {"content": "Ferrero purchases roughly one-quarter of the global supply",
         "references": ["ctx-1"]},
    ],
    "context": [
        {"id": "ctx-1",
         "origins": [{"document": {"url": "https://www.businessinsider.com/nutella-child-labor"},
                      "source": {"name": "Business Insider"}}]},
        {"id": "ctx-2",
         "origins": [{"document": {"url": "https://www.theguardian.com/ferrero"},
                      "source": {"name": "The Guardian"}}]},
    ],
}


def test_shape_collects_document_urls():
    res = CalaClient._shape("q", "knowledge/search", SEARCH_PAYLOAD, 1.0, False)
    assert res.documents == ["https://www.businessinsider.com/nutella-child-labor",
                             "https://www.theguardian.com/ferrero"]


def test_shape_keeps_publisher_with_each_citation():
    res = CalaClient._shape("q", "knowledge/search", SEARCH_PAYLOAD, 1.0, False)
    assert res.citations[0] == {"id": "ctx-1",
                                "publisher": "Business Insider",
                                "url": "https://www.businessinsider.com/nutella-child-labor"}


def test_query_payloads_have_no_citations():
    res = CalaClient._shape("q", "knowledge/query", {"results": [{"name": "X"}]}, 1.0, False)
    assert res.citations == []
    assert res.documents == []


from app.schemas import Evidence, EvidenceSource


def test_evidence_without_a_url_is_not_citable():
    """Depuration rule 4: no public document URL means no user-facing fact."""
    e = Evidence(claim="Nutella's parent company is Ferrero Group.",
                 scope="brand",
                 sources=[EvidenceSource(query="Nutella.parent_company")])
    assert e.is_citable is False


def test_evidence_with_a_url_is_citable():
    e = Evidence(claim="Ferrero buys a quarter of the global hazelnut supply.",
                 scope="supply_chain", date="2019",
                 sources=[EvidenceSource(publisher="Business Insider",
                                         url="https://example.org/a",
                                         query="What child labour...?")])
    assert e.is_citable is True


def test_evidence_requires_at_least_one_source():
    import pytest
    with pytest.raises(Exception):
        Evidence(claim="x", scope="product", sources=[])
