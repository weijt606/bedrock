# Editorial Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit a populated `editorial` field on `CoreSample` so the front end renders sourced, de-duplicated routes instead of raw Cala rows.

**Architecture:** Three layers, built bottom-up. (1) The Cala client learns to read `context[]` from `knowledge/search`, which is the only endpoint that returns document URLs. (2) A new `enricher` agent turns a candidate claim into `Evidence` carrying those URLs. (3) The extractor applies the depuration rules and assembles `structure`, `conduct`, `public_records`, `brands`, `gaps` and `coverage`. Nothing above layer 1 can produce an `evidenced` result until layer 1 exists, which is why it is Task 1.

**Tech Stack:** Python 3.12, pydantic v2, pytest + pytest-asyncio, httpx. No new dependencies.

**Spec:** `docs/EXTRACTOR_OUTPUT.md`. The worked target output is `docs/examples/editorial-nutella.json` — when this plan is done, the pipeline should be able to produce that shape for Nutella.

## Global Constraints

- **No language model states a fact.** LLMs plan queries and classify rows. Every user-visible claim carries `Evidence` pointing at Cala. (`README.md`, "The one rule")
- **Never rank or judge a company.** No severity ordering, no ethics score, no adjectives about a named company. Ordering is by evidence completeness, then impact recency, then source count. (`EXTRACTOR_OUTPUT.md`, "Conduct route")
- **No public document URL means no user-facing fact.** Emit an enrichment need, never a fake citation. (Depuration rule 4)
- **Uncertainty stays explicit.** `no_rows`, `too_complex`, `error`, `rate_limited` are four different outcomes and only `no_rows` is content. (Depuration rule 7, and `Gap.reason` as landed in PR #8)
- **Additive contract changes only.** `docs/API.md` is changed by agreement; adding a field never breaks. (`docs/CONTRIBUTING.md`)
- All commands run from `backend/` with the project venv: `./.venv/bin/pytest -q`
- Tests never hit the network. Fake the Cala client.

---

### Task 1: Cala client reads document URLs from `knowledge/search`

`Source.documents` is currently always `[]` because nothing parses the `context[]` array. This blocks every `evidenced` output in the spec.

**Files:**
- Modify: `backend/app/clients/cala.py:105-123` (the `_shape` staticmethod)
- Test: `backend/tests/test_evidence.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `CalaResult.documents: list[str]` populated from search payloads, and a new `CalaResult.citations: list[dict]` where each entry is `{"id": str, "publisher": str, "url": str}`. Task 3 consumes `citations`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_evidence.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_evidence.py -q`
Expected: FAIL — `AttributeError: 'CalaResult' object has no attribute 'citations'`

- [ ] **Step 3: Write minimal implementation**

Add the field to the dataclass in `backend/app/clients/cala.py`, next to `documents`:

```python
    citations: list[dict[str, str]] = field(default_factory=list)
```

Then in `_shape`, immediately after the existing `explainability` loop:

```python
        # `context[]` is the only place Cala returns a citable URL. Each entry
        # carries the publisher next to the document, so keep them paired —
        # a bare URL cannot be rendered as "The Guardian" in the UI.
        for ctx in payload.get("context") or []:
            cid = (ctx or {}).get("id")
            for origin in (ctx or {}).get("origins") or []:
                url = ((origin or {}).get("document") or {}).get("url")
                if not url or url in res.documents:
                    continue
                res.documents.append(url)
                res.citations.append({
                    "id": cid or "",
                    "publisher": ((origin or {}).get("source") or {}).get("name") or "",
                    "url": url,
                })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_evidence.py -q`
Expected: 3 passed

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass. `citations` is additive; no existing test constructs it.

- [ ] **Step 6: Commit**

```bash
git add backend/app/clients/cala.py backend/tests/test_evidence.py
git commit -m "Read document URLs out of knowledge/search context"
```

---

### Task 2: Evidence primitives on the wire

**Files:**
- Modify: `backend/app/schemas.py` (add after the `Source` class, before `EntityKind`)
- Test: `backend/tests/test_evidence.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `EvidenceSource(publisher: str | None, url: str | None, query: str)` and `Evidence(claim: str, scope: str, date: str | None, sources: list[EvidenceSource])`, plus `Evidence.is_citable` returning `True` when at least one source has a non-empty `url`. Tasks 3, 5, 6 and 7 consume both.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_evidence.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_evidence.py -q`
Expected: FAIL — `ImportError: cannot import name 'Evidence'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schemas.py — after class Source

Scope = Literal["product", "brand", "parent", "supplier",
                "supply_chain", "sector", "regulator"]


class EvidenceSource(BaseModel):
    """One citation behind a claim. `query` is kept for audit; `url` is what the
    reader can actually open, and its absence is what makes a claim uncitable."""

    publisher: str | None = None
    url: str | None = None
    query: str = Field(description="The exact string sent to Cala")


class Evidence(BaseModel):
    """A claim Cala stated, with its provenance.

    The extractor may select, order, de-duplicate and place these in a template.
    It may never rewrite the claim, imply causation, or synthesise a summary.
    """

    claim: str
    scope: Scope
    date: str | None = None
    sources: list[EvidenceSource] = Field(min_length=1)

    @property
    def is_citable(self) -> bool:
        return any(s.url for s in self.sources)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_evidence.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_evidence.py
git commit -m "Add Evidence primitives to the wire contract"
```

---

### Task 3: The enricher agent

Turns a narrow question into citable `Evidence` by asking `knowledge/search` and pairing each `explainability` claim with the `context` entries it references.

**Files:**
- Create: `backend/app/agents/enricher.py`
- Modify: `backend/app/agents/__init__.py` (export `EnricherAgent`)
- Test: `backend/tests/test_enricher.py` (create)

**Interfaces:**
- Consumes: `CalaResult.citations` (Task 1), `Evidence` / `EvidenceSource` (Task 2).
- Produces: `EnricherAgent(cala).evidence_for(question: str, scope: str, date: str | None = None) -> list[Evidence]`. Tasks 5 and 6 consume it.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_enricher.py
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
    orphan = RESULT.model_copy() if hasattr(RESULT, "model_copy") else RESULT
    res = CalaResult(query="q", endpoint="knowledge/search", citations=[],
                     explainability=[{"content": "Unbacked.", "references": ["ctx-9"]}])
    assert await EnricherAgent(FakeCala(res)).evidence_for("q", "product") == []


@pytest.mark.asyncio
async def test_scope_and_date_travel_onto_every_claim():
    ev = await EnricherAgent(FakeCala(RESULT)).evidence_for("q", "supply_chain", date="2024")
    assert all(e.scope == "supply_chain" and e.date == "2024" for e in ev)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_enricher.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agents.enricher'`

Note: this test also requires `CalaResult.explainability`. Add it in Step 3.

- [ ] **Step 3: Write minimal implementation**

First add the raw claim list to the dataclass in `backend/app/clients/cala.py`, beside `citations`:

```python
    explainability: list[dict[str, Any]] = field(default_factory=list)
```

and populate it inside the existing `explainability` loop in `_shape`:

```python
        for item in payload.get("explainability") or []:
            res.explainability.append(item or {})
            for ref in (item or {}).get("references") or []:
```

Then create `backend/app/agents/enricher.py`:

```python
"""Turning a question into citable Evidence.

`knowledge/query` returns typed rows and no sources. `knowledge/search` returns
prose plus the chain that makes a claim citable:

    explainability[i].content     the claim
    explainability[i].references  -> context[j].id
    context[j].origins[k]         -> document.url + source.name

This agent walks that chain. It selects and pairs; it never writes a claim.
"""
from __future__ import annotations

from typing import Any

from ..schemas import Evidence, EvidenceSource


class EnricherAgent:
    name = "enricher"

    def __init__(self, cala: Any) -> None:
        self.cala = cala

    async def evidence_for(self, question: str, scope: str,
                           date: str | None = None) -> list[Evidence]:
        res = await self.cala.search(question)
        by_id = {c["id"]: c for c in getattr(res, "citations", []) if c.get("id")}
        out: list[Evidence] = []
        for item in getattr(res, "explainability", []):
            claim = (item or {}).get("content")
            if not isinstance(claim, str) or not claim.strip():
                continue
            sources = [
                EvidenceSource(publisher=by_id[ref].get("publisher") or None,
                               url=by_id[ref].get("url") or None,
                               query=question)
                for ref in (item or {}).get("references") or [] if ref in by_id
            ]
            # No resolvable citation means no user-facing fact.
            if not sources:
                continue
            out.append(Evidence(claim=claim.strip(), scope=scope,
                                date=date, sources=sources))
        return out
```

Export it in `backend/app/agents/__init__.py` alongside the existing agents:

```python
from .enricher import EnricherAgent
```

and add `"EnricherAgent"` to that module's `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_enricher.py -q`
Expected: 3 passed

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/enricher.py backend/app/agents/__init__.py \
        backend/app/clients/cala.py backend/tests/test_enricher.py
git commit -m "Add the enricher: questions in, cited Evidence out"
```

---

### Task 4: Depuration helpers

The spec's rules 1, 2 and 3 — type resolution, self-reference removal, de-duplication — as pure functions, testable without any Cala shape.

**Files:**
- Create: `backend/app/agents/depuration.py`
- Test: `backend/tests/test_depuration.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `normalise_name(name: str) -> str`, `resolve_row_type(row: dict) -> str` returning one of `ingredient|manufacturer|supplier|factory|unknown`, and `dedupe(items: list[dict], key: Callable[[dict], tuple]) -> list[dict]`. Task 7 consumes all three.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_depuration.py
"""Spec rules 1-3, as pure functions."""
from app.agents.depuration import dedupe, normalise_name, resolve_row_type


def test_normalise_strips_case_accents_and_legal_suffixes():
    assert normalise_name("FERRERO GROUP S.p.A.") == "ferrero group"
    assert normalise_name("Nestlé S.A.") == "nestle"
    assert normalise_name("  Ferrero,  Inc. ") == "ferrero"


def test_an_ingredient_is_never_called_a_supplier():
    """Rule 1. The surveyor's ingredient ladder and its manufacturer ladder
    both land in supply[], and conflating them mislabels food as a company."""
    assert resolve_row_type({"ingredient": "Hazelnuts", "origin": "Turkey"}) == "ingredient"
    assert resolve_row_type({"manufacturer": "Casa Tarradellas"}) == "manufacturer"
    assert resolve_row_type({"factory_group": "Foxconn"}) == "factory"
    assert resolve_row_type({"supplier": "Wilmar"}) == "supplier"
    assert resolve_row_type({"something": "else"}) == "unknown"


def test_raw_material_rows_are_ingredients():
    assert resolve_row_type({"raw_material": "Barley malt",
                             "origin": "Mediterranean"}) == "ingredient"


def test_dedupe_merges_identical_entity_and_role_pairs():
    rows = [{"name": "Ferrero S.p.A.", "role": "parent"},
            {"name": "FERRERO", "role": "parent"},
            {"name": "Ferrero", "role": "supplier"}]
    out = dedupe(rows, key=lambda r: (normalise_name(r["name"]), r["role"]))
    assert len(out) == 2
    assert out[0]["name"] == "Ferrero S.p.A."   # first occurrence wins
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_depuration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agents.depuration'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/depuration.py
"""Cleaning Cala rows before they become editorial output.

Cala returns real data in inconsistent shapes: the same company arrives as
"Ferrero", "FERRERO GROUP S.p.A." and "Ferrero, Inc.", and an ingredient row
and a manufacturer row both land in supply[]. These helpers implement rules
1-3 of docs/EXTRACTOR_OUTPUT.md and nothing else.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Iterable

_SUFFIXES = (
    "s.p.a", "spa", "s.a", "sa", "n.v", "nv", "b.v", "bv", "gmbh", "ag",
    "plc", "ltd", "limited", "llc", "inc", "corp", "corporation", "co",
    "group", "holdings", "holding", "pty", "llp", "lp",
)


def normalise_name(name: str) -> str:
    """Lower-case, strip accents, punctuation and legal suffixes."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    words = [w for w in s.split() if w]
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


_TYPE_KEYS = (
    ("ingredient", ("ingredient", "raw_material", "component")),
    ("manufacturer", ("manufacturer", "manufactured_by", "maker")),
    ("factory", ("factory_group", "factory", "plant")),
    ("supplier", ("supplier", "vendor")),
)


def resolve_row_type(row: dict[str, Any]) -> str:
    """Rule 1. Classify a surveyor row. Never call an ingredient a supplier."""
    for kind, keys in _TYPE_KEYS:
        if any(row.get(k) for k in keys):
            return kind
    return "unknown"


def dedupe(items: Iterable[dict[str, Any]],
           key: Callable[[dict[str, Any]], tuple]) -> list[dict[str, Any]]:
    """Rule 3. Keep the first occurrence of each key, preserving order."""
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_depuration.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/depuration.py backend/tests/test_depuration.py
git commit -m "Add depuration helpers: type resolution, naming, dedupe"
```

---

### Task 5: Editorial schemas and the structure route

**Files:**
- Modify: `backend/app/schemas.py` (add after `Evidence`; extend `CoreSample`)
- Create: `backend/app/agents/editorial.py`
- Test: `backend/tests/test_editorial_structure.py` (create)

**Interfaces:**
- Consumes: `Evidence` (Task 2).
- Produces: `OwnershipChapter`, `StructureRoute`, `Coverage`, `EditorialSample`; `CoreSample.editorial: EditorialSample | None = None`; and `build_structure(layers: list[Layer], evidence_by_entity: dict[str, list[Evidence]]) -> StructureRoute`. Tasks 6 and 7 consume the schemas.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_editorial_structure.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_editorial_structure.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agents.editorial'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/schemas.py`, after `Evidence`:

```python
EditorialStatus = Literal["evidenced", "partial", "not_found"]


class OwnershipChapter(BaseModel):
    """A normalised Layer. Not new research."""

    step: int
    entity: str
    entity_kind: EntityKind = EntityKind.unknown
    relationship: str | None = None
    country: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Ending(BaseModel):
    kind: EntityKind
    name: str


class StructureRoute(BaseModel):
    status: EditorialStatus = "not_found"
    chapters: list[OwnershipChapter] = Field(default_factory=list)
    ending: Ending | None = None


class Coverage(BaseModel):
    searched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    source_count: int = 0


class EditorialSample(BaseModel):
    """The only thing the front end consumes. Raw collections stay on
    CoreSample for debugging and replay."""

    structure: StructureRoute = Field(default_factory=StructureRoute)
    conduct: list[ConductPath] = Field(default_factory=list)
    public_records: list[RecordCard] = Field(default_factory=list)
    brands: list[BrandGroup] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
```

`ConductPath`, `RecordCard` and `BrandGroup` are defined in Task 6; add them there before `EditorialSample` compiles. To keep this task runnable on its own, temporarily declare them above `EditorialSample`:

```python
class ConductPath(BaseModel):
    """Filled in by Task 6."""
    id: str
    status: EditorialStatus = "not_found"


class RecordCard(BaseModel):
    """Filled in by Task 6."""
    title: str


class BrandGroup(BaseModel):
    """Filled in by Task 6."""
    owner: str
```

Extend `CoreSample` with one additive field:

```python
    editorial: EditorialSample | None = Field(
        None, description="The presentation model. The raw collections above are debug data.")
```

Create `backend/app/agents/editorial.py`:

```python
"""Assembling the editorial routes.

This module selects, orders and labels. It never writes a claim: every string a
reader sees arrives inside an Evidence object produced by the enricher.
"""
from __future__ import annotations

from ..schemas import (Ending, Evidence, EntityKind, Layer, OwnershipChapter,
                       StructureRoute)


def build_structure(layers: list[Layer],
                    evidence_by_entity: dict[str, list[Evidence]]) -> StructureRoute:
    """Rules 1-4 of the structure route.

    A chapter is only `evidenced` when it has a public document URL. Because
    ownership currently arrives via knowledge/query, which returns none, the
    honest answer today is usually `partial` — that is the designed behaviour,
    not a bug.
    """
    if not layers:
        return StructureRoute(status="not_found")

    chapters = [
        OwnershipChapter(
            step=layer.index,
            entity=layer.name,
            entity_kind=layer.kind,
            relationship=layer.relationship or None,
            country=layer.country or None,
            evidence=evidence_by_entity.get(layer.name, []),
        )
        for layer in layers  # rule 1: preserve Cala's order
    ]

    terminal = next((l for l in layers if l.terminal), None)
    ending = (Ending(kind=terminal.kind, name=terminal.name)
              if terminal and terminal.kind in {EntityKind.person, EntityKind.family}
              else None)

    all_cited = all(any(e.is_citable for e in c.evidence) for c in chapters)
    status = "evidenced" if (all_cited and ending is not None) else "partial"
    return StructureRoute(status=status, chapters=chapters, ending=ending)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_editorial_structure.py -q`
Expected: 5 passed

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass. `CoreSample.editorial` defaults to `None`, so existing contract tests are unaffected.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/agents/editorial.py \
        backend/tests/test_editorial_structure.py
git commit -m "Add editorial schemas and the structure route"
```

---

### Task 6: The conduct route

**Files:**
- Modify: `backend/app/schemas.py` (replace the three placeholder classes from Task 5)
- Modify: `backend/app/agents/editorial.py` (append)
- Test: `backend/tests/test_editorial_conduct.py` (create)

**Interfaces:**
- Consumes: `Evidence` (Task 2), `EditorialStatus` (Task 5).
- Produces: `ConductChapter`, `ConductPath`, `RecordCard`, `BrandGroup`; and `build_conduct(candidates: list[dict]) -> list[ConductPath]` where each candidate is `{"id": str, "topic": str, "scope": str, "chapters": [{"role": str, "evidence": list[Evidence]}]}`. Task 7 consumes `build_conduct`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_editorial_conduct.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_editorial_conduct.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_conduct'`

- [ ] **Step 3: Write minimal implementation**

Replace the three placeholder classes in `backend/app/schemas.py`:

```python
ConductRole = Literal["product_link", "commercial_link", "documented_impact", "response"]


class ConductChapter(BaseModel):
    role: ConductRole
    claim: str
    evidence: list[Evidence] = Field(default_factory=list)


class ConductPath(BaseModel):
    """The minimum safe unit for the second door: a product connection and a
    documented event. `response` is optional and never implies resolution."""

    id: str
    status: EditorialStatus = "not_found"
    topic: Literal["labor", "environment", "health", "regulatory", "legal"] = "legal"
    scope: Scope = "product"
    chapters: list[ConductChapter] = Field(default_factory=list)


class RecordCard(BaseModel):
    """A relevant public record that cannot form a complete conduct path.
    A title-only flag is not eligible."""

    title: str
    scope: Scope = "brand"
    date: str | None = None
    summary: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class BrandGroup(BaseModel):
    owner: str
    count: int = 0
    sample: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
```

Append to `backend/app/agents/editorial.py`:

```python
from ..schemas import ConductChapter, ConductPath

ROLE_ORDER = ["product_link", "commercial_link", "documented_impact", "response"]
REQUIRED_ROLES = {"product_link", "commercial_link", "documented_impact"}


def _cited(evidence: list[Evidence]) -> bool:
    return any(e.is_citable for e in evidence)


def build_conduct(candidates: list[dict]) -> list[ConductPath]:
    """Assemble and rank conduct paths.

    Ordering is completeness, then impact recency, then source count — never
    moral severity. Bedrock reports what is filed and lets the reader decide.
    """
    paths: list[ConductPath] = []
    for cand in candidates:
        chapters = [
            ConductChapter(role=ch["role"],
                           claim=ch["evidence"][0].claim if ch.get("evidence") else "",
                           evidence=ch.get("evidence", []))
            for ch in sorted(cand.get("chapters", []),
                             key=lambda c: ROLE_ORDER.index(c["role"]))
        ]
        present = {c.role for c in chapters}
        complete = REQUIRED_ROLES.issubset(present) and all(
            _cited(c.evidence) for c in chapters if c.role in REQUIRED_ROLES)
        paths.append(ConductPath(
            id=cand["id"], topic=cand.get("topic", "legal"),
            scope=cand.get("scope", "product"),
            status="evidenced" if complete else ("partial" if chapters else "not_found"),
            chapters=chapters,
        ))

    def rank(p: ConductPath) -> tuple:
        impact = next((c for c in p.chapters if c.role == "documented_impact"), None)
        date = max((e.date or "" for e in impact.evidence), default="") if impact else ""
        sources = sum(len(e.sources) for c in p.chapters for e in c.evidence)
        return (0 if p.status == "evidenced" else 1, _neg_str(date), -sources)

    return sorted(paths, key=rank)


def _neg_str(date: str) -> tuple:
    """Sort dates descending inside an ascending sort key."""
    return tuple(-ord(ch) for ch in date.ljust(10))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_editorial_conduct.py -q`
Expected: 5 passed

- [ ] **Step 5: Run the whole suite**

Run: `./.venv/bin/pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/agents/editorial.py \
        backend/tests/test_editorial_conduct.py
git commit -m "Add the conduct route with evidence-based ordering"
```

---

### Task 7: Assemble `editorial` and wire it into the sample

**Files:**
- Modify: `backend/app/agents/editorial.py` (append `build_editorial`)
- Modify: `backend/app/agents/extractor.py:29-90` (call it inside `build`)
- Modify: `docs/API.md` (document the field)
- Test: `backend/tests/test_editorial_assembly.py` (create)

**Interfaces:**
- Consumes: `build_structure` (Task 5), `build_conduct` (Task 6), depuration helpers (Task 4).
- Produces: `build_editorial(*, layers, supply, flags, siblings, gaps, subject_name, evidence_by_entity, conduct_candidates) -> EditorialSample`, and `CoreSample.editorial` populated.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_editorial_assembly.py
"""Acceptance rules from docs/EXTRACTOR_OUTPUT.md."""
from app.agents.editorial import build_editorial
from app.schemas import Flag, Source


def _flag(title):
    return Flag(kind="litigation", title=title,
                source=Source(query="q", latency_s=1.0))


def test_the_subject_is_absent_from_its_own_sibling_list():
    """Rule 2, and an explicit line in the Nutella acceptance test."""
    ed = build_editorial(layers=[], supply=[], flags=[], gaps=[],
                         siblings=["Nutella", "Kinder", "Tic Tac"],
                         subject_name="Nutella", evidence_by_entity={},
                         conduct_candidates=[])
    assert "Nutella" not in ed.brands[0].sample
    assert ed.brands[0].count == 2


def test_a_title_only_record_is_not_eligible():
    """A RecordCard needs a public source URL; a bare flag title does not qualify."""
    ed = build_editorial(layers=[], supply=[], flags=[_flag("record")], gaps=[],
                         siblings=[], subject_name="Nutella",
                         evidence_by_entity={}, conduct_candidates=[])
    assert ed.public_records == []


def test_coverage_names_what_is_missing_instead_of_showing_an_empty_card():
    ed = build_editorial(layers=[], supply=[], flags=[], gaps=[], siblings=[],
                         subject_name="Nutella", evidence_by_entity={},
                         conduct_candidates=[])
    assert "ownership" in ed.coverage.missing
    assert ed.coverage.source_count == 0


def test_the_main_story_is_capped_without_hiding_overflow():
    """Rule 8: at most two conduct paths and three public records."""
    cands = [{"id": f"c{i}", "topic": "labor", "scope": "supply_chain", "chapters": []}
             for i in range(5)]
    ed = build_editorial(layers=[], supply=[], flags=[], gaps=[], siblings=[],
                         subject_name="X", evidence_by_entity={},
                         conduct_candidates=cands)
    assert len(ed.conduct) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest tests/test_editorial_assembly.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_editorial'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/agents/editorial.py`:

```python
from ..schemas import BrandGroup, Coverage, EditorialSample, RecordCard
from .depuration import normalise_name

MAX_CONDUCT = 2
MAX_RECORDS = 3


def build_editorial(*, layers, supply, flags, gaps, siblings, subject_name,
                    evidence_by_entity, conduct_candidates) -> EditorialSample:
    """Fold the crew's findings into the presentation model.

    Everything here selects, filters and counts. Anything a reader will see as a
    sentence arrived as Evidence from the enricher.
    """
    structure = build_structure(layers, evidence_by_entity)
    conduct = build_conduct(conduct_candidates)[:MAX_CONDUCT]

    # Rule 4: a record needs a citable claim. A bare flag title is not one.
    records = [
        RecordCard(title=f.title, scope="brand",
                   summary=f.summary, evidence=evidence_by_entity.get(f.title, []))
        for f in flags
        if any(e.is_citable for e in evidence_by_entity.get(f.title, []))
    ][:MAX_RECORDS]

    # Rule 2: drop a sibling whose normalised name equals the subject.
    subject_key = normalise_name(subject_name)
    kin = [b for b in siblings if normalise_name(b) != subject_key]
    owner = layers[-1].name if layers else subject_name
    brands = [BrandGroup(owner=owner, count=len(kin), sample=kin[:12])] if kin else []

    searched, missing = [], []
    (searched if layers else missing).append("ownership")
    (searched if supply else missing).append("supply")
    (searched if records else missing).append("public_records")
    (searched if kin else missing).append("brands")

    source_count = len({
        s.url for evs in evidence_by_entity.values() for e in evs
        for s in e.sources if s.url
    })

    return EditorialSample(
        structure=structure, conduct=conduct, public_records=records,
        brands=brands, gaps=list(gaps),
        coverage=Coverage(searched=searched, missing=missing,
                          source_count=source_count),
    )
```

In `backend/app/agents/extractor.py`, import it and populate the field. Add to the imports:

```python
from .editorial import build_editorial
```

and inside `build`, just before `return CoreSample(`:

```python
        editorial = build_editorial(
            layers=layers, supply=supply, flags=flags, gaps=gaps,
            siblings=siblings, subject_name=subject.resolved_name,
            evidence_by_entity=evidence_by_entity or {},
            conduct_candidates=conduct_candidates or [],
        )
```

Add the two new keyword-only parameters to `build`'s signature, both defaulting to `None` so every existing caller and test keeps working:

```python
              models: dict[str, str],
              evidence_by_entity: dict | None = None,
              conduct_candidates: list | None = None) -> CoreSample:
```

and pass `editorial=editorial` to the `CoreSample(...)` constructor.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest tests/test_editorial_assembly.py -q`
Expected: 4 passed

- [ ] **Step 5: Run the whole suite and regenerate the schema**

Run: `./.venv/bin/pytest -q && ./.venv/bin/python -c "from app.main import app; app.openapi(); print('openapi ok')"`
Expected: all pass, `openapi ok`

- [ ] **Step 6: Document the field in `docs/API.md`**

Add to the `CoreSample` block, after `"meta"`, and note that the raw collections remain for debugging while `editorial` is what the front end consumes. Point at `docs/examples/editorial-nutella.json` as the filled reference.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/editorial.py backend/app/agents/extractor.py \
        backend/tests/test_editorial_assembly.py docs/API.md
git commit -m "Assemble the editorial sample and put it on CoreSample"
```

---

## Not in this plan

- **Wiring the enricher into the orchestrator.** Task 3 builds it and Task 7 accepts its output, but deciding which claims are worth an extra `knowledge/search` round trip is a latency budget question, and Cala rate-limits at roughly six rapid calls. Do it as a separate change once the shape is proven.
- **Statute filtering.** The spec asks for regulations to be dropped unless they govern the resolved product category. Left out because the current statute rows carry no category to filter on; it needs a probe change first.
- **The front end.** It builds against `docs/examples/editorial-nutella.json` and does not wait for this plan.
