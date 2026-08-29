"""Pre-warm Cala for a demo.

Cala is 16-108s cold and ~0.5s warm, and the warm answer is permanent. A dig
that has never been run takes four minutes; the same dig a second time takes
twelve seconds. That is the whole story of this product's latency, and it means
a demo is fast or slow entirely according to whether somebody warmed it first.

    python scripts/warm.py Nutella "Coca-Cola" Oreo

Runs every query a real dig would issue, in the same shapes, so the live run
finds all of them cached. Prints what is still cold at the end — anything listed
there will be slow on stage.
"""
from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")

from app.agents.auditor import DIRECT_QUERY, LIST_QUERY          # noqa: E402
from app.clients.cala import CalaClient                          # noqa: E402
from app.schemas import Concern, SampleRequest                   # noqa: E402

# Whatever the request defaults to — warming a different set than the dig asks
# for is how you arrive on stage having warmed nothing that matters.
CONCERNS: list[Concern] = SampleRequest(kind="text", text="x").concerns

SLOW_S = 5.0


async def warm(cala: CalaClient, query: str, results: list) -> None:
    t0 = time.perf_counter()
    res = await cala.query(query)
    results.append((time.perf_counter() - t0, len(res.rows), query, res.error))


async def main(names: list[str]) -> None:
    cala = CalaClient()
    results: list = []

    # The shared list questions are identical for every product, so they are
    # warmed once for everybody.
    shared = [LIST_QUERY[c] for c in CONCERNS]
    await asyncio.gather(*(warm(cala, q, results) for q in shared))

    for name in names:
        print(f"\n  warming {name} ...", flush=True)
        # Round one: resolve the chain, because round two needs its names.
        chain_qs = [f"Who owns {name}?", f"Who ultimately owns {name}?",
                    f"{name}.country_of_origin", f"{name}.shareholders"]
        await asyncio.gather(*(warm(cala, q, results) for q in chain_qs))

        owners = []
        res = await cala.query(f"Who owns {name}?")
        for row in res.rows[:3]:
            owner = row.get("owner") or row.get("parent") or row.get("name")
            if isinstance(owner, str) and owner.strip():
                owners.append(owner.strip())

        targets = [name, *owners]
        qs = [DIRECT_QUERY[c].format(e=t) for c in CONCERNS for t in targets]
        qs += [f"{o}.shareholders" for o in owners]
        qs += [f"Who owns {o}?" for o in owners]
        qs += [f"List every brand owned by {o}" for o in owners]
        await asyncio.gather(*(warm(cala, q, results) for q in qs))

    await cala.aclose()

    slow = sorted((r for r in results if r[0] >= SLOW_S), reverse=True)
    print(f"\n  {len(results)} queries, {len(results) - len(slow)} already warm")
    if slow:
        print(f"  {len(slow)} were cold and are now warm:")
        for secs, rows, query, err in slow:
            print(f"    {secs:6.1f}s  rows={rows:<3} {err or '':<12} {query[:60]}")
    print("\n  Run it twice. The second pass should show nothing cold.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["Nutella"]))
