#!/usr/bin/env python3
"""Find out what GLiNER2 actually accepts and returns.

Pioneer's docs say a `schema` may carry `entities`, `classifications`,
`structures` and `relations`, but only the first two are specified. `relations`
is the one we want most — Bedrock is extracting *ownership relations*, not just
spans, and a model that returns `(Freixenet) --owned_by--> (Henkell & Co.)`
gives us the chain directly instead of a bag of names to re-link.

Rather than guess at an undocumented shape, this probes candidate shapes against
the live API and reports which one it accepts. Run it once after the account is
unblocked; it costs a handful of tiny calls.

    export PIONEER_API_KEY=...
    python scripts/probe_schema.py

It also dumps a full response for the shapes that do work, so
`app/clients/pioneer._parse_entities` can be matched to reality instead of to a
defensive guess.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

TEXT = ("Freixenet S.A., the Spanish cava producer founded in 1928, is ultimately "
        "owned by the Oetker family. Henkell & Co. Sektkellerei KG, based in "
        "Wiesbaden, Germany, is the direct parent and acquired a 50.67% stake in 2018.")

MODEL = "fastino/gliner2-large-v1"
ENTS = ["company", "person", "family", "jurisdiction", "stake", "date"]

CANDIDATES: list[tuple[str, dict[str, Any]]] = [
    ("entities only", {"entities": ENTS}),
    ("entities + classifications", {
        "entities": ENTS,
        "classifications": [{"task": "chain_position",
                             "labels": ["ultimate_parent", "direct_parent", "shareholder"]}],
    }),
    # relations, shape A — list of {name, subject, object}
    ("relations A: name/subject/object", {
        "entities": ENTS,
        "relations": [{"name": "owned_by", "subject": "company", "object": "company"},
                      {"name": "parent_of", "subject": "company", "object": "company"}],
    }),
    # shape B — list of {relation, source, target}
    ("relations B: relation/source/target", {
        "entities": ENTS,
        "relations": [{"relation": "owned_by", "source": "company", "target": "company"}],
    }),
    # shape C — bare list of labels, like entities
    ("relations C: bare labels", {"entities": ENTS, "relations": ["owned_by", "parent_of"]}),
    # shape D — {label, head, tail}
    ("relations D: label/head/tail", {
        "entities": ENTS,
        "relations": [{"label": "owned_by", "head": "company", "tail": "company"}],
    }),
    # structures — JSON extraction
    ("structures: named fields", {
        "structures": {"ownership": {"owner": "string", "parent": "string",
                                     "stake": "string", "jurisdiction": "string"}},
    }),
]


def call(schema: dict[str, Any]) -> tuple[int, Any]:
    try:
        r = httpx.post(
            f"{settings.pioneer_base}/inference",
            json={"model_id": MODEL, "text": TEXT, "schema": schema, "threshold": 0.4},
            headers={"X-API-Key": settings.pioneer_key,
                     "Content-Type": "application/json"},
            timeout=60.0)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text[:400]
    except Exception as exc:
        return 0, str(exc)[:200]


def main() -> None:
    if not settings.pioneer_key:
        sys.exit("PIONEER_API_KEY is not set")

    out: dict[str, Any] = {}
    for label, schema in CANDIDATES:
        code, body = call(schema)
        ok = code == 200
        print(f"\n{'=' * 78}\n{label:38} -> {code} {'OK' if ok else 'REJECTED'}")
        print(json.dumps(body, ensure_ascii=False, indent=1)[:1400])
        out[label] = {"status": code, "schema": schema, "body": body}

    dest = pathlib.Path("datasets/schema_probe.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1))

    accepted = [k for k, v in out.items() if v["status"] == 200]
    print(f"\n{'=' * 78}\naccepted: {accepted or 'none'}")
    print(f"wrote {dest}")
    print("\nIf a relations shape came back 200 with populated output, wire it into "
          "READER_SCHEMA in app/clients/pioneer.py — the reader then gets the "
          "ownership chain directly instead of a bag of names to re-link.")


if __name__ == "__main__":
    main()
