"""Disk cache for Cala answers.

This is not an optimisation, it is the product. A cold Cala query costs 16-75s;
the same query afterwards costs about 0.5s, forever. Every dig any player runs
makes the next player's dig faster, so the cache is shared, permanent and warmed
deliberately before a demo.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import threading
from typing import Any

from .config import settings

_lock = threading.Lock()
_dir = pathlib.Path(settings.cache_dir)
_dir.mkdir(parents=True, exist_ok=True)


def _path(kind: str, text: str) -> pathlib.Path:
    return _dir / f"{kind}-{hashlib.sha1(text.encode()).hexdigest()[:16]}.json"


def get(kind: str, text: str) -> dict[str, Any] | None:
    p = _path(kind, text)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def put(kind: str, text: str, payload: Any, latency_s: float) -> None:
    with _lock:
        try:
            _path(kind, text).write_text(
                json.dumps({"payload": payload, "latency": latency_s}, ensure_ascii=False)
            )
        except Exception:
            pass


def size() -> int:
    return len(list(_dir.glob("*.json")))
