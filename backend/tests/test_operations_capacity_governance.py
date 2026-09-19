"""The Operations page reported a ceiling nobody enforces.

Two independent semaphores guard the same resource: the application's leased
semaphore in Redis and the broker's own ``SANDBOX_MAX_CONCURRENT``. Nothing ties
them together, so the smaller one decides. A page that shows only the
application's number tells the operator "200 available" while the broker refuses
everything past 50.
"""

from __future__ import annotations

import pytest

from app.api.operations import _effective_capacity


def _runtime(active: int, limit: int) -> dict:
    return {"active": active, "limit": limit, "available": max(0, limit - active)}


class TestEffectiveCeiling:
    def test_the_broker_wins_when_it_is_the_smaller_gate(self):
        out = _effective_capacity({}, _runtime(0, 200), {"status": "ok", "max_concurrent": 50})
        assert out["max_concurrent_turns"] == 50
        assert out["available"] == 50
        assert out["limited_by"] == "broker"
        assert out["mismatch"] is True

    def test_the_application_wins_when_it_is_the_smaller_gate(self):
        out = _effective_capacity({}, _runtime(0, 20), {"status": "ok", "max_concurrent": 200})
        assert out["max_concurrent_turns"] == 20
        assert out["limited_by"] == "app"
        assert out["mismatch"] is True

    def test_matching_gates_are_not_reported_as_a_mismatch(self):
        out = _effective_capacity({}, _runtime(0, 200), {"status": "ok", "max_concurrent": 200})
        assert out["limited_by"] == "both"
        assert out["mismatch"] is False

    @pytest.mark.parametrize("broker", [{"status": "unavailable"}, {"status": "not_configured"}, {}])
    def test_an_unreadable_broker_leaves_the_application_ceiling_alone(self, broker):
        """Not knowing the other gate is not the same as it being zero: the page
        keeps reporting what it can actually verify."""
        out = _effective_capacity({}, _runtime(5, 200), broker)
        assert out["max_concurrent_turns"] == 200
        assert out["broker_max_concurrent"] is None
        assert out["mismatch"] is False

    def test_utilisation_is_measured_against_the_ceiling_that_binds(self):
        out = _effective_capacity({}, _runtime(25, 200), {"status": "ok", "max_concurrent": 50})
        assert out["utilization_percent"] == 50.0

    def test_available_never_goes_negative(self):
        """Leases taken before the broker ceiling dropped can exceed it."""
        out = _effective_capacity({}, _runtime(80, 200), {"status": "ok", "max_concurrent": 50})
        assert out["available"] == 0
