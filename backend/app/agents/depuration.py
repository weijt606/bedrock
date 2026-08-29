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

# Legal form only. "Group", "Holdings" and the like are part of how a company
# is actually named and calling them suffixes would merge "Ferrero Group" into
# "Ferrero", which are different entities in an ownership chain.
_SUFFIXES = (
    "spa", "sa", "nv", "bv", "gmbh", "ag", "plc", "ltd", "limited",
    "llc", "inc", "corp", "corporation", "co", "pty", "llp", "lp",
    # The chains this walks are mostly European and mostly German-speaking at the
    # top: Henkell & Co. Sektkellerei KG, Dr. August Oetker KG. Without these a
    # company matches nothing one hop above itself.
    "kg", "kgaa", "ohg", "se", "sarl", "sas", "srl", "bvba", "aps", "oyj",
)


def normalise_name(name: str) -> str:
    """Lower-case, strip accents, punctuation and legal suffixes."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    # Drop the dots first, so "S.p.A." collapses to one token and can be matched
    # as a suffix. Removing punctuation first would shatter it into "s p a".
    s = s.replace(".", "")
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
