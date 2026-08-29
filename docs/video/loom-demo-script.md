# Loom demo — 2 minutes

A demo, not a pitch. Show the thing working and say what is happening. No
adjectives about the product, no roadmap, no team slide.

**Before you hit record**

1. Warm the cache: search **Nutella** once and let it finish. Cold is 40–90s,
   warm is instant. Do this for any product you might type.
2. Check the video came back: `curl -s localhost:8000/v1/samples/<id>/media`
   should say `ready`. If it does not, cut the last shot — the piece stands
   without it.
3. Full screen, browser chrome hidden, notifications off.
4. Read the "wrong" answers out loud as written. Getting the guesses wrong on
   camera is the demo.

---

## 0:00 — 0:12 · The ask

**Screen:** the landing page.

> This is Bedrock. You type in something you eat, and it traces who actually
> owns it — every claim carrying the document it came from. Let me just run one.

*Type* `Nutella`. *Hit search.*

## 0:12 — 0:30 · It makes you commit

**Screen:** the two bet cards.

> Before it shows me anything, it makes me guess. Which country does the
> ownership end in? It's an Italian brand, so — Italy. And how many steps until
> I reach an actual person? I'll say three to four.

*Click* **Italy**. *Click* **3–4**.

## 0:30 — 0:48 · The work is on screen

**Screen:** the dig, probe lines appearing with their timers.

> While I was answering, it was already digging. These are the real queries
> going out to Cala — not a progress bar. *Who owns Nutella.*
> *Ferrero Group dot shareholders.* Each one is a live call against a verified
> knowledge graph.

## 0:48 — 1:12 · The chain

**Screen:** the chain cards, one click each.

> Ferrero Group is on the share register. And then — the Ferrero family holds
> a hundred percent. That's the end of it. Two steps from the jar in your hand
> to a family. No fund, no public market, nobody else.
>
> Under each line is the document behind it. That one's an SEC filing — I can
> open it.

*Click the source link. Let the filing load for a beat. Come back.*

## 1:12 — 1:34 · What nobody wrote down

**Screen:** the silence card — the big zero and the three attempts.

> This is the part I'd point at. We asked whether any regulator has ever acted
> against Ferrero. Zero rows — and we asked three different ways.
>
> That distinction matters, because Cala answers a *phrasing*, not an intent.
> The same question returns seven rows for Coca-Cola. So this silence is about
> Ferrero, not about our wording — and we show every attempt so you can check
> that yourself.

## 1:34 — 1:50 · The verdict

**Screen:** the verdict card.

> Then it holds me to what I said. Italy — right. Three to four steps — wrong,
> it's two. And ninety-four brands end at the same family, which I'd have put
> nowhere near that.
>
> Most people get most of it wrong. That's the product.

## 1:50 — 2:00 · How it works

**Screen:** the video card, or the terminal with the SSE stream.

> Underneath: six agents fanning out over Cala, streamed as they land so you
> watch it happen rather than wait for it. And one rule — no language model
> ever states a fact. They plan the questions; Cala answers them. Even the loop
> is labelled illustrative, and never carries a number.

---

## If you have to cut

Cut in this order: the closing architecture line, then the video, then the
second bet. **Never cut the silence card** — it is the only thing in the piece
nobody else will have.

## Lines to avoid

- *"revolutionary" / "game-changing" / "we believe"* — it is a demo.
- Any adjective about Ferrero. Say what is filed, not what it means. The piece
  reports the public record and lets the viewer decide; saying "shady" on camera
  undoes that in four seconds.
- *"AI-powered"*. The interesting claim is the opposite: no model wrote any of
  the facts.
