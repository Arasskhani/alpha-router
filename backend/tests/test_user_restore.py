"""Deleted Users is a waiting room, not a one-way door.

``soft_delete_user`` deleted every ``user_group_members`` row the account had,
and nothing snapshotted them, so the deletion was never reversible: an LDAP user
pruned by an OU change and picked up by the next sync came back with no groups,
and therefore no inherited budget plan, no group model access, and no group
knowledge or agent access. For a local account there was no way back at all -
``restore_directory_user`` existed but LDAP sync was its only caller, and
DeletedUsers offered permanent deletion and nothing else.

Memberships now survive, and ``app.services.group_membership`` is what keeps
"who is in this group" honest while they do.
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select

from app.core.security import hash_password
from app.models.user import User, UserGroup, user_group_members
from app.services.group_membership import live_member_counts_stmt, live_member_ids_stmt
from app.services.user_lifecycle_service import (
    permanently_delete_user,
    restore_user,
    soft_delete_user,
)


@pytest.fixture(autouse=True)
def no_object_storage(monkeypatch):
    def _purge(_slug, _user_id=None, **_kwargs) -> int:
        return 0

    monkeypatch.setattr("app.services.user_account_cleanup_service.oss.purge_user_cdn_objects", _purge)

    async def _unlink(_db, _path) -> None:
        return None

    monkeypatch.setattr("app.services.user_media_service.unlink_storage_if_unreferenced", _unlink)


async def _member(db_session, username: str) -> tuple[User, UserGroup]:
    group = UserGroup(name=f"group-for-{username}")
    db_session.add(group)
    user = User(
        username=username,
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(insert(user_group_members).values(user_id=user.id, group_id=group.id))
    await db_session.flush()
    return user, group


async def test_soft_delete_keeps_the_membership_rows(db_session):
    user, group = await _member(db_session, "temporarily_gone")

    await soft_delete_user(db_session, user)
    await db_session.flush()

    rows = (
        await db_session.execute(select(user_group_members.c.group_id).where(user_group_members.c.user_id == user.id))
    ).all()
    assert [r[0] for r in rows] == [group.id], "the membership was destroyed and cannot be restored"


async def test_a_deleted_user_is_not_a_member_for_anything_visible(db_session):
    user, group = await _member(db_session, "hidden_member")
    assert [r[0] for r in (await db_session.execute(live_member_ids_stmt(group.id))).all()] == [user.id]

    await soft_delete_user(db_session, user)
    await db_session.flush()

    assert (await db_session.execute(live_member_ids_stmt(group.id))).all() == []
    counts = dict((int(g), int(c)) for g, c in (await db_session.execute(live_member_counts_stmt([group.id]))).all())
    assert counts.get(group.id, 0) == 0


async def test_restore_brings_the_groups_back(db_session):
    user, group = await _member(db_session, "coming_back")
    await soft_delete_user(db_session, user)
    await db_session.flush()

    await restore_user(db_session, user)
    await db_session.flush()

    assert user.deleted_at is None
    assert user.is_active is True
    assert [r[0] for r in (await db_session.execute(live_member_ids_stmt(group.id))).all()] == [user.id]


async def test_soft_delete_ends_the_session_now(db_session):
    user, _group = await _member(db_session, "kicked_out")
    before = int(user.token_version or 0)

    await soft_delete_user(db_session, user)
    await db_session.flush()

    assert int(user.token_version) > before, "an existing JWT stayed valid until it expired"


async def test_a_purged_account_cannot_be_restored(db_session):
    user, _group = await _member(db_session, "gone_for_good")
    await soft_delete_user(db_session, user)
    await db_session.flush()
    await permanently_delete_user(db_session, user)
    await db_session.flush()

    with pytest.raises(ValueError, match="permanently deleted"):
        await restore_user(db_session, user)
