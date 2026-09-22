"""Sign-in history is kept for a configurable period, whole, and then goes.

The window has a floor of 90 days and does not redact anything ahead of the
row. Both are deliberate departures from the administrative trail's policy,
and both are asserted here so that copying that policy back over this one
would fail loudly.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_event import AuthEvent
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services.auth_event_retention_service import (
    DEFAULT_RETENTION_DAYS,
    KEY_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    clamp_retention_days,
    get_auth_event_retention,
    purge_expired_auth_events,
    set_auth_event_retention_days,
)


@pytest.fixture
async def db(db_session):
    return db_session


async def _admin(db: AsyncSession, username: str = "root") -> User:
    user = User(username=username, email=f"{username}@test", hashed_password="x", auth_provider="local", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _event(db: AsyncSession, *, days_old: int, **overrides) -> AuthEvent:
    fields = dict(
        occurred_at=datetime.datetime.utcnow() - datetime.timedelta(days=days_old),
        username="alice",
        event_type="login_failed",
        outcome="failure",
        reason_code="bad_password",
        reason_detail="Invalid credentials",
        ip="203.0.113.7",
    )
    fields.update(overrides)
    row = AuthEvent(**fields)
    db.add(row)
    await db.flush()
    return row


class TestWindow:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, DEFAULT_RETENTION_DAYS),
            ("", DEFAULT_RETENTION_DAYS),
            ("abc", DEFAULT_RETENTION_DAYS),
            (7, MIN_RETENTION_DAYS),
            (89, MIN_RETENTION_DAYS),
            (99999, MAX_RETENTION_DAYS),
            ("120", 120),
        ],
    )
    def test_a_window_is_always_a_sane_number_of_days(self, value, expected):
        assert clamp_retention_days(value) == expected

    def test_the_floor_is_a_quarter_not_a_week(self):
        """The administrative trail allows 7. Sign-in records are what an
        incident review and PCI DSS 10.7 ask for first; a typo must not be
        able to discard the quarter an auditor will ask about."""
        assert MIN_RETENTION_DAYS == 90
        assert DEFAULT_RETENTION_DAYS == 365

    async def test_default_before_anything_is_saved(self, db):
        assert (await get_auth_event_retention(db))["retention_days"] == DEFAULT_RETENTION_DAYS

    async def test_saving_persists_and_clamps(self, db):
        saved = await set_auth_event_retention_days(db, 30)
        assert saved["retention_days"] == MIN_RETENTION_DAYS
        saved = await set_auth_event_retention_days(db, 730)
        assert saved["retention_days"] == 730
        assert (await get_auth_event_retention(db))["retention_days"] == 730

    async def test_a_value_written_around_the_api_is_still_clamped_on_read(self, db):
        """Someone editing system_settings by hand cannot get below the floor."""
        from app.models.system import SystemSetting

        db.add(SystemSetting(key=KEY_RETENTION_DAYS, value="3"))
        await db.flush()
        assert (await get_auth_event_retention(db))["retention_days"] == MIN_RETENTION_DAYS

    async def test_the_page_says_what_the_next_run_will_delete(self, db):
        await set_auth_event_retention_days(db, 100)
        await _event(db, days_old=400)
        await _event(db, days_old=101)
        await _event(db, days_old=1)
        await db.commit()

        state = await get_auth_event_retention(db)
        assert state["stored_events"] == 3
        assert state["expiring_events"] == 2
        assert "expiring_details" not in state, "there is no detail window on this table"


class TestPurge:
    async def test_rows_past_the_window_go_and_recent_rows_stay_whole(self, db):
        await set_auth_event_retention_days(db, 90)
        await _event(db, days_old=200)
        recent = await _event(db, days_old=10)
        await db.commit()

        result = await purge_expired_auth_events(db)
        assert result == {"retention_days": 90, "events_deleted": 1}

        rows = (await db.execute(select(AuthEvent))).scalars().all()
        assert [r.id for r in rows] == [recent.id]
        # Nothing on the surviving row was redacted: the reason lives exactly
        # as long as the fact. This is the defect the table was made to fix.
        assert rows[0].reason_code == "bad_password"
        assert rows[0].reason_detail == "Invalid credentials"
        assert rows[0].ip == "203.0.113.7"

    async def test_a_row_inside_the_window_is_never_touched_in_any_column(self, db):
        """The service has no UPDATE in it. If someone adds an early-redaction
        step, this is the test that notices."""
        await set_auth_event_retention_days(db, 3650)
        row = await _event(db, days_old=1000, user_agent="Mozilla/5.0", session_id="abc", correlation_id="c1")
        await db.commit()
        before = {c.name: getattr(row, c.name) for c in AuthEvent.__table__.columns}

        await purge_expired_auth_events(db)
        await db.refresh(row)
        after = {c.name: getattr(row, c.name) for c in AuthEvent.__table__.columns}
        assert after == before

    async def test_backfilled_rows_age_like_any_other(self, db):
        await set_auth_event_retention_days(db, 90)
        await _event(db, days_old=500, backfilled=True, source_event_id=12345)
        await db.commit()

        assert (await purge_expired_auth_events(db))["events_deleted"] == 1

    async def test_running_twice_deletes_nothing_the_second_time(self, db):
        await set_auth_event_retention_days(db, 90)
        await _event(db, days_old=500)
        await db.commit()

        assert (await purge_expired_auth_events(db))["events_deleted"] == 1
        assert (await purge_expired_auth_events(db))["events_deleted"] == 0

    async def test_a_large_backlog_is_removed_in_batches(self, db, monkeypatch):
        from app.services import auth_event_retention_service as svc

        monkeypatch.setattr(svc, "_PURGE_BATCH_SIZE", 3)
        await set_auth_event_retention_days(db, 90)
        for _ in range(7):
            await _event(db, days_old=200)
        await db.commit()

        assert (await purge_expired_auth_events(db))["events_deleted"] == 7
        assert (await db.execute(select(AuthEvent))).scalars().all() == []

    async def test_an_empty_table_is_not_an_error(self, db):
        assert (await purge_expired_auth_events(db))["events_deleted"] == 0


class _Request:
    client = type("C", (), {"host": "203.0.113.9"})()
    headers: dict[str, str] = {}


async def test_changing_the_window_is_itself_audited(db):
    from app.api.admin import SignInActivityRetentionSettingsPatch, patch_sign_in_activity_retention_settings

    admin = await _admin(db, "retention_admin")
    await db.commit()

    response = await patch_sign_in_activity_retention_settings(
        SignInActivityRetentionSettingsPatch(retention_days=400), _Request(), db, admin
    )
    assert response["sign_in_activity"]["retention_days"] == 400

    rows = (
        (
            await db.execute(
                select(SecurityAuditEvent).where(SecurityAuditEvent.action == "sign_in_activity_retention_changed")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].actor_username == "retention_admin"
    assert rows[0].actor_ip == "203.0.113.9"
    assert rows[0].resource_type == "auth_events"
    detail = json.loads(rows[0].detail_json)
    assert detail == {"retention_days": 400, "previous_retention_days": DEFAULT_RETENTION_DAYS}


def test_the_api_refuses_a_window_below_the_floor():
    """The schema and the service agree on the floor, so a 30-day request is a
    422 rather than a silent clamp the operator never sees."""
    from pydantic import ValidationError

    from app.api.admin import SignInActivityRetentionSettingsPatch

    with pytest.raises(ValidationError):
        SignInActivityRetentionSettingsPatch(retention_days=30)
    assert SignInActivityRetentionSettingsPatch(retention_days=MIN_RETENTION_DAYS).retention_days == 90


async def test_saving_a_shorter_window_does_not_purge_immediately(db):
    from app.api.admin import SignInActivityRetentionSettingsPatch, patch_sign_in_activity_retention_settings

    admin = await _admin(db, "hasty_admin")
    old = await _event(db, days_old=800)
    await db.commit()

    await patch_sign_in_activity_retention_settings(
        SignInActivityRetentionSettingsPatch(retention_days=90), _Request(), db, admin
    )
    assert await db.get(AuthEvent, old.id) is not None, "pressing Save destroyed sign-in evidence"


async def test_the_retention_run_records_itself_where_it_cannot_prune(db, session_factory, monkeypatch):
    from app.models.governance import GovernanceAuditEvent
    from app.services import scheduler

    await _event(db, days_old=800)
    await set_auth_event_retention_days(db, 90)
    await db.commit()

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_factory)
    await scheduler.job_auth_event_retention()

    recorded = (
        (
            await db.execute(
                select(GovernanceAuditEvent).where(
                    GovernanceAuditEvent.event_type == "governance.retention.auth_events.purged"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(recorded) == 1
    assert recorded[0].payload_json["events_deleted"] == 1
    assert (await db.execute(select(AuthEvent))).scalars().all() == []


async def test_the_job_is_scheduled_nightly():
    """The window is only a promise if something applies it."""
    import inspect

    from app.services import scheduler

    source = inspect.getsource(scheduler)
    assert 'id="auth_event_retention"' in source
    assert "job_auth_event_retention," in source


async def test_the_retention_policy_page_receives_the_block(db):
    """``GET /api/admin/storage`` is what the Retention Policy page renders."""
    from app.api.admin import get_storage_overview

    stats = await get_storage_overview(db=db, _=await _admin(db, "viewer"))
    block = stats["sign_in_activity"]
    assert block["retention_days"] == DEFAULT_RETENTION_DAYS
    assert block["min_days"] == MIN_RETENTION_DAYS
    assert block["stored_events"] == 0
