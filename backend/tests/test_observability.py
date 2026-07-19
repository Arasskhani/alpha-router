"""Phase 10: bounded, non-sensitive observability counters."""

from app.services.observability import increment, reset, snapshot


def test_observability_exposes_only_known_counters():
    reset()
    increment("redis_fallback")
    increment("user_controlled_label")

    counters = snapshot()
    assert counters["redis_fallback"] == 1
    assert counters["csrf_failure"] == 0
    assert "user_controlled_label" not in counters
    reset()

