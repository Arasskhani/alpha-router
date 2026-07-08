"""Lightweight per-user rate limiting for chat list/search endpoints."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException

_lock = Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, *, limit: int, window_seconds: int = 60) -> None:
    """Raise HTTP 429 when the user exceeds limit events per window."""
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        hits = _buckets[key]
        _buckets[key] = [t for t in hits if t > cutoff]
        if len(_buckets[key]) >= limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
        _buckets[key].append(now)


def prune_stale_buckets(max_age_seconds: int = 3600) -> None:
    """Drop idle bucket keys (optional housekeeping)."""
    now = time.monotonic()
    cutoff = now - max_age_seconds
    with _lock:
        stale = [k for k, hits in _buckets.items() if not hits or hits[-1] < cutoff]
        for k in stale:
            del _buckets[k]
