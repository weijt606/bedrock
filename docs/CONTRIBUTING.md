# Working agreement

Two of us, one weekend. The split is clean so we can work without blocking.

| | Owner |
|---|---|
| `backend/` — agents, orchestrator, providers | **backend** |
| the front end, the game layer, the shelf | **frontend** |
| `docs/API.md` — the contract between us | changed only by agreement |

## The contract

`docs/API.md` and `/docs` define everything that crosses between us. Build the
game against the shapes in that file, not against whatever the backend happens to
return today.

**Breaking the contract needs a heads-up in the channel before the PR**, because
it stops the other person working. Adding a field never breaks anything — add
freely.

Until the backend is up, mock it: every shape in `API.md` has a filled example,
and `demo/index.html` has five complete samples hard-coded to copy from.

## Branches

```
main                      always demo-able. Never push straight to it.
feat/<thing>              short-lived, one PR
fix/<thing>
```

Small PRs, merged the day they open. `main` must run at every moment of the
weekend — at a hackathon a broken `main` at hour 20 is unrecoverable.

## Running it

```bash
cd backend
python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
set -a && . ../.env && set +a
./.venv/bin/uvicorn app.main:app --reload --port 8000
./.venv/bin/pytest -q          # no network needed
```

## Before every demo

Cold Cala queries take 16–75 s and warm ones 0.5 s, so **warm anything you plan
to show**:

```bash
curl -s -X POST localhost:8000/v1/samples:sync -H 'Content-Type: application/json' \
     -d '{"kind":"text","text":"Chupa Chups","depth":4}' > /dev/null
```

`.cache/` is gitignored but it is worth sharing the directory directly before
judging — a warm cache is the difference between a two-second demo and a
ninety-second one.

## Rhythm

- Stand-up every ~4 hours: what landed, what is blocked, what changed in `API.md`
- Demo-able `main` at every checkpoint
- Feature freeze **4 hours** before submission — the rest is polish, warming the
  cache, and the script

## Line we do not cross

Bedrock reports what is on the public record and never scores or judges a
company. No ethics grades, no risk ratings, no adjectives. If a PR introduces a
judgement about a named company, that is a blocking review comment.
