"""The Operations capacity control: what it records, and what it reports.

Two defects this covers.

The first is that changing these limits left no trace. The three numbers decide
whether the platform runs code at all - setting the global ceiling to 1 takes
Code Interpreter away from every user - and the write went straight to
``SystemSetting`` with nothing in the audit trail. Every comparable
administrative act in this product is recorded; this one was not.

The second is that the page reported a ceiling nobody enforces. Two independent
semaphores guard the same resource: the application's leased semaphore in Redis
and the broker's own ``SANDBOX_MAX_CONCURRENT``. Nothing ties them together, so
the smaller one decides. A page that shows only the application's number tells
the operator "200 available" while the broker refuses everything past 50.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.api.operations import _effective_capacity, patch_code_interpreter_capacity
from app.api.operations import CodeInterpreterCapacityPatch
from app.models.security import SecurityAuditEvent
from app.services import code_interpreter_capacity_service as caps


class _Request:
    def __init__(self, host: str = "203.0.113.9") -> None:
        self.client = type("C", (), {"host": host})()
        self.headers: dict[str, str] = {}


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


async def _patch(db, admin, monkeypatch, **body):
    """Call the endpoint with Redis and the broker stubbed out."""

    async def fake_stats():
        return {"active": 0, "limit": int(body.get("max_concurrent_turns") or 200), "available": 0}

    async def fake_sync(_db):
        from app.services.code_interpreter_capacity_service import get_code_interpreter_capacity_policy

        return await get_code_interpreter_capacity_policy(_db)

    monkeypatch.setattr(caps, "code_interpreter_capacity_stats", fake_stats)
    monkeypatch.setattr(caps, "sync_code_interpreter_capacity_policy", fake_sync)
    return await patch_code_interpreter_capacity(
        body=CodeInterpreterCapacityPatch(**body),
        request=_Request(),
        db=db,
        admin=admin,
    )


class TestCapacityChangeIsAudited:
    async def test_the_trail_records_who_changed_it_and_from_what(self, db_session, admin, monkeypatch):
        await _patch(
            db_session, admin, monkeypatch, max_concurrent_turns=200, max_per_subject=2, retry_after_seconds=30
        )
        await _patch(db_session, admin, monkeypatch, max_concurrent_turns=1, max_per_subject=1, retry_after_seconds=60)

        events = (await db_session.execute(select(SecurityAuditEvent).order_by(SecurityAuditEvent.id))).scalars().all()
        assert [e.action for e in events] == ["code_interpreter_capacity_changed"] * 2
        assert events[-1].resource_type == "code_interpreter"
        assert events[-1].actor_username == admin.username
        assert events[-1].actor_ip == "203.0.113.9"
        detail = json.loads(events[-1].detail_json)
        assert detail["before"]["global_max"] == 200
        assert detail["after"]["global_max"] == 1
        assert detail["after"]["retry_after_seconds"] == 60

    async def test_the_event_names_only_what_this_endpoint_can_change(self, db_session, admin, monkeypatch):
        """The environment ceilings travel in the same policy dict and cannot be
        changed here; recording them in every event is noise."""
        await _patch(db_session, admin, monkeypatch, max_concurrent_turns=5, max_per_subject=2, retry_after_seconds=30)
        event = (await db_session.execute(select(SecurityAuditEvent))).scalars().one()
        detail = json.loads(event.detail_json)
        assert set(detail["after"]) == {"global_max", "per_subject_max", "retry_after_seconds", "enabled"}

    async def test_turning_it_off_and_on_is_named_as_such_in_the_trail(self, db_session, admin, monkeypatch):
        """One action name for "tweaked a ceiling" and for "took the feature away
        from everyone" makes the two impossible to tell apart when reading the
        trail, which is exactly when it matters."""
        await _patch(db_session, admin, monkeypatch, enabled=False)
        await _patch(db_session, admin, monkeypatch, enabled=True)
        events = (await db_session.execute(select(SecurityAuditEvent).order_by(SecurityAuditEvent.id))).scalars().all()
        assert [e.action for e in events] == ["code_interpreter_disabled", "code_interpreter_enabled"]
        assert json.loads(events[0].detail_json)["after"]["enabled"] == 0

    async def test_the_change_and_its_audit_row_land_together(self, db_session, admin, monkeypatch):
        """Same transaction: a saved limit with no event, or an event for a save
        that did not happen, are both worse than either alone."""
        from app.services.code_interpreter_capacity_service import get_code_interpreter_capacity_policy

        await _patch(db_session, admin, monkeypatch, max_concurrent_turns=7, max_per_subject=3, retry_after_seconds=15)
        policy = await get_code_interpreter_capacity_policy(db_session)
        assert policy["global_max"] == 7
        assert (await db_session.execute(select(SecurityAuditEvent))).scalars().one() is not None
