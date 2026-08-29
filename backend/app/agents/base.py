from __future__ import annotations

from typing import Any

from ..clients.cala import CalaResult
from ..schemas import Source


def source_of(res: CalaResult) -> Source:
    return Source(
        query=res.query,
        endpoint=res.endpoint,  # type: ignore[arg-type]
        latency_s=res.latency_s,
        cached=res.cached,
        documents=res.documents,
        fact_ids=res.fact_ids,
    )


def first_name(row: dict[str, Any]) -> str:
    for k in ("owner", "ultimate_owner", "shareholder", "name", "brand", "manufacturer",
              "empresa", "factory_group"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return next((str(v) for v in row.values() if isinstance(v, str) and v.strip()), "unknown")


def detail_lines(rows: list[dict[str, Any]], limit: int = 8) -> list[str]:
    """Flatten Cala rows into readable lines without inventing anything."""
    out: list[str] = []
    for row in rows[:limit]:
        name = first_name(row)
        extras = []
        for k in ("role", "type", "relationship", "products", "producto_categoria",
                  "datos_relevantes", "description", "detail", "category"):
            v = row.get(k)
            if isinstance(v, str) and v.strip() and v.strip() != name:
                extras.append(v.strip())
        for k in ("ownership_percent", "stake_percent"):
            v = row.get(k)
            if v not in (None, ""):
                extras.insert(0, f"{v}%" if not str(v).endswith("%") else str(v))
        out.append(f"{name} — {' · '.join(extras)}" if extras else name)
    return out
