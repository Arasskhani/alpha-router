"""An organisation must not be able to lock itself out of its own admin panel.

Two guards protect that: the one that refuses to demote the last Full
Administrator, and the one that refuses to delete them. Both used a count that
included accounts nobody can sign in to, so with two Super Admins, soft-deleting
one and then deleting the other was allowed and left zero live administrators.
"""

from __future__ import annotations

import datetime

import pytest

from app.core.security import hash_password
from app.models.user import User
from app.services.rbac import SUPER_ADMIN_SLUG
from app.services.user_lifecycle_service import permanently_delete_user, soft_delete_user
from app.services.user_role_service import count_active_full_administrators, set_user_roles


@pytest.fixture(autouse=True)
def no_object_storage(monkeypatch):
    """Permanent deletion reaches out to object storage; this test is about the guard."""

    def _purge(_slug, _user_id=None, **_kwargs) -> int:
        return 0

    monkeypatch.setattr(
        "app.services.user_account_cleanup_service.oss.purge_user_cdn_objects",
        _purge,
    )

    async def _unlink(_db, _path) -> None:
        return None

    monkeypatch.setattr("app.services.user_media_service.unlink_storage_if_unreferenced", _unlink)


async def _admin(db_session, username: str) -> User:
    row = User(
        username=username,
        hashed_password=hash_password("admin-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    await set_user_roles(db_session, row, [SUPER_ADMIN_SLUG])
    return row


async def test_a_soft_deleted_administrator_does_not_count(db_session):
    first = await _admin(db_session, "admin_one")
    second = await _admin(db_session, "admin_two")
    assert await count_active_full_administrators(db_session) == 2

    await soft_delete_user(db_session, second)
    await db_session.flush()
    assert await count_active_full_administrators(db_session) == 1, (
        "an account with deleted_at set cannot sign in and must not be counted"
    )

    with pytest.raises(ValueError, match="last Full Administrator"):
        await permanently_delete_user(db_session, first)


async def test_a_disabled_administrator_does_not_count(db_session):
    first = await _admin(db_session, "admin_active")
    second = await _admin(db_session, "admin_disabled")
    second.is_active = False
    await db_session.flush()

    assert await count_active_full_administrators(db_session) == 1
    with pytest.raises(ValueError, match="last Full Administrator"):
        await permanently_delete_user(db_session, first)


async def test_two_live_administrators_allow_one_to_go(db_session):
    first = await _admin(db_session, "admin_keeper")
    second = await _admin(db_session, "admin_leaver")
    assert await count_active_full_administrators(db_session) == 2

    await permanently_delete_user(db_session, second)
    await db_session.flush()
    assert await count_active_full_administrators(db_session) == 1
    assert first.deleted_at is None


async def test_the_count_is_one_query_not_one_per_user(db_session):
    """The guard runs on the deletion path; it used to walk every user row."""

    for index in range(6):
        await _admin(db_session, f"admin_bulk_{index}")
    plain = User(
        username="plain_user",
        hashed_password=hash_password("user-password"),
        auth_provider="local",
        is_active=True,
        created_at=datetime.datetime.utcnow(),
    )
    db_session.add(plain)
    await db_session.flush()

    statements: list[str] = []
    from sqlalchemy import event

    def _record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    sync_engine = db_session.get_bind()
    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        assert await count_active_full_administrators(db_session) == 6
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, f"expected one query, got {len(selects)}: {selects}"
