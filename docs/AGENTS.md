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
Classifies each row: entity kind, confidence, whether the chain terminates. One
call per batch, never per row. Biased toward `company`, because mislabelling a
company as a person ends the dig one hop in — the failure we actually hit.

Falls back to a deterministic regex classifier with no key, so the pipeline runs
end to end without Pioneer and gains accuracy when it is plugged in. Pioneer's
`adaptive: true` retrains on our traffic, and every dig is a free labelled
example.

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
