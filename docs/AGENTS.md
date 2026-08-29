# Agents

## Measured Cala behaviour

Everything in the backend is shaped by these, observed over ~60 live queries.
Read this before changing a probe.

| Observation | Consequence |
|---|---|
| Cold query 16–75 s, median ≈ 35 s | streaming; concurrent fan-out; budgets |
| The same query afterwards ≈ 0.5 s, permanently | the disk cache is the product |
| ~6 rapid calls then `429` | one shared semaphore across every agent |
| Answers return 1–33 rows, never more | exhaustiveness comes from depth, not volume |
| `GET /v1/entities?name=` is a **string** match, not semantic | intake re-ranks by exact name then entity type |
| `POST /v1/entities/{id}` — note POST, `GET` returns 405 | — |
| `/introspection` lists what the schema *allows*, not what exists | never trust it; even Nestlé returns `relationships: {}` |
| Entity nodes carry no edges — the graph only exists at `knowledge/query` | you cannot traverse; you must ask |
| Law entities have no incoming edges | you cannot go product → statute, only ask directly |
| Conceptual questions match company *names* | ask narrow, concrete questions |
| Over-broad questions return `{"error": "This question is too complex…"}` | `CalaClient` surfaces this as `too_complex`; ask something smaller, never retry the same string |
| Per-property `sources` on `retrieve_entity`; `explainability` fact ids on `knowledge/search` | both are collected into `Source` |

## The crew

### `intake`
Any input → one `Subject`. Vision reads a brand name off packaging; fal
transcribes speech; text passes through. The string is then resolved against
Cala's entity index and re-ranked (exact name first, then `Product` > `Company` >
`Organization`) because the raw search returns every shell company sharing a
substring — "Chupa Chups" also returns `CHUPA YACHTING LIMITED`.

### `prospector`
The ownership chain. The only sequential agent: hop *N+1* asks about hop *N*'s
answer. Hop 0 is `Who owns {X}?`; after that `{X}.shareholders`, which returns
registered addresses and stake percentages where they exist.

Terminates on: an assay `terminal` mark, a repeated name, an empty result, or the
depth cap. Emits every hop immediately.

### `surveyor`
`{X}.manufactured_by` and supplier lookups, plus `shared_factories(region)` —
which brands sit in the same factory group. Coverage is uneven and follows
reporting density: McDonald's Spain returns 7 suppliers, Mercadona's
*interproveedores* 28 with revenue figures, `H&M.suppliers` returns nothing.
That unevenness is a finding, not a bug.

### `statute`
Regulations governing the label. Must ask by number or by a concrete question;
"Protected Designation of Origin" as a query returns companies with "Origin" in
their name.

### `recorder`
Litigation and sanctions, **as filed**. Rows carry `source` fact ids. Never
characterises a company — see the one rule in the README.

### `assay` (Pioneer)

Given one row from a share register, decide what kind of thing it names and
whether the ownership chain stops there. That single call is what makes the dig
work or fail:

| Row | Wrong answer | What happens |
|---|---|---|
| `Perfetti Van Melle` | person | chain ends one hop in, Luxembourg never found |
| `Juan Roig` | company | chain never ends, runs to the depth cap |
| `Free float` | company | we follow a *category* upwards and get nonsense |

Three capitalised words with no legal suffix — a regex cannot separate a family
company from a family member. It is a narrow, high-volume classification problem
over short strings, which is exactly where a small fine-tuned encoder beats a
large general model on accuracy, latency and cost simultaneously. That is the
only place Pioneer sits in Bedrock.

**Runtime** — `POST /inference` on a GLiNER2 encoder, schema-based:

```json
{ "model_id": "fastino/gliner2-base-v1",
  "text": "Juan Roig | role: executive chairman | ownership_percent: 50.66%",
  "schema": { "classifications": [
      {"task": "entity_kind",       "labels": ["company","person","family","fund","foundation","not_an_entity"]},
      {"task": "chain_terminates",  "labels": ["yes","no"]}]},
  "threshold": 0.5 }
```

Auth is `X-API-Key`, not a bearer token. Rows in a batch are classified
concurrently — ~100 ms each, 5,000 req/min allowed — so a whole answer costs
about as much wall-clock as one row.

**The feedback loop** — nobody hand-labels anything.

```
prospector walks past a node  ──▶  that node demonstrably had shareholders
                                    ──▶  it was a company, and not terminal
                                          ──▶  POST /inferences/{id}/feedback
```

Cala's verified graph is the supervisor. Every dig a player runs produces free
labelled examples, and Pioneer's Adaptive Inference retrains the specialist on
them. Corrections are only posted where the model disagreed with what the chain
went on to prove — confirming a correct prediction carries no signal.

**Training** — `backend/scripts/train_assay.py`:

```
seed      harvest real rows out of our own Cala cache into datasets/
generate  POST /generate      synthesise more of the same shape
train     POST /felix/training-jobs   LoRA on fastino/gliner2-base-v1
status    poll for f1 / precision / recall
evaluate  POST /felix/evaluations
```

`seed` needs no Pioneer key — it reads answers already on disk. On the first run
it produced 101 real rows and flagged 36 as low-confidence, which is where the
hand-labelling effort is worth spending. It also turned up `Free float` and
`Treasury shares` classified as companies, which is how the `not_an_entity`
label came to exist.

Put the finished job id in `MODEL_ASSAY` and nothing else changes.

**Without a key** the client falls back to a deterministic classifier that
refuses to guess on ambiguous names — it returns `unknown` with `terminal=False`
so the dig continues and the next hop resolves it. Ending a chain early is the
expensive mistake, so the fallback is built to never make it.

### `extractor`
Folds everything into one `CoreSample` and computes the derived numbers the game
plays with. Adds no facts.

## Adding an agent

1. New module in `app/agents/`, one class, one `run(subject, emit, ...)`.
2. Return `(items, gaps)`. Every item carries a `Source` — use `base.source_of`.
3. Add its field to `CoreSample`, its event to `EventType`.
4. Wire it into `Orchestrator.run` as another `dig_*` coroutine inside the
   `asyncio.gather`, unless it depends on the chain.
5. Add its questions to the planner prompt in `clients/llm.py`.

## The boundary

A model may **plan**, **reshape** and **read**. A model may not **assert**.
If your agent puts a string into a field with a `Source`, that string came from
Cala. This is enforced structurally: `source` is required on `Layer`,
`SupplyNode`, `Statute` and `Flag`, and pydantic will not construct them without it.
