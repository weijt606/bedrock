# API

Everything the front end needs. The live, always-correct version of this is
<http://localhost:8000/docs> — it is generated from the same pydantic models, so
if this file and `/docs` ever disagree, `/docs` wins.

Base URL in development: `http://localhost:8000`

The API also serves the prototype front end from `/`, so there is one command to
run and no CORS to configure:

```bash
cd backend && ./.venv/bin/uvicorn app.main:app --port 8000
#  http://localhost:8000        the game
#  http://localhost:8000/docs   this contract, live
```

`demo/index.html` is the reference implementation of everything below — if a
frame is ambiguous here, look at how the demo renders it.

---

## Shape of a session

```
POST /v1/samples                 -> { sample_id, events, result }
GET  /v1/samples/{id}/events     -> SSE, one frame per finding      ← render this
GET  /v1/samples/{id}            -> the finished CoreSample
```

`POST` returns instantly. The dig itself happens on the event stream. **Do not
wait for the stream to close before drawing anything** — a cold dig runs 30–90
seconds and the whole experience is watching it happen.

---

## `POST /v1/samples`

```jsonc
{
  "kind": "text",            // "text" | "image" | "audio"
  "text": "Chupa Chups",     // when kind=text
  "image_b64": "...",        // when kind=image  (photo of the packaging)
  "audio_b64": "...",        // when kind=audio  (spoken product name)
  "mime": "image/jpeg",
  "depth": 4,                // 1..6 ownership hops
  "include": ["ownership", "supply", "statute", "flags", "siblings"]
}
```

Response `202`:

```json
{ "sample_id": "9f21c0ab77e1",
  "events": "/v1/samples/9f21c0ab77e1/events",
  "result": "/v1/samples/9f21c0ab77e1" }
```

Trim `include` to go faster. `["ownership"]` alone is the quickest useful dig.

---

## `GET /v1/samples/{id}/events`

Server-sent events. Each frame is a `StreamEvent`:

```
event: layer
id: 7
data: {"type":"layer","sample_id":"9f21…","seq":7,"at":32.6,"agent":"prospector","payload":{…}}
```

`at` is seconds since the dig started — use it for the timer in the UI.

### Frames, in the order they arrive

| `event:` | `payload` | What to do with it |
|---|---|---|
| `accepted` | `{depth, include}` | Dig registered |
| `subject` | `Subject` | Show what we think the product is. `confidence` 0.9 means Cala matched a real entity |
| `plan` | `{source, probes}` | `source` is `"planner"` or `"static-ladder"`. Debug only |
| `probe` | `{query, agent, hop?}` | **A lookup just started.** Print the query verbatim and start a counter — this is the dig animation |
| `layer` | `Layer` | An ownership step landed. Append it, advance the ground colour, extend the country trail |
| `supply` | `SupplyNode` | A manufacturer landed |
| `statute` | `Statute` | A regulation landed |
| `flag` | `Flag` | A public record landed |
| `gap` | `{query, reason, latency_s}` | **A question with no answer.** Render it, do not hide it — see below |
| `siblings` | `{items, owner, latency_s}` | Other brands under the same owner |
| `score` | `Score` | Running totals |
| `done` | `CoreSample` | The whole thing. Switch to the verdict screen |
| `error` | `{message}` | Only for input we could not read at all |

### Gaps are content, not errors

`reason` is one of `no_rows`, `too_complex`, `error`. A `no_rows` gap means
nobody has published that fact anywhere Cala can read — which is the most
interesting thing the product finds. Render it as a result:

```
> Estrella Damm.barley_supplier
  rows = 0
```

---

## `CoreSample`

```jsonc
{
  "subject": {
    "raw_input": "chupa chups",
    "resolved_name": "Chupa Chups",
    "entity_id": "660f12c9-504d-412c-83bf-e77580630b52",
    "entity_type": "Product",
    "description": "An iconic lollipop brand founded in 1958 by Enric Bernat…",
    "confidence": 0.9,
    "identified_by": "text"          // "text" | "vision" | "speech"
  },

  "layers": [                        // the dig, in order
    {
      "index": 1,
      "name": "C+F Confectionery and Foods S.A.",
      "kind": "company",             // company|person|family|fund|foundation|unknown
      "country": "LU",               // ISO-3166 alpha-2, or null
      "city": null,
      "address": "10, Rue Henri M. Schnadt, L-2530 Luxembourg",
      "stake_percent": null,
      "relationship": "direct parent",
      "detail": ["C+F Confectionery and Foods S.A. — direct parent", "…"],
      "confidence": 0.88,
      "terminal": false,             // true = a human being, chain ends here
      "source": {
        "query": "Perfetti Van Melle.shareholders",
        "endpoint": "knowledge/query",
        "latency_s": 34.0,
        "cached": false,
        "documents": [],
        "fact_ids": ["b0595ee6-…"]
      }
    }
  ],

  "supply":   [ { "name": "Casa Tarradellas", "role": "pizzas…", "shared_with": [], "source": {…} } ],
  "statutes": [ { "name": "Regulation (EU) No 1169/2011", "number": "1169/2011",
                  "title": "Food Information to Consumers", "provisions": ["…"], "source": {…} } ],
  "flags":    [ { "kind": "litigation", "title": "RICO lawsuits by independent designers",
                  "parties": "Independent designers vs Shein", "source": {…} } ],
  "siblings": ["Mentos", "Trident", "Smint", "…"],

  "gaps": [ { "query": "Estrella Damm.barley_supplier", "reason": "no_rows", "latency_s": 29.0 } ],

  "guesses": [                       // ask these BEFORE revealing the layers
    { "id": "ends_in_country", "question": "Which country does the ownership end in?",
      "options": ["Spain","Netherlands","Luxembourg","Germany","Italy","United States","United Kingdom"],
      "answer": "Luxembourg" },
    { "id": "hops_to_human",  "question": "How many steps until you reach a person?",
      "options": ["1-2","3-4","5+"], "answer": "3-4" },
    { "id": "still_domestic", "question": "Is it still owned in Spain?",
      "options": ["Yes","No"], "answer": "No" }
  ],

  "score": {
    "hops_to_human": 3,
    "countries": ["ES", "NL", "LU"],
    "ends_in": "LU",
    "origin_country": "ES",
    "left_home": true,
    "siblings_count": 32,
    "gaps_count": 1
  },

  "meta": {
    "sample_id": "9f21c0ab77e1",
    "queries_run": 5,
    "cache_hits": 3,
    "total_latency_s": 73.4,
    "agents": ["intake","prospector","surveyor","statute","recorder","extractor"],
    "models": { "planner": "gpt-4o-mini", "assay": "pioneer:gemma-4-12b",
                "stt": "fal-ai/whisper", "facts": "cala/knowledge" }
  }
}
```

### `answer` is withheld during the dig

`guesses[].answer` is `null` on every frame until `done`. That is deliberate:
ask the player before the chain resolves, keep their pick client-side, and
compare once `done` arrives. Nothing on the stream spoils the answer early.

---

## Other endpoints

| | |
|---|---|
| `GET /v1/health` | Which providers are wired up, which classifier is live, how many answers are cached |
| `POST /v1/samples:sync` | Blocking, returns a `CoreSample`. Tests and cache warming only — never a demo |

### Warming the cache before a demo

Cold: 16–75 s. Warm: ~0.5 s, permanently. Run every product you intend to show:

```bash
for p in "Chupa Chups" "Estrella Damm" "Freixenet" "Cola Cao" "Nutella" "Zara"; do
  curl -s -X POST localhost:8000/v1/samples:sync \
    -H 'Content-Type: application/json' \
    -d "{\"kind\":\"text\",\"text\":\"$p\",\"depth\":4}" | jq -r '.subject.resolved_name'
done
```

---

## What a real stream looks like

`Chupa Chups`, depth 3, against live Cala with a partly warm cache:

```
[   0.0s] accepted
[   1.0s] subject   Chupa Chups (Product)
[   1.0s] probe     > Who ultimately owns Chupa Chups?          ← reader and ladder
[   1.0s] probe     > Who owns Chupa Chups?                       start together
[   2.2s] layer     Perfetti Van Melle                unknown  cc=None
[   2.2s] probe     > Perfetti Van Melle.shareholders
[   3.2s] layer     C+F Confectionery and Foods S.A.  company  cc=LU
[   3.2s] probe     > C+F Confectionery and Foods S.A.shareholders
[  36.8s] layer     Egidio Perfetti                   unknown  cc=None
[  36.8s] siblings  32 brands
[  36.8s] score     {"hops_to_human":3,"ends_in":"LU","siblings_count":32}
[  36.8s] done      queries=3  cache_hits=2
```

Three things to design around, all visible above:

1. **Two probes open at once.** The reader and the ownership ladder run
   concurrently. Key your probe timers by `payload.query`, not by assuming one
   is in flight at a time.
2. **The gap between 3.2s and 36.8s is one cold Cala query.** That is the dig,
   and it is why the probe line shows the real query with a running counter
   rather than a spinner. Warm, the same sample finishes in about two seconds.
3. **`kind` can be `unknown`.** Above, the person at the end of the chain was
   not confidently classified, so `terminal` stayed false. Render `unknown`
   honestly — do not coerce it to `company` or `person`.

---

## Front-end recipe

```js
const { sample_id, events } = await fetch("/v1/samples", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ kind: "text", text: name, depth: 4 }),
}).then(r => r.json());

const es = new EventSource(events);

es.addEventListener("probe",  e => startProbeTimer(JSON.parse(e.data).payload.query));
es.addEventListener("layer",  e => pushLayer(JSON.parse(e.data).payload));
es.addEventListener("gap",    e => pushGap(JSON.parse(e.data).payload));
es.addEventListener("done",   e => { showVerdict(JSON.parse(e.data).payload); es.close(); });
es.addEventListener("error",  e => es.close());
```

`EventSource` cannot send headers or a body, which is why creating the sample and
streaming it are two calls.
