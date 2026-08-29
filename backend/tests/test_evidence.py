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
