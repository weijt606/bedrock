# Nutella — video script

A 75-second piece. **Every number and every source on screen is real text**,
rendered over the footage — never generated inside it. fal produces backgrounds
only. That division is not a style choice: a generative model cannot spell, and
a piece about verifiable provenance cannot show a hallucinated citation.

Data below is verbatim from the live Cala API. Raw responses in `cala-raw/food/`,
assembled shape in `docs/examples/editorial-nutella.json`.

---

## Shot list

### 1 · Open — the object (0:00–0:08)

**Footage:** fal loop A (below). A Nutella jar, filaments reaching out and back.
**On screen:** nothing yet. Let it breathe.
**Audio:** none throughout. Silence is the register.

### 2 · The question (0:08–0:14)

**Footage:** loop A continues, darkening.
**Text, centred, serif:**

> You have eaten this.
> You have never met anyone who made it.

### 3 · The machine works (0:14–0:30)

**Footage:** screen recording of the real dig, or the query lines typed on black.
**Text, monospace, appearing line by line with a running timer:**

```
> Who owns Nutella?                                    34.0s
> Ferrero Group.shareholders                           28.4s
> Nutella.ingredients                                  19.1s
> What child labour is documented in Ferrero's
  hazelnut supply chain in Turkey?                     41.7s
```

This shot is the proof that a real system ran. Do not stylise the queries —
their plainness is the point.

### 4 · The chain (0:30–0:45)

**Footage:** ground colour descending from candy red to institutional paper.
**Text, one node at a time, each with its source beneath in small type:**

```
Nutella
   ↓
Ferrero Group
   ↓
Ferrero family                          ← a person. the chain stops.
```

### 5 · What it is made of (0:45–0:56)

**Footage:** loop B (below) — hazelnut and cocoa textures, no product.
**Text, appearing as a list:**

```
hazelnuts    Turkey · Italy · Chile · United States
palm oil     Malaysia · Indonesia · Guatemala
cocoa        Nigeria / West Africa
sugar        Brazil · Europe
```

Source line, small: `Cala · Nutella.ingredients`

### 6 · The turn (0:56–1:08)

**Footage:** loop B, slowed to almost still.
**Text, one line at a time, each holding for 2 seconds:**

> Turkey grows three quarters of the world's hazelnuts.
> `Business Insider`

> Ferrero buys roughly one quarter of the global supply.
> `Business Insider`

> Ferrero's 2024 Sustainability Report identified
> **3,020 children** working on Turkish hazelnut farms.
> `India CSR · Ferrero 2024 Sustainability Report`

> Investigations found pickers as young as eleven.
> `The Guardian` · `Business & Human Rights Resource Centre`

The three publishers stacked under the last line carry the weight. Independent
sources agreeing is the argument — not our typography.

### 7 · The response (1:08–1:14)

Never end on the accusation without what is also on the record.

> Ferrero and the ILO ran a 40-month programme,
> over $4 million, against child labour in the harvest.
> `International Labour Organization`

### 8 · The silence (1:14–1:22)

**Footage:** flat paper, no motion.
**Text, monospace:**

```
> Ferrero Group.regulatory_actions                    rows = 0
> What regulatory actions has Ferrero received?       rows = 0
> What is the regulatory actions of Ferrero Group?    rows = 0
  ─────────────────────────────────────────────────────────────
  asked three ways. nobody has published it.
```

The same query returns seven rows for Coca-Cola. Showing all three attempts is
what makes the silence provable rather than asserted.

### 9 · Close (1:22–1:30)

> 66 brands answer to the same family.
> Nine of them are probably in your kitchen.

Then, plain: `Every fact above has a source. None of it was written by a model.`

---

## fal prompts — backgrounds only

Both are image-to-video and need a real photograph. Shoot a Nutella jar on a
flat surface, run it through `cutouts.py`, and use that PNG. Do not let a model
invent a branded packshot; `cutouts.py` says why.

**Loop A — the object**

```text
A 6-second seamless editorial motion loop based on the supplied reference
image of a jar. Keep the product packaging recognizable, stable, and
physically realistic; do not alter its label or logo.

The jar sits on a dark, tactile editorial surface. Around and behind it,
subtle abstract material textures inspired by hazelnut and cocoa emerge as
translucent layers. Fine warm filaments extend outward like an invisible
network, then return to the product.

Art direction: deep brown, cream, muted red; premium investigative magazine;
quiet, precise, elegant, restrained camera motion. The animation is
metaphorical, not documentary.

No people, workers, children, farms, factories, maps, flags, captions,
numbers, charts, voice, music, invented text, or invented logos.
```

**Loop B — material, no product**

```text
A 6-second seamless abstract loop. Translucent layers of hazelnut shell and
cocoa texture drift slowly across a dark tactile surface, lit like a still
life. Extremely restrained motion, almost still. No subject, no object, no
horizon.

Art direction: deep brown, cream, muted red; premium investigative magazine;
quiet, precise, elegant. Metaphorical, not documentary.

No people, workers, children, farms, factories, maps, flags, captions,
numbers, charts, voice, music, invented text, or invented logos.
```

Request 6s, 16:9, 720p, audio disabled, slow dolly-in. Loop both to fill their
shots rather than generating longer clips.

---

## Rules for the edit

1. **No generated text, ever.** Every word on screen is typed by us.
2. **No claim without its publisher underneath.** If a line cannot be sourced,
   it does not go in.
3. **Never say Ferrero is bad.** The piece reports what is filed. The reader
   decides. This is a legal line, not a stylistic one.
4. **Keep scope visible.** The 3,020 figure is about the *hazelnut supply
   chain*, not about the jar. Say so.
5. **Silence needs its attempts shown**, or it is just a claim.
