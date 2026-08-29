"""The enricher maps Cala's explainability chain onto Evidence.

claim -> references[] -> context[].id -> origins[].document.url
"""
import pytest

from app.agents.enricher import EnricherAgent
from app.clients.cala import CalaResult


class FakeCala:
    def __init__(self, result):
        self.result = result
        self.asked = []

    async def search(self, text):
        self.asked.append(text)
        return self.result


RESULT = CalaResult(
    query="What child labour is documented in Ferrero's hazelnut supply chain?",
    endpoint="knowledge/search",
    content="...",
    documents=["https://bi.example/a", "https://guardian.example/b"],
    citations=[{"id": "ctx-1", "publisher": "Business Insider", "url": "https://bi.example/a"},
               {"id": "ctx-2", "publisher": "The Guardian", "url": "https://guardian.example/b"}],
    explainability=[
        {"content": "Ferrero purchases roughly one-quarter of the global supply.",
         "references": ["ctx-1"]},
        {"content": "Children as young as 11 were working as pickers.",
         "references": ["ctx-2", "ctx-1"]},
    ],
)


@pytest.mark.asyncio
async def test_each_claim_gets_only_its_own_citations():
    ev = await EnricherAgent(FakeCala(RESULT)).evidence_for("q", "supply_chain")
    assert ev[0].claim == "Ferrero purchases roughly one-quarter of the global supply."
    assert [s.publisher for s in ev[0].sources] == ["Business Insider"]
    assert [s.publisher for s in ev[1].sources] == ["The Guardian", "Business Insider"]


@pytest.mark.asyncio
async def test_a_claim_with_no_resolvable_citation_is_dropped():
    """Rule 4: emit an enrichment need, never a fake citation."""
    res = CalaResult(query="q", endpoint="knowledge/search", citations=[],
                     explainability=[{"content": "Unbacked.", "references": ["ctx-9"]}])
    assert await EnricherAgent(FakeCala(res)).evidence_for("q", "product") == []


@pytest.mark.asyncio
async def test_scope_and_date_travel_onto_every_claim():
    ev = await EnricherAgent(FakeCala(RESULT)).evidence_for("q", "supply_chain", date="2024")
    assert all(e.scope == "supply_chain" and e.date == "2024" for e in ev)
