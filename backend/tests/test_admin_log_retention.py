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
from sqlalchemy.ext.asyncio import AsyncSession

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
async def db(db_session):
    """The shared test engine (see conftest), under the name this file grew up with."""
    return db_session


@pytest.fixture(autouse=True)
def no_object_storage(monkeypatch):
    """Permanent deletion purges the account's media; there is no bucket here."""

    def _purge(_slug, _user_id=None, **_kwargs) -> int:
        return 0

    monkeypatch.setattr("app.services.user_account_cleanup_service.oss.purge_user_cdn_objects", _purge)

    async def _unlink(_db, _path) -> None:
        return None

    monkeypatch.setattr("app.services.user_media_service.unlink_storage_if_unreferenced", _unlink)


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


class _Request:
    client = type("C", (), {"host": "203.0.113.9"})()
    headers: dict[str, str] = {}


async def _audit_rows(db: AsyncSession, action: str) -> list[SecurityAuditEvent]:
    return list(
        (await db.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == action))).scalars().all()
    )


async def test_changing_the_window_is_itself_audited(db):
    """A retention change destroys evidence later; it has to leave a record."""
    from app.api.admin import AdminLogRetentionSettingsPatch, patch_admin_log_retention_settings

    admin = await _admin(db, "retention_admin")
    await db.commit()

    await patch_admin_log_retention_settings(
        AdminLogRetentionSettingsPatch(detail_retention_days=30, event_retention_days=400),
        _Request(),
        db,
        admin,
    )

    rows = await _audit_rows(db, "admin_log_retention_changed")
    assert len(rows) == 1
    assert rows[0].actor_username == "retention_admin"
    assert rows[0].actor_ip == "203.0.113.9"
    detail = json.loads(rows[0].detail_json)
    assert detail.get("detail_retention_days") == 30 or "30" in rows[0].detail_json


async def test_saving_a_window_does_not_purge_immediately(db):
    """Unlike the raw-payload window next door. Shortening this one destroys
    audit evidence, so it must not happen as a side effect of pressing Save."""
    from app.api.admin import AdminLogRetentionSettingsPatch, patch_admin_log_retention_settings

    admin = await _admin(db, "hasty_admin")
    old = await _event(db, days_old=800)
    await db.commit()

    # A window far shorter than the row's age. If Save purged, this row would go.
    await patch_admin_log_retention_settings(
        AdminLogRetentionSettingsPatch(detail_retention_days=7, event_retention_days=7),
        _Request(),
        db,
        admin,
    )

    survivor = await db.get(SecurityAuditEvent, old.id)
    assert survivor is not None, "pressing Save destroyed audit evidence"
    assert survivor.detail_redacted_at is None


async def test_the_retention_run_records_itself_where_it_cannot_prune(db, session_factory, monkeypatch):
    """A retention pass that destroys evidence leaves evidence that it ran, in
    the governance chain - a trail this job never touches."""
    from app.models.governance import GovernanceAuditEvent
    from app.services import scheduler

    await _event(db, days_old=800)
    await set_admin_log_retention(db, detail_retention_days=7, event_retention_days=30)
    await db.commit()

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_factory)

    await scheduler.job_admin_log_retention()

    recorded = (
        (
            await db.execute(
                select(GovernanceAuditEvent).where(
                    GovernanceAuditEvent.event_type == "governance.retention.admin_logs.purged"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(recorded) == 1
    assert recorded[0].payload_json["events_deleted"] == 1


async def test_permanent_deletion_is_audited_before_the_row_disappears(db):
    """The record must carry the deleted account's *name*. permanently_delete_user
    tombstones the row - username and email are gone afterwards - so the audit
    row has to be written first, in the same transaction."""
    from app.api.admin import permanently_delete_user_endpoint
    from app.services.user_role_service import set_user_roles

    admin = await _admin(db, "the_deleter")
    await set_user_roles(db, admin, ["super_admin"])
    victim = await _admin(db, "soon_gone")
    victim.deleted_at = datetime.datetime.utcnow()
    await db.commit()

    await permanently_delete_user_endpoint(victim.id, _Request(), db, admin)

    rows = await _audit_rows(db, "user_permanently_deleted")
    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)
    assert detail["username"] == "soon_gone", "the record names an account that no longer has a name"
    purged = await db.get(User, victim.id)
    assert purged.username != "soon_gone", "and the row itself was tombstoned"


async def test_account_takeover_paths_are_audited(db):
    """Resetting a password, removing a second factor and bulk permanent
    deletion are account-takeover shaped however legitimate; each leaves a row."""
    from app.api.admin import (
        ResetPasswordIn,
        UsersPermanentDeleteIn,
        admin_disable_user_2fa,
        bulk_permanently_delete_users,
        reset_local_user_password,
    )
    from app.services.user_role_service import set_user_roles

    admin = await _admin(db, "root_operator")
    await set_user_roles(db, admin, ["super_admin"])
    target = await _admin(db, "the_target")
    target.totp_enabled = True
    target.totp_secret_encrypted = "enc"
    doomed = await _admin(db, "bulk_doomed")
    doomed.deleted_at = datetime.datetime.utcnow()
    await db.commit()

    await reset_local_user_password(
        target.id, ResetPasswordIn(password="a-long-enough-password"), _Request(), db, admin
    )
    await admin_disable_user_2fa(target.id, _Request(), db, admin)
    await bulk_permanently_delete_users(UsersPermanentDeleteIn(user_ids=[doomed.id]), _Request(), db, admin)

    for action in ("user_password_reset", "user_2fa_disabled", "users_permanently_deleted"):
        rows = await _audit_rows(db, action)
        assert len(rows) == 1, f"{action} left no audit row"
        assert rows[0].actor_username == "root_operator"
    reset_detail = json.loads((await _audit_rows(db, "user_password_reset"))[0].detail_json)
    assert "password" not in json.dumps(reset_detail).lower() or reset_detail.get("sessions_revoked") is True
