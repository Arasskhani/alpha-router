"""The administrative audit trail: readable, attributable, and prunable.

`security_audit_events` was written to from the day security settings shipped
and never read back - no endpoint, no page - while the Admin Guide told
operators the trail existed. These cover the three things that had to be true
before it could be shown: an event keeps its actor's name after that account is
gone, the retention windows behave the way an operator would predict, and
pruning never silently takes more than it was asked for.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services.admin_log_retention_service import (
    DEFAULT_DETAIL_RETENTION_DAYS,
    DEFAULT_EVENT_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    clamp_retention_days,
    get_admin_log_retention,
    purge_expired_admin_logs,
    set_admin_log_retention,
)
from app.services.security_audit import log_security_event


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _admin(db: AsyncSession, username: str = "root") -> User:
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _event(db: AsyncSession, *, days_old: int, action: str = "tls_activate") -> SecurityAuditEvent:
    row = SecurityAuditEvent(
        action=action,
        resource_type="tls_certificate",
        detail_json=json.dumps({"note": "x"}),
        created_at=datetime.datetime.utcnow() - datetime.timedelta(days=days_old),
    )
    db.add(row)
    await db.flush()
    return row


class TestActorIsWrittenOntoTheRow:
    async def test_the_actor_name_is_copied_not_joined(self, db):
        admin = await _admin(db, "alice")
        await log_security_event(
            db, actor=admin, actor_ip="10.0.0.1", action="tls_activate", resource_type="tls_certificate"
        )
        await db.commit()

        row = (await db.execute(select(SecurityAuditEvent))).scalars().one()
        assert row.actor_username == "alice"
        assert row.actor_email == "alice@test"

    async def test_the_trail_survives_deleting_the_administrator(self, db):
        """The whole reason the columns exist. actor_user_id is ON DELETE SET
        NULL and permanent deletion really does remove the row, so an event
        identified only by id forgets who did it."""
        admin = await _admin(db, "alice")
        await log_security_event(db, actor=admin, actor_ip=None, action="media_cleared_all", resource_type="storage")
        await db.commit()

        await db.delete(admin)
        await db.commit()

        row = (await db.execute(select(SecurityAuditEvent))).scalars().one()
        assert row.actor_username == "alice"

    async def test_an_unauthenticated_event_is_still_recorded(self, db):
        """saml_response_rejected has no actor; it must not blow up on one."""
        await log_security_event(
            db, actor=None, actor_ip="1.2.3.4", action="saml_response_rejected", resource_type="saml"
        )
        await db.commit()
        row = (await db.execute(select(SecurityAuditEvent))).scalars().one()
        assert row.actor_username is None and row.actor_ip == "1.2.3.4"


class TestWindows:
    @pytest.mark.parametrize(
        "value,expected",
        [(None, 90), ("", 90), ("abc", 90), (1, MIN_RETENTION_DAYS), (99999, MAX_RETENTION_DAYS), ("120", 120)],
    )
    def test_a_window_is_always_a_sane_number_of_days(self, value, expected):
        assert clamp_retention_days(value, default=90) == expected

    async def test_defaults_before_anything_is_saved(self, db):
        state = await get_admin_log_retention(db)
        assert state["detail_retention_days"] == DEFAULT_DETAIL_RETENTION_DAYS
        assert state["event_retention_days"] == DEFAULT_EVENT_RETENTION_DAYS

    async def test_detail_never_outlives_the_row(self, db):
        """Blanking detail on a row that is about to be deleted is meaningless,
        and the inverted pair reads as a misconfiguration."""
        saved = await set_admin_log_retention(db, detail_retention_days=300, event_retention_days=100)
        assert saved["detail_retention_days"] == 100
        assert saved["event_retention_days"] == 100

    async def test_each_window_can_be_saved_on_its_own(self, db):
        await set_admin_log_retention(db, detail_retention_days=30, event_retention_days=400)
        saved = await set_admin_log_retention(db, event_retention_days=500)
        assert saved["detail_retention_days"] == 30 and saved["event_retention_days"] == 500

    async def test_the_page_says_what_the_next_run_will_touch(self, db):
        await set_admin_log_retention(db, detail_retention_days=30, event_retention_days=60)
        await _event(db, days_old=90)
        await _event(db, days_old=45)
        await _event(db, days_old=1)
        await db.commit()

        state = await get_admin_log_retention(db)
        assert state["stored_events"] == 3
        assert state["expiring_details"] == 2
        assert state["expiring_events"] == 1


class TestPurge:
    async def test_detail_is_blanked_and_the_event_kept(self, db):
        """Who did what, when, survives; only the unbounded column goes."""
        await set_admin_log_retention(db, detail_retention_days=30, event_retention_days=3650)
        old = await _event(db, days_old=90)
        await db.commit()

        result = await purge_expired_admin_logs(db)
        assert result["details_redacted"] == 1
        assert result["events_deleted"] == 0

        await db.refresh(old)
        assert old.detail_json is None
        assert old.detail_redacted_at is not None
        assert old.action == "tls_activate" and old.created_at is not None

    async def test_recent_events_are_untouched(self, db):
        await set_admin_log_retention(db, detail_retention_days=30, event_retention_days=60)
        recent = await _event(db, days_old=1)
        await db.commit()

        await purge_expired_admin_logs(db)
        await db.refresh(recent)
        assert recent.detail_json is not None and recent.detail_redacted_at is None

    async def test_rows_past_the_longer_window_are_deleted(self, db):
        await set_admin_log_retention(db, detail_retention_days=10, event_retention_days=30)
        await _event(db, days_old=90)
        await _event(db, days_old=1)
        await db.commit()

        result = await purge_expired_admin_logs(db)
        assert result["events_deleted"] == 1
        assert (await db.execute(select(SecurityAuditEvent))).scalars().all().__len__() == 1

    async def test_running_twice_redacts_nothing_the_second_time(self, db):
        await set_admin_log_retention(db, detail_retention_days=30, event_retention_days=3650)
        await _event(db, days_old=90)
        await db.commit()

        first = await purge_expired_admin_logs(db)
        second = await purge_expired_admin_logs(db)
        assert first["details_redacted"] == 1
        assert second["details_redacted"] == 0

    async def test_an_empty_table_is_not_an_error(self, db):
        result = await purge_expired_admin_logs(db)
        assert result["details_redacted"] == 0 and result["events_deleted"] == 0


def test_changing_the_window_is_itself_audited():
    """A retention change destroys evidence later; it has to leave a record."""
    import inspect

    from app.api import admin

    source = inspect.getsource(admin)
    assert 'action="admin_log_retention_changed"' in source


def test_saving_a_window_does_not_purge_immediately():
    """Unlike the raw-payload window next door. Shortening this one destroys
    audit evidence, so it must not happen as a side effect of pressing Save."""
    import inspect

    from app.api import admin

    handler = inspect.getsource(admin.patch_admin_log_retention_settings)
    assert "purge_expired_admin_logs" not in handler


def test_the_retention_run_records_itself_where_it_cannot_prune():
    import inspect

    from app.services import scheduler

    source = inspect.getsource(scheduler.job_admin_log_retention)
    assert "governance.retention.admin_logs.purged" in source


def test_permanent_deletion_is_audited_before_the_row_disappears():
    """Reading username/email off a deleted instance is not reliable, so the
    record is written first, in the same transaction."""
    import inspect

    from app.api import admin

    handler = inspect.getsource(admin.permanently_delete_user_endpoint)
    assert handler.index("_audit_user_action") < handler.index("await permanently_delete_user(")


def test_account_takeover_paths_are_audited():
    import inspect

    from app.api import admin

    source = inspect.getsource(admin)
    for action in ("user_password_reset", "user_2fa_disabled", "users_permanently_deleted"):
        assert f'action="{action}"' in source
