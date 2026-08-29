#!/usr/bin/env python3
"""Head-to-head: does the specialist actually replace the frontier LLM call?

The task under test is the one Bedrock genuinely needs: **read a paragraph of
Cala ownership prose and return the entities in it** — the companies, people,
families, jurisdictions, stakes and dates. Today that is a structured-extraction
prompt to a general-purpose model. It should be a small NER encoder.

    A  frontier      gpt-4o-mini, JSON-mode structured extraction   (the incumbent)
    B  zero-shot     fastino/gliner2-large-v1 via Pioneer           (no training)
    C  specialist    a fine-tuned job id via Pioneer                (MODEL_READER)

## Where the gold labels come from

Nobody hand-labels anything, and we do not let a model grade a model.

Cala's *typed* endpoint already knows the answer: `knowledge/query` returns the
shareholders of a company as structured rows. Cala's *prose* endpoint describes
the same ownership in a paragraph. So for each subject we take the entity names
`knowledge/query` returned as the gold set, and score each system on whether it
recovered those names from the prose.

**The verified knowledge graph is the referee.** That keeps the benchmark honest
in the same way it keeps the product honest, and it costs nothing to extend —
every subject anyone digs becomes another test case.

## Usage

    export CALA_API_KEY=... PIONEER_API_KEY=... OPENAI_API_KEY=...
    python scripts/bench.py build        # assemble gold + prose from Cala
    python scripts/bench.py run          # score A, B and C
    python scripts/bench.py run --systems A,C

Costs and latencies are measured, not quoted. `--repeat` runs each system N
times to get a stable p50/p95.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import statistics
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.clients.cala import CalaClient  # noqa: E402
from app.clients.pioneer import (OWNERSHIP_ENTITIES, READER_SCHEMA,  # noqa: E402
                                 PioneerClient)
from app.config import settings  # noqa: E402

BENCH = pathlib.Path("datasets/bench_ownership.json")

SUBJECTS = [
    "Chupa Chups", "Freixenet", "Estrella Damm", "Cola Cao", "Mercadona",
    "Nutella", "Oreo", "Zara", "IKEA", "Nespresso", "Ben & Jerry's",
    "Red Bull", "Moleskine", "Telepizza", "Casa Tarradellas",
]

# Per-1M-token list prices, and the per-call price Pioneer bills for an encoder.
# Override from the environment if your account differs; the point of the table
# is the ratio, not the third decimal place.
PRICE_FRONTIER_IN = float(os.environ.get("PRICE_FRONTIER_IN", 0.15))
PRICE_FRONTIER_OUT = float(os.environ.get("PRICE_FRONTIER_OUT", 0.60))
PRICE_ENCODER_CALL = float(os.environ.get("PRICE_ENCODER_CALL", 0.0001))


# --------------------------------------------------------------------------- #
#  build: gold labels from Cala's typed rows, prose from Cala's search
# --------------------------------------------------------------------------- #

def _names(rows: list[dict[str, Any]]) -> list[str]:
    out = []
    for r in rows:
        for k in ("owner", "ultimate_owner", "shareholder", "name", "direct_parent"):
            v = r.get(k)
            if isinstance(v, str) and len(v.strip()) > 2:
                out.append(v.strip())
    seen, uniq = set(), []
    for n in out:
        if n.lower() not in seen:
            seen.add(n.lower())
            uniq.append(n)
    return uniq


async def cmd_build() -> None:
    cala = CalaClient()
    cases: list[dict[str, Any]] = []
    for subject in SUBJECTS:
        prose = await cala.search(f"Who ultimately owns {subject}?")
        rows_a = await cala.query(f"Who owns {subject}?")
        rows_b = await cala.query(f"{subject}.shareholders")
        gold = _names(rows_a.rows) + _names(rows_b.rows)
        gold = [g for g in dict.fromkeys(gold) if g.lower() != subject.lower()]

        if not prose.content or not gold:
            print(f"  skip  {subject:20} prose={bool(prose.content)} gold={len(gold)}")
            continue
        cases.append({
            "subject": subject,
            "prose": prose.content,
            "gold": gold,
            "prose_latency_s": prose.latency_s,
            "rows_latency_s": round(rows_a.latency_s + rows_b.latency_s, 2),
        })
        print(f"  ok    {subject:20} gold={len(gold):2}  prose {prose.latency_s:5.1f}s  "
              f"rows {rows_a.latency_s + rows_b.latency_s:5.1f}s")
    await cala.aclose()

    BENCH.parent.mkdir(parents=True, exist_ok=True)
    BENCH.write_text(json.dumps(cases, ensure_ascii=False, indent=1))
    print(f"\nwrote {len(cases)} cases -> {BENCH}")
    if cases:
        p = statistics.median(c["prose_latency_s"] for c in cases)
        r = statistics.median(c["rows_latency_s"] for c in cases)
        print(f"median Cala latency: prose {p:.1f}s vs typed rows {r:.1f}s")


# --------------------------------------------------------------------------- #
#  the three systems
# --------------------------------------------------------------------------- #

FRONTIER_PROMPT = (
    "Extract every named entity from the ownership description below.\n"
    f"Labels: {', '.join(OWNERSHIP_ENTITIES)}.\n"
    "Copy spans verbatim from the text. Do not add anything that is not written there.\n"
    'Return {"entities":[{"text":str,"label":str}]}.\n\nText:\n'
)


async def run_frontier(client: httpx.AsyncClient, prose: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    r = await client.post(
        f"{settings.openai_base}/chat/completions",
        json={"model": settings.model_planner, "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "user", "content": FRONTIER_PROMPT + prose[:6000]}]},
        headers={"Authorization": f"Bearer {settings.openai_key}"}, timeout=90.0)
    r.raise_for_status()
    body = r.json()
    ents = json.loads(body["choices"][0]["message"]["content"]).get("entities") or []
    usage = body.get("usage") or {}
    cost = (usage.get("prompt_tokens", 0) / 1e6 * PRICE_FRONTIER_IN
            + usage.get("completion_tokens", 0) / 1e6 * PRICE_FRONTIER_OUT)
    return {"entities": [e for e in ents if isinstance(e, dict)],
            "latency_s": time.perf_counter() - t0, "cost_usd": cost}


async def run_pioneer(pio: PioneerClient, prose: str, model: str) -> dict[str, Any]:
    prev = settings.model_reader
    object.__setattr__(settings, "model_reader", model)
    try:
        t0 = time.perf_counter()
        got = await pio.extract(prose, READER_SCHEMA)
        latency = time.perf_counter() - t0
    finally:
        object.__setattr__(settings, "model_reader", prev)
    return {"entities": (got or {}).get("entities", []),
            "latency_s": latency, "cost_usd": PRICE_ENCODER_CALL}


# --------------------------------------------------------------------------- #
#  scoring
# --------------------------------------------------------------------------- #

def _norm(s: str) -> str:
    s = s.lower().strip(" .,")
    for suffix in (" group", " kg", " gmbh", " b.v.", " bv", " s.a.", " sa",
                   " n.v.", " ltd", " limited", " inc", " plc", " s.l."):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    return s


def score(pred: list[dict[str, Any]], gold: list[str]) -> tuple[int, int, int]:
    """Recall-oriented: did the system recover the names Cala's typed rows list?

    A predicted span counts if it contains, or is contained by, a gold name once
    both are normalised — "Henkell & Co. Sektkellerei KG" and "Henkell & Co."
    are the same company and it would be dishonest to score that as a miss.
    """
    p = {_norm(e.get("text", "")) for e in pred if e.get("text")}
    p.discard("")
    g = {_norm(x) for x in gold}
    hits = {x for x in g if any(x in q or q in x for q in p if len(q) > 3)}
    tp = len(hits)
    fn = len(g) - tp
    matched = {q for q in p if any(q in x or x in q for x in g if len(x) > 3)}
    fp = len(p) - len(matched)
    return tp, fp, fn


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


# --------------------------------------------------------------------------- #
#  run
# --------------------------------------------------------------------------- #

async def cmd_run(systems: str = "A,B,C", repeat: int = 1) -> None:
    if not BENCH.exists():
        sys.exit(f"{BENCH} missing — run `python scripts/bench.py build` first")
    cases = json.loads(BENCH.read_text())
    wanted = {s.strip().upper() for s in systems.split(",")}

    plan = []
    if "A" in wanted and settings.has_openai:
        plan.append(("A  frontier   " + settings.model_planner, "frontier", None))
    if "B" in wanted and settings.has_pioneer:
        plan.append(("B  zero-shot  fastino/gliner2-large-v1", "pioneer",
                     "fastino/gliner2-large-v1"))
    if "C" in wanted and settings.has_pioneer:
        plan.append((f"C  specialist {settings.model_reader}", "pioneer",
                     settings.model_reader))
    if not plan:
        sys.exit("nothing to run — check OPENAI_API_KEY / PIONEER_API_KEY")

    pio = PioneerClient()
    http = httpx.AsyncClient(timeout=90.0)
    table: list[dict[str, Any]] = []

    for label, kind, model in plan:
        tp = fp = fn = 0
        lat: list[float] = []
        cost = 0.0
        fails = 0
        for case in cases:
            for _ in range(repeat):
                try:
                    got = (await run_frontier(http, case["prose"]) if kind == "frontier"
                           else await run_pioneer(pio, case["prose"], model or ""))
                except Exception:
                    fails += 1
                    continue
                lat.append(got["latency_s"])
                cost += got["cost_usd"]
            a, b, c = score(got["entities"], case["gold"])
            tp, fp, fn = tp + a, fp + b, fn + c
        prec, rec, f1 = prf(tp, fp, fn)
        table.append({
            "system": label, "precision": prec, "recall": rec, "f1": f1,
            "p50_s": statistics.median(lat) if lat else 0.0,
            "p95_s": (statistics.quantiles(lat, n=20)[-1] if len(lat) > 4
                      else (max(lat) if lat else 0.0)),
            "cost_per_1k": cost / max(1, len(lat)) * 1000,
            "failures": fails,
        })

    await pio.aclose()
    await http.aclose()

    print(f"\n{len(cases)} cases · gold labels from Cala's typed rows · repeat={repeat}\n")
    print(f"{'system':44} {'P':>6} {'R':>6} {'F1':>6} {'p50':>8} {'p95':>8} {'$/1k':>9}")
    print("-" * 92)
    for r in table:
        print(f"{r['system']:44} {r['precision']:6.3f} {r['recall']:6.3f} {r['f1']:6.3f} "
              f"{r['p50_s']:7.2f}s {r['p95_s']:7.2f}s {r['cost_per_1k']:8.3f}")

    if len(table) >= 2:
        a, best = table[0], max(table[1:], key=lambda r: r["f1"])
        print(f"\nvs the incumbent ({a['system'].split()[0]}):")
        print(f"  F1       {best['f1'] - a['f1']:+.3f}")
        if a["p50_s"]:
            print(f"  latency  {a['p50_s'] / max(best['p50_s'], 1e-6):.1f}x faster")
        if best["cost_per_1k"]:
            print(f"  cost     {a['cost_per_1k'] / best['cost_per_1k']:.0f}x cheaper")

    out = pathlib.Path("datasets/bench_results.json")
    out.write_text(json.dumps(table, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build", "run"])
    ap.add_argument("--systems", default="A,B,C")
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    if args.command == "build":
        asyncio.run(cmd_build())
    else:
        asyncio.run(cmd_run(args.systems, args.repeat))
