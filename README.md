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
| **fal** | transcribe speech, cut a product out of its background, render the motion behind a card | depict anything a card then treats as evidence |
| **Aikido** | scan every dependency and every diff, and open a PR when it finds something | run at request time — it has never seen a response |
| **Entire** | record the prompts, transcripts and decisions behind each change, next to the git history | enter the request path at all |

The last two rows are not filler, and they are not in the request path either —
which is exactly why they belong in a table about who is allowed to state a fact.
A supply-chain audit tool that shipped a compromised dependency would be making
its reader's argument for them; the reason Aikido can never contaminate a fact is
that it has never seen one.

Entire earns its row for a related reason. An unusual amount of this codebase is
a reaction to *measured API behaviour* rather than to anything a diff can show —
why the auditor asks `Ferrero.labour_disputes` and not "what has Ferrero been
accused of", why a query goes to the parent and not the brand. The diff shows the
line; the transcript shows the twelve queries that made it the only line that
works. Three Aikido findings and the full write-up are in
[`docs/SIDE_TRACKS.md`](docs/SIDE_TRACKS.md).

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
  text  ──┐
  image ──┼──▶   INTAKE   ──▶   ORCHESTRATOR
  audio ──┘   fal · OpenAI      plans the dig · fans out · enforces budgets
             reads the label                │
             hears the name                 │
                ┌───────────────┬───────────┴───────────┬───────────────┐
                │               │                       │               │
           PROSPECTOR       SURVEYOR                 STATUTE        RECORDER
            ownership        supply                    law           filings
           hop by hop      concurrent              concurrent      concurrent
           sequential
                │               │                       │               │
                └───────────────┴───────────┬───────────┴───────────────┘
                                            │
                              AUDITOR · ENRICHER · CALA
                            every fact, with its source
                                            │
                        ┌───────────────────┴───────────────────┐
                   typed rows                            markdown prose
                        │                                       │
                  ASSAY · Pioneer                        READER · Pioneer
                   gliner2-base                           gliner2-large
              what kind of thing                       where the spans
                  is this row?                                are
                        │                                       │
                        └───────────────────┬───────────────────┘
                                            │
                                        EXTRACTOR
                              one CoreSample, streamed over SSE
                                            │
                        ┌───────────────────┴───────────────────┐
                    the deck                              fal · video
              bet · descend · verdict                 illustrative only,
                                                      never given a fact
```

**The crew**

| Agent | Job |
|---|---|
| `intake` | **fal** hears a spoken name, **OpenAI** reads a photographed label; either way one `Subject`, resolved against Cala |
| `prospector` | Walks the ownership chain hop by hop until it reaches a person |
| `surveyor` | Manufacturers, co-packers, and which other brands use the same factory group |
| `statute` | The regulations that dictate what the label must declare |
| `recorder` | Litigation and sanctions listings, as filed |
| `reader` | **Pioneer** — turns Cala's *prose* answers back into structured layers |
| `assay` | **Pioneer** — what kind of thing each registry row names, and whether the chain ends there |
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

## Where the small models sit

Cala tells us **who** owns a company. It does not tell us **what kind of thing
the answer is** — and that decides whether the dig continues.

```
[36.8s] layer   Egidio Perfetti   kind=unknown   terminal=False
```

That is a real frame. The human being at the end of the chain, and the system
did not know it had arrived. The opposite failure is worse: read
`Perfetti Van Melle` as a person and the chain ends one hop in, before
Luxembourg. Read `Free float` as a company and you follow a *category* upwards
into nonsense.

`Perfetti Van Melle` and `Juan Roig` are the same shape to a rule — three
capitalised words, no legal suffix. One is a family firm, the other a family
member.

So Bedrock puts a fine-tuned model in exactly two places, and both of them are
about **shape, not truth**:

| | Model | Decides |
|---|---|---|
| **assay** | `gliner2-base` | what kind of thing a registry row names, and whether ownership stops there |
| **reader** | `gliner2-large` | where the entities are inside Cala's *prose* answers, which are often faster and more current than its tables |

Narrow, high-volume, short strings, no reasoning required — an encoder answers in
~100 ms at $0.15/M where a frontier model takes seconds at $5/M and is worse at
it. Our whole latency budget is already spent on Cala, so this step cannot cost
seconds.

Neither model ever adds a fact. Every layer they touch still carries the Cala
`Source` it came from, which is why a model can sit in the hot path without
breaking the one rule.

### The training set nobody labels

When the prospector walks one hop further, Cala has just **proved** what the
previous node was: a name with shareholders was a company, and did not terminate
the chain. That correction goes back via `POST /inferences/{id}/feedback`.

```
player digs  →  Cala answers  →  chain continues  →  correction posted
                     ↑                                       │
                     └────────  specialist improves  ◀────────┘
```

**The verified knowledge graph supervises the small model.** Every dig anyone
runs is a free labelled example, the system gets more accurate the more it is
played, and there is no annotation step, ever. Corrections go out only where the
model disagreed with what the chain went on to prove.

The same principle referees the benchmark: gold labels come from the entity names
Cala's *typed* endpoint returned, and each system is scored on recovering them
from Cala's *prose*. No hand-labelling, and no model grading a model.

Both models are optional — without a key the assay falls back to a deterministic
classifier and the reader contributes nothing, so the typed ladder carries the
dig. See [`docs/PIONEER.md`](docs/PIONEER.md).

---

## Docs

| | |
|---|---|
| [`docs/API.md`](docs/API.md) | Endpoints, the `CoreSample` contract, every SSE frame |
| [`docs/PIONEER.md`](docs/PIONEER.md) | Where the fine-tuned models sit, the benchmark, and the label-free training loop |
| [`docs/AGENTS.md`](docs/AGENTS.md) | What each agent does, measured Cala behaviour, how to add one |
| [`docs/GAMIFICATION.md`](docs/GAMIFICATION.md) | Which response fields drive which game mechanic |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Branches, the working agreement, how we split the work |

`frontend/` is the page. It is served by the API at <http://localhost:8000> in
development, and deployed separately in production, where it falls back to
`/api`.

---

## Stack

Cala (knowledge) · OpenAI (reasoning) · Pioneer (GLiNER2 extraction + fine-tuned classification) ·
fal (speech, cut-outs) · FastAPI · SSE · Aikido (security) · Entire (repo).

Built at TechEurope Barcelona.
