"""Assembling the editorial routes.

This module selects, orders and labels. It never writes a claim: every string a
reader sees arrives inside an Evidence object produced by the enricher.
"""
from __future__ import annotations

from ..schemas import (BrandGroup, ConductChapter, ConductPath, Coverage,
                       EditorialSample,
                       Ending, EntityKind, Evidence, Layer, OwnershipChapter,
                       StructureRoute)
from .depuration import normalise_name


MAX_CONDUCT = 2


MAX_RECORDS = 3


def build_structure(layers: list[Layer],
                    evidence_by_entity: dict[str, list[Evidence]]) -> StructureRoute:
    """Rules 1-4 of the structure route.

    A chapter is only `evidenced` when it has a public document URL. Because
    ownership currently arrives via knowledge/query, which returns none, the
    honest answer today is usually `partial` — that is the designed behaviour,
    not a bug, and the front end must render it as well as it renders success.
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


# --------------------------------------------------------------------------- #
#  conduct
# --------------------------------------------------------------------------- #

ROLE_ORDER = ["product_link", "commercial_link", "documented_impact", "response"]
REQUIRED_ROLES = {"product_link", "commercial_link", "documented_impact"}


def _cited(evidence: list[Evidence]) -> bool:
    return any(e.is_citable for e in evidence)


def _recency_key(date: str) -> tuple:
    """Sort dates descending inside an ascending sort key."""
    return tuple(-ord(ch) for ch in date.ljust(10))


def build_conduct(candidates: list[dict]) -> list[ConductPath]:
    """Assemble and rank conduct paths.

    Ordering is completeness, then impact recency, then source count — never
    moral severity. Bedrock reports what is filed and lets the reader decide;
    ranking companies by how bad we think they are is the line the project
    does not cross.
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
        return (0 if p.status == "evidenced" else 1, _recency_key(date), -sources)

    return sorted(paths, key=rank)


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
        RecordCard(title=f.title, scope="brand", summary=f.summary,
                   evidence=evidence_by_entity.get(f.title, []))
        for f in flags
        if any(e.is_citable for e in evidence_by_entity.get(f.title, []))
    ][:MAX_RECORDS]

    # Rule 2: drop a sibling whose normalised name equals the subject. A product
    # listed among its own siblings reads as a bug to everyone who sees it.
    subject_key = normalise_name(subject_name)
    kin = [b for b in siblings if normalise_name(b) != subject_key]
    owner = layers[-1].name if layers else subject_name
    brands = [BrandGroup(owner=owner, count=len(kin), sample=kin[:12])] if kin else []

    searched: list[str] = []
    missing: list[str] = []
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
