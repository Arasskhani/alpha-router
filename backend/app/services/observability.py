"""Low-overhead process observability counters for security/operations signals.

Counters are intentionally in-process and bounded to a fixed allowlist. They
are a diagnostic supplement, not a replacement for fleet-wide metrics.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock

_KNOWN_EVENTS = frozenset(
    {
        "redis_fallback",
        "broker_failure",
        "ssrf_block",
        "csrf_failure",
        "repeated_401",
        "budget_hold_leak",
        "docs_denied",
        "production_guard_warning",
    }
)
_lock = Lock()
_counts: Counter[str] = Counter()


def increment(event: str) -> None:
    """Increment a known event without accepting user-controlled labels."""
    if event not in _KNOWN_EVENTS:
        return
    with _lock:
        _counts[event] += 1


def snapshot() -> dict[str, int]:
    """Return all known counters, including events still at zero."""
    with _lock:
        return {event: int(_counts.get(event, 0)) for event in sorted(_KNOWN_EVENTS)}


def reset() -> None:
    """Test hook to reset process counters."""
    with _lock:
        _counts.clear()
