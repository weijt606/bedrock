"""A beat should carry the documents the enricher found for the entity it is about.

The enrichment pass already runs: `_editorial` asks knowledge/search per hop and
the URLs land on `editorial.structure.chapters[].evidence`. But `story[]` — the
thing the interface actually renders — was built from knowledge/query sources,
which never carry a URL. So the reader saw the query we asked instead of the
publisher, on every beat, for every product.

These pin the join: chapter evidence, matched to a beat by `Beat.entities`.
"""
from app.agents.extractor import attach_documents
from app.schemas import (Beat, EditorialRoutes, Evidence, EvidenceSource,
                         OwnershipChapter, Source, StructureRoute)

GUARDIAN = "https://www.theguardian.com/a"
REUTERS = "https://reuters.com/b"


def _routes(*pairs):
    return EditorialRoutes(structure=StructureRoute(
        status="partial",
        chapters=[OwnershipChapter(step=i + 1, entity=name, evidence=[
            Evidence(claim="c", scope="parent",
                     sources=[EvidenceSource(publisher="P", url=url, query="q")])
        ]) for i, (name, url) in enumerate(pairs)]))


def _beat(entities, docs=()):
    return Beat(kind="handover", headline="h", entities=list(entities),
                source=Source(query="Ferrero Group.shareholders", latency_s=1.0,
                              documents=list(docs)))


def test_a_beat_gains_the_documents_found_for_its_entity():
    story = [_beat(["Ferrero Group"])]
    attach_documents(story, _routes(("Ferrero Group", GUARDIAN)))
    assert story[0].source.documents == [GUARDIAN]


def test_a_beat_about_two_entities_gains_both():
    story = [_beat(["Nutella", "Ferrero Group"])]
    attach_documents(story, _routes(("Nutella", REUTERS), ("Ferrero Group", GUARDIAN)))
    assert story[0].source.documents == [REUTERS, GUARDIAN]


def test_documents_already_present_are_kept_and_not_duplicated():
    story = [_beat(["Ferrero Group"], docs=[GUARDIAN])]
    attach_documents(story, _routes(("Ferrero Group", GUARDIAN)))
    assert story[0].source.documents == [GUARDIAN]


def test_a_beat_about_nobody_in_the_chain_is_left_alone():
    """No invented citation. A beat with no matching entity keeps its query."""
    story = [_beat(["Someone Else"])]
    attach_documents(story, _routes(("Ferrero Group", GUARDIAN)))
    assert story[0].source.documents == []


def test_no_editorial_is_a_no_op():
    story = [_beat(["Ferrero Group"])]
    attach_documents(story, None)
    assert story[0].source.documents == []


def test_a_beat_without_a_source_is_skipped_rather_than_crashing():
    story = [Beat(kind="scale", headline="h", entities=["Ferrero Group"])]
    attach_documents(story, _routes(("Ferrero Group", GUARDIAN)))
    assert story[0].source is None
