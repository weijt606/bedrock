"""Turning a planner's questions into corroborated questions.

An agent asks *questions*; Cala answers *phrasings*. Those are not the same
thing, and conflating them is how Bedrock ends up telling a reader that nobody
has published a fact when in truth we guessed the wrong key.

Measured on the live API:

    Estrella Damm.barley_supplier                   ->  0 rows
    Estrella Damm.raw_material_origin               ->  4 rows

So a "ladder" is one question expressed several ways. The agent walks it until
something answers, and only calls the record silent when every rung is empty.

The planner may return either shape:

    ["X.lawsuits", "X.recalls"]                     one question per string
    [["X.lawsuits", "What lawsuits has X faced?"]]  explicit ladders

Plain strings are expanded here so an older planner prompt keeps working and
still gets corroboration for free.
"""
from __future__ import annotations

from typing import Any, Sequence


def natural_language_variant(probe: str) -> str | None:
    """Rewrite `Subject.some_field` as a plain question.

    Purely mechanical — it re-punctuates the key the caller already chose and
    never invents a new subject or a new field.
    """
    if "." not in probe or probe.endswith("?"):
        return None
    subject, _, field = probe.partition(".")
    subject, field = subject.strip(), field.strip()
    if not subject or not field or "." in field:
        return None
    return f"What is the {field.replace('_', ' ')} of {subject}?"


def questions_to_ladders(questions: Sequence[Any] | None) -> list[list[str]]:
    """Normalise planner output into one ladder per question.

    Returns `[]` when there is nothing usable, so callers can fall back to their
    own static ladder with a plain `or`.
    """
    if not questions:
        return []
    ladders: list[list[str]] = []
    for item in questions:
        if isinstance(item, str):
            rungs = [item]
            extra = natural_language_variant(item)
            if extra:
                rungs.append(extra)
        elif isinstance(item, (list, tuple)):
            rungs = [q for q in item if isinstance(q, str) and q.strip()]
        else:
            continue
        # De-duplicate while preserving the planner's ordering.
        seen: set[str] = set()
        rungs = [q for q in rungs if not (q in seen or seen.add(q))]
        if rungs:
            ladders.append(rungs)
    return ladders
