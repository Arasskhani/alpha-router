"""Permanently deleting a user has to work on the database we actually ship.

``permanently_delete_user`` ended in ``DELETE FROM users``. On PostgreSQL that
statement is refused for most of the accounts an operator would ever want to
remove: four audit tables reference ``users.id`` with ``ON DELETE SET NULL`` and
carry a ``BEFORE UPDATE OR DELETE`` append-only trigger, and PostgreSQL runs
``SET NULL`` as a real UPDATE, which fires the trigger.

These tests run on SQLite too, where they check the anonymisation contract. The
trigger itself only exists on PostgreSQL, so the test that reproduces the
original failure is guarded on the dialect - run the suite with
``TEST_DATABASE_URL`` pointing at PostgreSQL to exercise it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.core.security import hash_password
from app.models.governance import GovernanceAuditEvent
from app.models.user import User
from app.services.agent_governance_service import append_governance_audit_event
from app.services.user_lifecycle_service import (
    PURGED_AUTH_PROVIDER,
    permanently_delete_user,
    soft_delete_user,
)


@pytest.fixture(autouse=True)
def no_object_storage(monkeypatch):
    def _purge(_slug, _user_id=None, **_kwargs) -> int:
        return 0

    monkeypatch.setattr(
        "app.services.user_account_cleanup_service.oss.purge_user_cdn_objects",
        _purge,
    )

    async def _unlink(_db, _path) -> None:
        return None

    monkeypatch.setattr("app.services.user_media_service.unlink_storage_if_unreferenced", _unlink)


async def _user(db_session, username: str = "doomed") -> User:
    row = User(
        username=username,
        email=f"{username}@example.test",
        display_name="Doomed Person",
        hashed_password=hash_password("a-password"),
        auth_provider="ldap",
        external_id="S-1-5-21-doomed",
        department="Engineering",
        job_title="Staff",
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _install_append_only_trigger(db_session) -> bool:
    """Recreate the production trigger when the test engine is PostgreSQL."""

    if db_session.get_bind().dialect.name != "postgresql":
        return False
    await db_session.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION alpharouter_reject_audit_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit table % is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    await db_session.execute(
        text(
            """
            CREATE TRIGGER trg_governance_audit_events_append_only
            BEFORE UPDATE OR DELETE ON governance_audit_events
            FOR EACH ROW EXECUTE FUNCTION alpharouter_reject_audit_mutation()
            """
        )
    )
    return True


async def test_an_audited_administrator_can_be_deleted(db_session):
    """The case that used to abort the transaction with 'audit table is append-only'."""

    user = await _user(db_session, "audited_admin")
    await append_governance_audit_event(
        db_session,
        event_type="agent.publish",
        resource_type="agent",
        resource_id="agent-1",
        actor_user_id=user.id,
    )
    await db_session.flush()
    on_postgres = await _install_append_only_trigger(db_session)

    await permanently_delete_user(db_session, user)
    await db_session.flush()

    events = (await db_session.execute(select(GovernanceAuditEvent))).scalars().all()
    assert len(events) == 1, "the audit event must survive"
    assert events[0].actor_user_id == user.id, (
        "the actor id is part of the hash chain; nulling it would make the event read as tampered"
    )
    if on_postgres:
        # Reaching here at all is the assertion: the trigger was live.
        assert True


async def test_everything_identifying_is_gone(db_session):
    user = await _user(db_session, "identifiable")
    user_id = user.id

    await permanently_delete_user(db_session, user)
    await db_session.flush()
    db_session.expunge_all()

    row = await db_session.get(User, user_id)
    assert row is not None, "the row anchors audit references and must remain"
    assert row.username == f"purged-user-{user_id}"
    assert row.email is None
    assert row.display_name is None
    assert row.hashed_password is None
    assert row.external_id is None
    assert row.auth_provider == PURGED_AUTH_PROVIDER
    assert row.department is None
    assert row.job_title is None
    assert row.totp_enabled is False
    assert row.totp_secret_encrypted is None
    assert row.is_active is False
    assert row.purged_at is not None
    assert row.deleted_at is not None


async def test_the_username_is_released(db_session):
    user = await _user(db_session, "reusable_name")
    await permanently_delete_user(db_session, user)
    await db_session.flush()

    replacement = User(
        username="reusable_name",
        hashed_password=hash_password("new-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(replacement)
    await db_session.flush()
    assert replacement.id != user.id


async def test_a_purged_row_is_in_neither_user_listing(db_session):
    from app.api.admin import _apply_user_list_filters

    live = await _user(db_session, "still_here")
    soft = await _user(db_session, "soft_deleted")
    purged = await _user(db_session, "purged_away")
    await soft_delete_user(db_session, soft)
    await permanently_delete_user(db_session, purged)
    await db_session.flush()

    def _names(rows) -> set[str]:
        return {row.username for row in rows}

    active_stmt = _apply_user_list_filters(
        select(User),
        q=None,
        username=None,
        email=None,
        department=None,
        job_title=None,
        role=None,
        is_active=None,
        group_id=None,
    )
    deleted_stmt = _apply_user_list_filters(
        select(User),
        q=None,
        username=None,
        email=None,
        department=None,
        job_title=None,
        role=None,
        is_active=None,
        group_id=None,
        deleted_only=True,
        active_only=False,
    )

    active = _names((await db_session.execute(active_stmt)).scalars().all())
    deleted = _names((await db_session.execute(deleted_stmt)).scalars().all())

    assert live.username in active
    assert soft.username in deleted
    assert f"purged-user-{purged.id}" not in active | deleted
