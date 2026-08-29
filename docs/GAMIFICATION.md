# Gamification

Which response field drives which mechanic. Written for whoever is building the
front end — you should not have to read the backend to build the game.

## The core loop

```
   name it  →  GUESS  →  watch it dig  →  verdict  →  it joins your shelf
```

The guess is what makes the wait worth having. A cold dig takes 30–90 seconds;
if the player has money on the outcome, that minute is suspense instead of a
loading screen. Ask **before** the first `layer` frame arrives.

## 1. Guess — from `guesses[]`

Three pre-built prompts arrive on `done`, but you can render them from the
`subject` frame with `answer: null` and fill in the answers at the end.

| `id` | Question | Options |
|---|---|---|
| `ends_in_country` | Which country does the ownership end in? | 7 countries |
| `hops_to_human` | How many steps until you reach a person? | `1-2` / `3-4` / `5+` |
| `still_domestic` | Is it still owned in *{origin}*? | Yes / No |

`still_domestic` is the cruellest and the best: it is binary, it is always
askable, and most people say Yes.

## 2. Dig — from `probe`, `layer`, `gap`

- `probe` → print the query **verbatim** and start a seconds counter. Showing the
  real query is the honesty of the piece; do not replace it with "Analysing…".
- `layer` → append. Advance the ground colour one step. Extend the country trail
  (`ES → NL → LU`). Switch the typeface from serif to mono at the first `company`
  layer: that is the moment the object stops being a thing and becomes a filing.
- `gap` → render as a result, in mono, with the zero picked out.

`layer.confidence` is the assay model's score. Below `0.6`, mark it as uncertain
rather than hiding it.

## 3. Verdict — from `score`

| Field | Reads as |
|---|---|
| `hops_to_human` | **4** steps to a human being |
| `countries` | This object has been to **3** countries |
| `ends_in` vs the guess | right / wrong |
| `left_home` | "It is not Spanish any more" |
| `siblings_count` | You have been choosing between **32** of these |
| `gaps_count` | **1** question nobody has answered |

## 4. Collection — client side

Keep dug samples in `localStorage`. The payoff is convergence: when two products
share a terminal owner, light both up. Two of the bundled five end at the same
two names, and the player discovers that themselves rather than being told.

Detect it by comparing terminal layer names across stored samples:

```js
const terminal = s => s.layers.filter(l => l.terminal).map(l => l.name);
```

## 5. The story — from `story[]`

`CoreSample.story` is a list of `Beat`s, already in telling order, each with a
`weight` from 0 to 1 and the `source` behind it.

| `kind` | Reads as |
|---|---|
| `origin` | where and when the thing started |
| `handover` | it answers to somebody else now |
| `border` | the trail left the country it came from |
| `terminus` | it ends here — an address, or a person |
| `scale` | "this object has been to 4 countries" |
| `convergence` | "32 brands end in the same place" |
| `concern` | a record on something the player said they care about |
| `silence` | we asked, and nobody has written it down |

Three ways to use it, cheapest first:

1. **Render in array order.** It is already a story.
2. **Sort by `weight`, take three.** The short version, for a results card.
3. **Sequence against the dig.** `at_step` says which layer a beat belongs to, so
   a beat can land on screen at the moment its layer does.

`headline` is templated from data — **no model wrote it** — so it is safe to
render verbatim beside a real company's name. `detail` is the second line.

The heaviest beat is normally a `concern` whose `about` is *not* the brand. That
is the payoff of the whole product: you asked about child labour, and the record
is filed against the company one step above the thing you picked up.

## 6. Concerns — from `concerns[]`

Ask the player what they care about **before** the dig, pass it as
`concerns: [...]`, and every entity in the chain gets checked, not just the brand.

That turns the guess mechanic into something sharper than a country quiz:

> *You said you care about child labour. Which of these five companies do you
> think has a record?*

Then reveal. It is usually not the one on the packet.

**Three rules for rendering this section.** They are not stylistic.

- **Never show a score, a grade or a traffic light.** Bedrock reports what is
  filed. "X appears on the UFLPA Entity List" is a fact with a source; "X is
  unethical" is an opinion and is defamatory if wrong.
- **`clear` is not "clean".** It means nothing has been filed where Cala can see
  it. Say that.
- **Always keep `about` visible.** A record against the parent must never look
  like a record against the brand.

## 7. Scoring

Deliberately not on the server — it belongs to the player, not the sample.
Suggested: +1 per correct guess, and a running "wrong" count that is the real
message. Most people are wrong most of the time; the tally is the argument.

## What the game must never do

- **Never rank or judge a company.** No ethics grades, no A–F, no traffic
  lights. Bedrock reports what is filed and the player decides. This is a legal
  line as much as an editorial one.
- **Never render a fact without its `source` reachable.** Every claim has one;
  hover, tap or footnote it.
- **Never hide a gap.** It is the third act.
