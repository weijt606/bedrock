# fal · Entire · Aikido

What each one does in Bedrock, and why it is there rather than bolted on.

---

## fal

Three jobs, and the same rule governs all three: **fal reads, it never invents.**
Bedrock's entire argument is that these facts are checkable, so a generated
image or an imagined transcript would undo the argument it is decorating. Every
fal call is a model deciding something about material that already exists.

### 1. Voice input — `nvidia/nemotron-3-nano-omni/audio`

An audio-understanding model rather than a transcriber: it takes a prompt
alongside the clip. That suits us better, because what we need from a voice note
is not every word, it is the one brand name in it — so it is asked for that and
told to answer `UNKNOWN` otherwise.

Two things measured against the live API, neither documented:

- **A data URI is rejected.** The model reads the file extension off the URL, so
  `data:audio/wav;base64,…` returns `422 Unsupported audio format` even when the
  bytes are a valid wav. The clip has to go to fal storage first and be
  referenced by the URL that comes back.
- **Only `.wav` and `.mp3` are accepted** — not the `audio/webm` a browser's
  MediaRecorder produces by default, nor Safari's mp4. Rather than put a
  converter on the server, the page decodes what it recorded and re-encodes
  16 kHz mono PCM itself.

Worth recording: given fal's own sample clip — a promo song with no brand in it —
the model answers `UNKNOWN` rather than inventing one. Asked to transcribe the
same clip verbatim it returns the lyrics, so the refusal is a refusal and not a
failure to hear.

`backend/app/clients/falstt.py`

### 2. Cutting the product out — `fal-ai/birefnet/v2`

The hero stands the product on the strata it is made of. That only works if the
product has no background; a rectangle on a rock reads as a sticker.

BiRefNet decides which of a photographer's pixels are the subject. It does not
invent one — which is why this is the honest use of a generative-media API in a
project like this, and why nothing here calls an image *generator*.

`General Use (Heavy)` at 2048 rather than Light, because thin structures — a
bottle neck, a straw, a lollipop stick — shear off at the lower setting.

Two paths, and the precedence between them matters:

| Input | What happens |
|---|---|
| a photograph | cut out and placed. **Nothing found by name may replace it** — the name read off a label can be wrong, the object in someone's hand cannot |
| a typed name | an official packshot is fetched, then cut out |

The cut-out is what lands, never the raw file. Placing the photograph first and
replacing it a moment later showed people their kitchen table standing on a rock.

`backend/app/clients/packshot.py`

### 3. The default hero

The stock Coca-Cola can on the plinth is the same pipeline run once, offline:
crop, BiRefNet, commit the result. The page therefore has no code path that
renders an image with a background.

---

## Entire

The repo is tracked by [Entire](https://entire.io), which captures the prompts,
transcripts and decisions behind each change alongside the git history.

```bash
brew tap entireio/tap && brew trust entireio/tap
brew install --cask entire
entire login && entire enable
npx skills add https://github.com/entireio/skills --all
```

Twelve skills in `.agents/skills/`, symlinked into `.claude/skills/`, pinned by
`skills-lock.json`. Hooks live in `.claude/settings.json` and are guarded — if
the CLI is not on `PATH` they exit 0, so a teammate who skips the install is
unaffected.

**Why it earns its place here specifically.** An unusual amount of this codebase
is a reaction to *measured API behaviour* rather than to anything a diff can
show:

- why `not_an_entity` exists — a seed run found `Free float` classified as a
  company
- why the labour-rights probe is `{e}.labour_disputes` and not a question — the
  question times out
- why the disk cache is treated as a feature — the same query returns different
  columns on different calls
- why a data URI cannot be sent to the audio model

None of that survives in a patch. `what happened at <file>:<line>` recovers it,
and `hand off this session` matters because we are two people and one of us is
usually asleep.

---

## Aikido

Connected to the repository, scanning the backend and the page. Three findings so
far, all fixed:

**A dependency advisory in starlette 0.41.3** (#22). Aikido's autofix pinned its
own patched build, `0.41.3+aikido.7`, from a private index.

That fix could not stand, for a reason CI made unarguable. The index URL carries
an account token: commit it and there is a credential in a public repository;
leave it out and the build fails, because CI has no token —

```
ERROR: No matching distribution found for starlette==0.41.3+aikido.7
```

There is no arrangement of a vendor pin that is both safe and installable in a
public repo. So the advisory is closed by moving upstream instead. `fastapi`
0.115.6 capped starlette below 0.42, which is what held us on the affected line
in the first place; lifting fastapi lifts the cap and skips the affected range
entirely. Now on `fastapi==0.141.1` with `starlette==1.6.0`, no private index,
73 tests green and no deprecation warnings.

Worth saying plainly: **the finding was real and Aikido was right to raise it.**
The autofix was the wrong shape for this repository, not the wrong call.

**An XSS pattern in the deck renderer** (#36). `card.kind` was interpolated into
a `data-kind` attribute unescaped. Aikido rated it low confidence and was right
to: `card.kind` is a literal the deck assigns itself — `bet`, `beat`, `verdict`,
`silence` — never user input and never anything Cala returned, so there was no
reachable exploit. Merged anyway. Escaping costs nothing, and the alternative is
a renderer where you have to remember which of its inputs are trusted.

**An XSS pattern in the result renderer** (#25). Interpolated values in the result
markup are escaped. They happened to be numbers, but the habit is the point: the
same template is one edit away from carrying a company name that came off the
open web.

**Where the scan has something real to bite on.** This is not a static site with
a token bolted to it — the backend holds four API keys, ingests third-party
data, accepts base64 uploads straight from a browser, and streams responses. The
upload endpoints were unbounded until review capped every base64 field; that is
exactly the class of thing a scanner should be pointed at.
