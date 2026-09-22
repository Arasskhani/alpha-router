"""A session that ends without a sign-out still leaves a row.

Nine places bump ``users.token_version``, which signs the person out of every
device on their next request. Only the explicit sign-out was recorded, so an
administrator reading the sign-in history saw an account that "never signed
out" and could no longer do anything, with no explanation between the two.

``session_revoked`` is that explanation. These tests run against the database
rather than a spy, because the row is meant to ride the transaction that did
the revoking: if the deactivation rolls back, so must the record of it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.auth_event import AuthEvent
from app.services import user_lifecycle_service as lifecycle


def _request() -> MagicMock:
    request = MagicMock()
    request.headers = {"user-agent": "spec"}
    request.client = SimpleNamespace(host="198.51.100.9")
    request.cookies = {}
    return request


@pytest.fixture(autouse=True)
def no_object_storage(monkeypatch):
    """Permanent deletion purges the account's media; there is no bucket here."""

    def _purge(_slug, _user_id=None, **_kwargs) -> int:
        return 0

    monkeypatch.setattr("app.services.user_account_cleanup_service.oss.purge_user_cdn_objects", _purge)

    async def _unlink(_db, _path) -> None:
        return None

    monkeypatch.setattr("app.services.user_media_service.unlink_storage_if_unreferenced", _unlink)


async def _revocations(db) -> list[AuthEvent]:
    rows = (await db.execute(select(AuthEvent).order_by(AuthEvent.id))).scalars().all()
    return [r for r in rows if r.event_type == "session_revoked"]


async def test_11a_soft_deleting_an_account(db_session, user):
    await lifecycle.soft_delete_user(db_session, user)
    await db_session.commit()
    rows = await _revocations(db_session)
    assert len(rows) == 1
    assert rows[0].reason_code == "user_deleted"
    assert rows[0].user_id == user.id
    assert rows[0].username == user.username
    assert rows[0].scope == "all_sessions"
    # No request reaches this service; the row is honest about it.
    assert rows[0].ip is None


async def test_11b_permanent_deletion_keeps_the_name_it_is_about_to_erase(db_session, user, admin):
    """The users row survives but is blanked; the snapshot is taken first."""
    name = user.username
    await lifecycle.permanently_delete_user(db_session, user)
    await db_session.commit()
    rows = await _revocations(db_session)
    assert [r.reason_code for r in rows] == ["user_deleted"]
    assert rows[0].username == name
    await db_session.refresh(user)
    assert user.username != name, "the account itself was emptied"


async def test_11c_a_revocation_rolls_back_with_the_change_that_caused_it(db_session, user):
    await lifecycle.soft_delete_user(db_session, user)
    await db_session.rollback()
    assert await _revocations(db_session) == []


async def test_11d_deactivation_by_an_administrator(db_session, user, admin):
    from app.api import admin as admin_api

    body = admin_api.UserAdminPatch(is_active=False)
    with patch.object(admin_api, "_audit_user_action", AsyncMock()):
        await admin_api.patch_user(user.id, body, _request(), db=db_session, actor=admin)
    rows = await _revocations(db_session)
    assert [r.reason_code for r in rows] == ["user_deactivated"]
    assert rows[0].ip == "198.51.100.9"
    await db_session.refresh(user)
    assert user.is_active is False


async def test_11e_an_administrators_password_reset(db_session, user, admin):
    from app.api import admin as admin_api

    body = SimpleNamespace(password="Str0ng!Passw0rd#2026")
    with patch.object(admin_api, "_audit_user_action", AsyncMock()):
        await admin_api.reset_local_user_password(user.id, body, _request(), db=db_session, admin=admin)
    rows = await _revocations(db_session)
    assert [r.reason_code for r in rows] == ["admin_password_reset"]


async def test_11f_an_administrator_disabling_a_second_factor(db_session, user, admin):
    from app.api import admin as admin_api

    user.totp_enabled = True
    user.totp_secret_encrypted = "enc"
    await db_session.commit()
    with patch.object(admin_api, "_audit_user_action", AsyncMock()), patch("app.services.totp_service.audit"):
        await admin_api.admin_disable_user_2fa(user.id, _request(), db=db_session, actor=admin)
    rows = await _revocations(db_session)
    assert [r.reason_code for r in rows] == ["admin_2fa_disabled"]


async def test_11g_a_person_changing_their_own_password(db_session, user):
    from app.api import user_settings

    user.hashed_password = hash_password("Old!Passw0rd#2026")
    await db_session.commit()
    body = SimpleNamespace(
        current_password="Old!Passw0rd#2026",
        new_password="New!Passw0rd#2026",
        confirm_password="New!Passw0rd#2026",
    )
    with (
        patch.object(user_settings, "check_rate_limit", AsyncMock()),
        patch.object(user_settings, "set_session_cookies"),
        patch.object(user_settings, "audit"),
    ):
        await user_settings.change_password(body, _request(), MagicMock(), user=user, db=db_session)
    rows = await _revocations(db_session)
    assert [r.reason_code for r in rows] == ["password_changed"]
    assert rows[0].auth_method == "local"
