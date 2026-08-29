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
