# Pioneer in Bedrock

Bedrock uses Pioneer in two places, and in both of them it is replacing a
general-purpose LLM API call that we had already written and shipped. Neither is
decorative: remove them and the product is measurably slower, more expensive and
wrong more often.

---

## How it works

### The decision everything hinges on

Cala tells us **who** owns a company. It does not tell us **what kind of thing
the answer is** — and that is what decides whether the dig continues.

From a real run:

```
[36.8s] layer   Egidio Perfetti   kind=unknown   terminal=False
```

That is the human being at the end of the chain, and the system did not know it
had arrived. The opposite failure is worse. An earlier build read this row as a
person:

```
[ 1.7s] layer   Perfetti Van Melle   kind=person   terminal=True   ← chain over
```

One hop in, and Luxembourg is never found.

`Perfetti Van Melle` and `Juan Roig` are indistinguishable to a rule: three
capitalised words, no legal suffix. One is a family firm, the other a family
member. A share register also opens with rows like `Free float` and
`Treasury shares`, which name a category rather than an owner — follow one of
those upwards and the whole chain is nonsense.

### Why a small model, and not a big one

| | |
|---|---|
| Input | one short string — `Juan Roig` plus the columns Cala returned beside it |
| Output | one of six labels, plus a yes/no |
| Frequency | 3–30 rows per dig, every dig, every player |
| Reasoning required | none — this is pattern recognition |

Narrow, high-volume, short, no reasoning. That is where an encoder beats a
decoder on accuracy, latency and cost simultaneously: `fastino/gliner2-base-v1`
answers in ~100 ms at $0.15/M, against seconds and $5/M for a frontier model
doing the same job badly. Our entire latency budget is already spent on Cala
(16–75 s cold), so the classification step cannot cost seconds.

Note what is in the `text` we send: not just the name, but the columns Cala
returned beside it. `role: chairman` is the tell that a regex never sees.

### The data flow

```
                    Cala  ─────────────────────────────┐
                      │                                 │
        knowledge/query│                  knowledge/search│
        typed rows     │                  markdown prose  │
                      ▼                                 ▼
              ┌───────────────┐                 ┌───────────────┐
              │  ASSAY        │                 │  READER       │
              │  classify     │                 │  extract      │
              │  gliner2-base │                 │  gliner2-large│
              └───────┬───────┘                 └───────┬───────┘
                      │ kind · confidence · terminal    │ spans
                      ▼                                 ▼
              ┌─────────────────────────────────────────────────┐
              │           the ownership chain, with sources     │
              └─────────────────────────────────────────────────┘
```

Both take *facts that already exist* and decide something about their **shape** —
what type a row is, where a span begins. Neither adds a fact. That is what keeps
the one rule intact while still putting a model in the hot path.

### The boundary, stated exactly

| | Allowed to | Never allowed to |
|---|---|---|
| **Cala** | state facts, with sources | — |
| **OpenAI** | plan which questions to ask, reshape rows, read a brand name off a photograph | assert anything about a company |
| **Pioneer** | say what kind of thing a row names, and where a span is | add a row, or change what one says |

Enforced structurally: `source` is a required field on `Layer`, `SupplyNode`,
`Statute` and `Flag`, so an agent cannot construct an unsourced fact. Layers the
reader produces still carry the `knowledge/search` query that produced the
paragraph they were read from.

---

## 1. The reader — GLiNER2 doing the thing we were paying a frontier model to do

### The problem we did not know we had

Cala exposes two endpoints over the same knowledge. We were only using one.

| | `knowledge/query` | `knowledge/search` |
|---|---|---|
| Returns | typed rows | **markdown prose** |
| "Who ultimately owns Chupa Chups?" | 73 s across the ladder | **0.85 s** |
| Freixenet ownership | Ferrer family 42%, Bonet 7.3% | names the **2021 Oetker family split** and the buy-out of the remaining Ferrer/Bonet shares |

The prose is frequently both faster and **more current** than the table. We were
discarding it for one reason only: somebody has to turn a paragraph back into
structure.

That is a named-entity problem, not a reasoning problem — and we had it
implemented as a JSON-mode structured-extraction prompt to `gpt-4o-mini`.

### The swap

`app/agents/reader.py` sends the prose to a GLiNER2 encoder through Pioneer's
`POST /inference` with a schema:

```json
{ "entities": ["company","person","family","jurisdiction","stake","date","brand"],
  "classifications": [{ "task": "chain_position",
                        "labels": ["ultimate_parent","direct_parent","subsidiary",
                                   "acquirer","target","shareholder"] }] }
```

A zero-shot NER encoder used as a **knowledge-graph prose decompiler** — reading
a knowledge base's own natural-language answer back into the table it came from.
The encoder decides *where the spans are*; it never decides what is true, so the
one rule holds and every layer the reader emits still carries the Cala `Source`
of the paragraph it came from.

### Where the benchmark's gold labels come from

We do not hand-label, and we do not let a model grade a model.

Cala's typed endpoint already knows the answer. Its prose endpoint describes the
same ownership in a paragraph. So for each subject the entity names
`knowledge/query` returned are the gold set, and each system is scored on whether
it recovered those names from the prose.

**The verified knowledge graph is the referee** — the same principle that keeps
the product honest, applied to the evaluation. It also means the benchmark grows
for free: every subject a player digs becomes another test case.

```bash
python scripts/bench.py build          # gold + prose, straight from Cala
python scripts/bench.py run            # A vs B vs C
```

| | System |
|---|---|
| **A** | a frontier decoder (`gpt-5.6-luna` by default), JSON-mode structured extraction — *the incumbent* |
| **B** | `fastino/gliner2-large-v1`, zero-shot |
| **C** | our fine-tuned job id |

Reported per system: precision, recall, F1, p50 and p95 latency, and measured
cost per 1,000 calls. Results land in `datasets/bench_results.json`.

---

## 2. The assay — the one classification that decides whether the dig works

Given a row from a share register, what kind of thing does it name, and does
ownership stop there?

| Row | Wrong answer | Consequence |
|---|---|---|
| `Perfetti Van Melle` | person | chain ends one hop in, Luxembourg never found |
| `Juan Roig` | company | chain never terminates |
| `Free float` | company | we follow a *category* up the chain |

Three capitalised words with no legal suffix. A regex cannot separate a family
company from a family member, and a frontier model is a preposterous way to
answer a question this small, millions of times.

`fastino/gliner2-base-v1` via `POST /inference`, one call per row, whole batch
concurrent — ~100 ms each against a 5,000 req/min ceiling.

---

## Adaptive inference: a training set nobody labels

This is the part we are proudest of.

When the prospector walks one hop further, Cala has just **proved** what the
previous node was: a name that turned out to have shareholders was a company, and
did not terminate the chain. That correction goes back to
`POST /inferences/{id}/feedback`.

```
player digs  →  Cala answers  →  chain continues  →  correction posted
                     ↑                                        │
                     └────────  specialist improves  ◀─────────┘
```

So **the verified knowledge graph supervises the small model**, every dig anyone
runs is a free labelled example, and the system gets more accurate the more it is
used — with no annotation step, ever. Corrections go out only where the model
disagreed with what the chain went on to prove; confirming a correct prediction
carries no signal.

`/v1/health` reports `assay.corrections_posted` so you can watch it happen.

---

## Synthetic data

`scripts/train_assay.py generate` asks Pioneer for more rows of the same shape,
with a domain description written around the cases that actually broke us:

> …include hard cases where a company name looks like a person's name because it
> is derived from the founding family — for example 'Perfetti Van Melle',
> 'Dr. August Oetker KG', 'Casa Tarradellas' — and individuals whose rows carry
> an explicit role or stake.

Before generating anything, `seed` harvests real rows out of our own Cala cache.
Its first run produced **101 real rows, 36 flagged low-confidence**, and turned up
`Free float` and `Treasury shares` being classified as companies — which is why
`not_an_entity` exists as a label and why the prospector now walks past those
rows. Real data first, synthetic data to fill the gaps it exposes.

---

## What this account can actually train

Read live from `GET /base-models` (27 models, 7 trainable):

| Model | Type | $/M |
|---|---|---|
| `fastino/gliner2-base-v1` | encoder | 0.15 |
| `fastino/gliner2-large-v1` | encoder | 0.15 |
| `fastino/gliner2-multi-v1` | encoder | 0.15 |
| `fastino/gliner2-multi-large-v1` | encoder | 0.15 |
| `fastino/Fastino-Nemotron-3.5-Lightning-Financial` | decoder | 0.50 |
| `fastino/Fastino-Nemotron-3.5-Lightning-Healthcare` | decoder | 0.50 |
| `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16` | decoder | 0.50 |

Two notes. There is no Gemma 4 on this account, so the bonus goes to GLiNER2.
And `Fastino-Nemotron-3.5-Lightning-Financial` is a trainable decoder already
pointed at the financial domain — corporate registries, filings, shareholdings —
which is the obvious next specialist after the reader lands.

Frontier decoders are on the same key (`gpt-5.6-luna`, `gpt-5.5`,
`claude-sonnet-5`, `claude-opus-5`, `GLM-5.2`, `Kimi-K3`, `DeepSeek-V4-Flash`),
which is why the benchmark routes its baseline through Pioneer too: the
specialist and the model it replaces go through the same gateway, the same
client and the same network, so the comparison is not rigged by plumbing.

---

## The gold set, as built

`scripts/bench.py build` against live Cala: **15 subjects, 68 gold entities**,
median prose length 1,026 characters.

It also measured the thing that motivated the whole reader agent:

```
median Cala latency:  prose 26.3s   vs   typed rows 47.1s
Chupa Chups:          prose  0.8s   vs   typed rows 28.1s
```

`datasets/bench_ownership.json` is committed, so the benchmark is reproducible
without a Cala key.

---

## Both specialists are optional

Neither model is load-bearing for the pipeline, which is deliberate — a
hackathon account, a rate limit or an outage should not be able to take the
product down.

| Without | What happens |
|---|---|
| `PIONEER_API_KEY` | the assay falls back to a deterministic classifier that refuses to guess on ambiguous names, and the reader contributes nothing — the typed ladder carries the dig |
| a trained job id | `MODEL_ASSAY` / `MODEL_READER` stay on the stock GLiNER2 encoders |
| the extractor entirely | ownership still resolves, one hop at a time, from typed rows |

What is lost is precision and speed, not function. The fallback is built never to
make the expensive mistake — ending a chain early — so it returns `unknown` and
keeps digging where the specialist would have decided.

Swapping either model in is one environment variable:

```
MODEL_ASSAY=job_...     # the row classifier
MODEL_READER=job_...    # the prose extractor
```

---

## Commands

```bash
python scripts/train_assay.py seed        # real rows from our own cache (no key needed)
python scripts/train_assay.py generate    # POST /generate
python scripts/train_assay.py train       # LoRA on GLiNER2
python scripts/train_assay.py status <id> # f1 / precision / recall
python scripts/train_assay.py evaluate <id>
python scripts/train_assay.py models      # what the account can serve

python scripts/bench.py build             # gold set from Cala
python scripts/bench.py run               # frontier vs zero-shot vs specialist
python scripts/probe_schema.py            # what does the schema field really accept?
```

Then in `.env`:

```
MODEL_ASSAY=job_...     # the row classifier
MODEL_READER=job_...    # the prose extractor
```

Nothing else changes. Both models are swapped by environment variable, and both
have a fallback that keeps the pipeline running if Pioneer is unreachable — the
assay degrades to a deterministic classifier, the reader simply contributes
nothing and the typed ladder carries the dig.
