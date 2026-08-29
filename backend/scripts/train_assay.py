#!/usr/bin/env python3
"""Train the assay model.

The assay decides one thing: given a row from a corporate registry, is this a
company, a person, a family, a fund or a foundation — and does the ownership
chain stop here. Getting it wrong is expensive in both directions: call a company
a person and the dig ends one hop in; call a person a company and it never ends.

This script builds a specialist for that job on Pioneer:

    seed      collect real rows from our own Cala cache          (free, honest)
    generate  ask Pioneer to synthesise more of the same shape   POST /generate
    train     LoRA on a GLiNER2 encoder                          POST /felix/training-jobs
    evaluate  F1 / precision / recall against held-out labels    POST /felix/evaluations

Usage
    export PIONEER_API_KEY=...
    python scripts/train_assay.py seed          # dump what we already have
    python scripts/train_assay.py generate      # synthesise a dataset
    python scripts/train_assay.py train
    python scripts/train_assay.py status job_abc123
    python scripts/train_assay.py evaluate job_abc123
    python scripts/train_assay.py models        # what the account can serve

Then put the finished job id in .env:

    MODEL_ASSAY=job_abc123

Nothing here runs at request time. Inference stays on the fast path in
app/clients/pioneer.py.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Any

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.clients.pioneer import KINDS, row_text  # noqa: E402

BASE = os.environ.get("PIONEER_BASE", "https://api.pioneer.ai")
KEY = os.environ.get("PIONEER_API_KEY", "")
DATASET = os.environ.get("ASSAY_DATASET", "bedrock-registry-rows")
BASE_MODEL = os.environ.get("ASSAY_BASE_MODEL", "fastino/gliner2-base-v1")
CACHE = pathlib.Path(os.environ.get("CACHE_DIR", ".cache"))
SEED_OUT = pathlib.Path("datasets/registry_rows.jsonl")

H = {"X-API-Key": KEY, "Content-Type": "application/json"}


def _need_key() -> None:
    if not KEY:
        sys.exit("PIONEER_API_KEY is not set. Create one at https://app.pioneer.ai/api-keys")


def _post(path: str, body: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
    r = httpx.post(f"{BASE}{path}", json=body, headers=H, timeout=timeout)
    if r.status_code >= 400:
        sys.exit(f"{r.status_code} {path}\n{r.text[:600]}")
    return r.json()


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    r = httpx.get(f"{BASE}{path}", params=params, headers=H, timeout=60.0)
    if r.status_code >= 400:
        sys.exit(f"{r.status_code} {path}\n{r.text[:600]}")
    return r.json()


# --------------------------------------------------------------------------- #
#  seed — real rows we already paid for
# --------------------------------------------------------------------------- #

def cmd_seed() -> None:
    """Harvest ownership rows out of the Cala cache into a labelling sheet.

    These are real answers to real questions, already on disk. Label the
    `kind` column by hand where the weak label looks wrong — a few hundred rows
    of genuine registry output beats a large synthetic set.
    """
    from app.clients.pioneer import _heuristic

    rows: list[dict[str, Any]] = []
    for f in sorted(CACHE.glob("query-*.json")):
        try:
            payload = json.loads(f.read_text()).get("payload") or {}
        except Exception:
            continue
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            name = (row.get("owner") or row.get("name") or row.get("shareholder")
                    or row.get("ultimate_owner") or "").strip()
            if not name:
                continue
            weak = _heuristic(name, row)
            rows.append({
                "text": row_text(name, row),
                "entity_kind": weak["kind"],          # weak label — review before training
                "chain_terminates": "yes" if weak["terminal"] else "no",
                "_confidence": weak["confidence"],
            })

    seen, uniq = set(), []
    for r in rows:
        if r["text"] not in seen:
            seen.add(r["text"])
            uniq.append(r)

    SEED_OUT.parent.mkdir(parents=True, exist_ok=True)
    with SEED_OUT.open("w") as fh:
        for r in uniq:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    unsure = sum(1 for r in uniq if r["entity_kind"] == "unknown" or r["_confidence"] < 0.7)
    print(f"wrote {len(uniq)} rows -> {SEED_OUT}")
    print(f"{unsure} are low confidence or unknown — those are the ones worth "
          f"labelling by hand, they are exactly what the model is for")


# --------------------------------------------------------------------------- #
#  generate / train / evaluate
# --------------------------------------------------------------------------- #

def cmd_generate(n: int = 400) -> None:
    _need_key()
    job = _post("/generate", {
        "task_type": "classification",
        "dataset_name": DATASET,
        "labels": KINDS,
        "num_examples": n,
        "domain_description": (
            "Single rows from European corporate share registers and ownership "
            "filings. Each row names one shareholder or parent and may carry a role, "
            "a stake percentage or a registered address. Names include operating "
            "companies with legal suffixes (S.A., B.V., GmbH, KG, S.L.), holding "
            "companies, family offices, foundations and private individuals. Include "
            "hard cases where a company name looks like a person's name because it "
            "is derived from the founding family — for example 'Perfetti Van Melle', "
            "'Dr. August Oetker KG', 'Casa Tarradellas' — and individuals whose rows "
            "carry an explicit role or stake."
        ),
    })
    job_id = job.get("job_id") or job.get("id")
    print(f"generation job {job_id} -> {job.get('status')}")
    _poll(f"/generate/jobs/{job_id}")


def cmd_train() -> None:
    _need_key()
    job = _post("/felix/training-jobs", {
        "base_model": BASE_MODEL,
        "model_name": "bedrock-assay",
        "datasets": [{"name": DATASET}],
        "training_type": "lora",
        "nr_epochs": 5,
        "learning_rate": 5e-5,
    })
    job_id = job.get("id")
    print(f"training job {job_id} -> {job.get('status')}")
    print(f"poll: python scripts/train_assay.py status {job_id}")


def cmd_status(job_id: str) -> None:
    _need_key()
    body = _poll(f"/felix/training-jobs/{job_id}")
    if (body or {}).get("metrics"):
        m = body["metrics"]
        print(f"\n  f1={m.get('f1')}  precision={m.get('precision')}  recall={m.get('recall')}")
        print(f"\nPut this in .env:\n  MODEL_ASSAY={job_id}")


def cmd_evaluate(job_id: str) -> None:
    _need_key()
    body = _post("/felix/evaluations", {"model_id": job_id, "dataset": {"name": DATASET}})
    print(json.dumps(body, indent=2)[:1200])


def cmd_models() -> None:
    _need_key()
    body = _get("/base-models", {"supports_inference": "true"})
    models = body if isinstance(body, list) else body.get("models", [])
    for m in models:
        if isinstance(m, dict):
            print(f"  {m.get('id') or m.get('name'):48} {m.get('type') or m.get('family') or ''}")
        else:
            print(f"  {m}")


def _poll(path: str, every: float = 10.0, cap: float = 1800.0) -> dict[str, Any] | None:
    t0 = time.time()
    while time.time() - t0 < cap:
        body = _get(path)
        status = (body or {}).get("status", "?")
        print(f"  [{time.time()-t0:6.0f}s] {status}", flush=True)
        if status in ("complete", "completed", "succeeded", "failed", "error", "cancelled"):
            return body
        time.sleep(every)
    print("  gave up waiting; the job keeps running server-side")
    return None


COMMANDS = {"seed": cmd_seed, "generate": cmd_generate, "train": cmd_train,
            "status": cmd_status, "evaluate": cmd_evaluate, "models": cmd_models}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: train_assay.py [{' | '.join(COMMANDS)}]")
    fn = COMMANDS[sys.argv[1]]
    fn(*sys.argv[2:])  # type: ignore[operator]
