# Bedrock

**One drill through everything behind the thing in your hand.**

Point Bedrock at a product — type it, photograph it, say it out loud — and it
excavates the layers underneath: who makes it, who owns the company that makes
it, who owns *that*, which laws govern what its label must declare, and what is
on the public record about any of them.

It stops when it reaches a human being. Usually that takes four steps and
crosses three borders.

> Chupa Chups → Perfetti Van Melle → Perfetti Van Melle Group B.V. →
> C+F Confectionery and Foods S.A., 10 Rue Henri M. Schnadt, L-2530 Luxembourg →
> Augusto and Giorgio Perfetti

---

## The one rule

**No language model ever states a fact.**

This is the architectural spine, not a slogan. Bedrock sits on top of
[Cala](https://cala.ai)'s verified entity graph, and the entire point of that
graph is that its facts are traceable. A system that then paraphrases those facts
through an LLM has thrown away the only thing that made them worth having.

So the roles are split, and the split is enforced by the type system:

| Component | Allowed to | Never allowed to |
|---|---|---|
| **Cala** | state facts, with sources | — |
| **OpenAI** | plan which questions to ask, reshape returned rows, read a brand name off a photograph | assert anything about a company |
| **Pioneer** | classify and score rows Cala returned, on a fine-tuned encoder | add a row |
| **fal** | transcribe speech to text | anything else |

Every user-visible claim in the response — `Layer`, `SupplyNode`, `Statute`,
`Flag` — carries a **required** `source: Source` field naming the exact Cala
query, the endpoint, the latency and the document URLs behind it. An agent
cannot emit an unsourced fact, because pydantic will not construct the object.

The corollary matters for the product too: Bedrock reports what is *filed* — a
lawsuit, a sanctions listing, a shareholding — and never scores a company or
calls it good or bad. "X is a defendant in Y" is a sourced fact. "X is unethical"
is an opinion, is defamatory if wrong, and is not something this system emits.

---

## Architecture

```
                       ┌───────────────────────────────────────────────┐
   text ──┐            │                ORCHESTRATOR                   │
  image ──┼──▶ INTAKE ─▶  plans the dig · fans out · enforces budgets   │
  audio ──┘   (vision   │                                               │
               / STT)   └───┬───────────┬───────────┬───────────┬───────┘
                            │           │           │           │
                   sequential           └─── concurrent ────────┘
                            │           │           │           │
                     ┌──────▼─────┐ ┌───▼────┐ ┌────▼─────┐ ┌───▼──────┐
                     │ PROSPECTOR │ │SURVEYOR│ │ STATUTE  │ │ RECORDER │
                     │  ownership │ │ supply │ │   law    │ │ filings  │
                     └──────┬─────┘ └───┬────┘ └────┬─────┘ └───┬──────┘
                            │           │           │           │
                            └───────────┴─────┬─────┴───────────┘
                                              │
                                      ┌───────▼────────┐
                                      │      CALA      │  ← every fact
                                      │ knowledge graph│
                                      └───────┬────────┘
                                              │ raw rows
                                      ┌───────▼────────┐
                                      │  ASSAY (Pioneer)│ ← kind, confidence,
                                      │  fine-tuned SLM │   chain termination
                                      └───────┬────────┘
                                              │
                                      ┌───────▼────────┐
                                      │   EXTRACTOR    │ → CoreSample + SSE
                                      └────────────────┘
```

**The crew**

| Agent | Job |
|---|---|
| `intake` | Any input becomes one `Subject`, resolved against Cala's entity index |
| `prospector` | Walks the ownership chain hop by hop until it reaches a person |
| `surveyor` | Manufacturers, co-packers, and which other brands use the same factory group |
| `statute` | The regulations that dictate what the label must declare |
| `recorder` | Litigation and sanctions listings, as filed |
| `reader` | Turns Cala's *prose* answers back into structured layers with GLiNER2 |
| `assay` | Pioneer's fine-tuned model classifies and scores every row |
| `extractor` | Folds everything into one `CoreSample` and computes the game numbers |

---

## Why it is built for latency

Measured against the live Cala API, over ~60 queries:

| | |
|---|---|
| Cold query | **16–75 s** (median ≈ 35 s) |
| The same query again | **≈ 0.5 s**, permanently |
| Rate limit | roughly six rapid calls before `429` |
| Rows per answer | 1–33, never more |

Four consequences shaped the whole backend:

1. **Streaming is mandatory.** `POST /v1/samples` returns immediately;
   `GET /v1/samples/{id}/events` streams every probe, layer and gap the instant
   it lands. The front end animates an excavation instead of showing a spinner.
2. **Only the ownership chain is sequential** — hop *N+1* is a question about
   hop *N*'s answer. Supply, statute and public-record probes have no such
   dependency and are fanned out with `asyncio.gather`, racing the chain.
3. **The cache is the product.** Answers are written to disk and never expire, so
   every dig anyone runs makes the next person's dig instant. Warm before a demo
   with `POST /v1/samples:sync`.
4. **A slow probe degrades to a `Gap`, never a 500.** And gaps are content: the
   most interesting thing Bedrock finds is often the thing nobody is required to
   write down.

```
> Estrella Damm.barley_supplier
  rows = 0
```

We can name seven shareholders of the brewery. We cannot name one field of
barley. Ownership is filed by law; origin is not.

---

## Quick start

Requires **Python 3.12+** (the schemas use `X | None` annotations).

```bash
cd backend
python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env && $EDITOR ../.env      # at minimum, CALA_API_KEY
set -a && . ../.env && set +a
./.venv/bin/uvicorn app.main:app --reload --port 8000
```

- Interactive schema: <http://localhost:8000/docs>
- Provider status: <http://localhost:8000/v1/health>

Bedrock degrades cleanly. With only `CALA_API_KEY` set it runs the full dig using
a static probe ladder and a deterministic classifier. Each additional key
upgrades one stage rather than unlocking it:

| Key | Upgrades |
|---|---|
| `CALA_API_KEY` | **required** — the facts |
| `OPENAI_API_KEY` | planner + photo input |
| `PIONEER_API_KEY` | classification accuracy on registry rows, plus the retraining loop |
| `FAL_KEY` | voice input |

---

## The training loop nobody has to label

The assay decides whether a row naming `Perfetti Van Melle` is a company or a
person. Get it wrong and the dig ends one hop in, before Luxembourg.

Bedrock never labels that by hand. When the prospector walks one hop further,
Cala has just *proved* what the previous node was — a name with shareholders was
a company, and did not terminate the chain. That correction goes back to Pioneer
via `POST /inferences/{id}/feedback`, so **the verified knowledge graph supervises
the small model**, and every dig a player runs is a free labelled example.

```
player digs  →  Cala answers  →  chain continues  →  correction posted
                     ↑                                       │
                     └────────  specialist gets better  ◀─────┘
```

`backend/scripts/train_assay.py` bootstraps the same dataset from answers already
sitting in the cache.

---

## Docs

| | |
|---|---|
| [`docs/API.md`](docs/API.md) | Endpoints, the `CoreSample` contract, every SSE frame |
| [`docs/PIONEER.md`](docs/PIONEER.md) | Where the fine-tuned models sit, the benchmark, and the label-free training loop |
| [`docs/AGENTS.md`](docs/AGENTS.md) | What each agent does, measured Cala behaviour, how to add one |
| [`docs/GAMIFICATION.md`](docs/GAMIFICATION.md) | Which response fields drive which game mechanic |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Branches, the working agreement, how we split the work |

`demo/` holds the design prototype that established the visual language — the
descent from candy red to institutional paper, the country trail, the `rows = 0`
ending. It runs on frozen data and needs no backend.

---

## Stack

Cala (knowledge) · OpenAI (reasoning) · Pioneer (GLiNER2 extraction + fine-tuned classification) ·
fal (speech, cut-outs) · FastAPI · SSE · Aikido (security) · Entire (repo).

Built at TechEurope Barcelona.
