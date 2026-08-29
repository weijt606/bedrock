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
