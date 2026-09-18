"""Changing someone's privileges is recorded.

Role assignment is the most consequential administrative action in the product
and was not audited at all - while ``model_access_changed``, written from the
same file, was. Every path that replaces a user's role set now records who
changed it, for whom, and what it was before.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.api.admin import UsersBulkIn, _audit_role_change, bulk_update_users
from app.core.security import hash_password
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services.rbac import SUPER_ADMIN_SLUG
from app.services.user_role_service import set_user_roles


class _Request:
    client = type("C", (), {"host": "198.51.100.4"})()
    headers: dict[str, str] = {}


async def _person(db_session, username: str, slugs: list[str]) -> User:
    row = User(
        username=username,
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(row)
    await db_session.flush()
    await set_user_roles(db_session, row, slugs)
    await db_session.flush()
    return row


async def _rows(db_session) -> list[SecurityAuditEvent]:
    return list(
        (await db_session.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == "user_roles_changed")))
        .scalars()
        .all()
    )


async def test_a_role_change_records_before_and_after(db_session):
    actor = await _person(db_session, "auditing_admin", [SUPER_ADMIN_SLUG])
    target = await _person(db_session, "the_promoted", ["user"])

    await _audit_role_change(
        db_session,
        _Request(),
        actor,
        user=target,
        previous=["user"],
        new=["reports_full_administrator"],
    )
    await db_session.flush()

    rows = await _rows(db_session)
    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)
    assert detail["previous_roles"] == ["user"]
    assert detail["new_roles"] == ["reports_full_administrator"]
    assert rows[0].actor_username == "auditing_admin"
    assert rows[0].actor_ip == "198.51.100.4"


async def test_a_no_op_writes_nothing(db_session):
    """Re-applying the roles someone already has is not a privilege change."""

    actor = await _person(db_session, "quiet_admin", [SUPER_ADMIN_SLUG])
    target = await _person(db_session, "unchanged_person", ["user"])

    await _audit_role_change(db_session, _Request(), actor, user=target, previous=["user"], new=["user"])
    await db_session.flush()

    assert await _rows(db_session) == []


async def test_the_bulk_path_records_each_user(db_session):
    actor = await _person(db_session, "bulk_admin", [SUPER_ADMIN_SLUG])
    first = await _person(db_session, "bulk_one", ["user"])
    second = await _person(db_session, "bulk_two", ["user"])

    await bulk_update_users(
        UsersBulkIn(user_ids=[first.id, second.id], roles=["reports_full_administrator"]),
        _Request(),
        db_session,
        actor,
    )
    await db_session.flush()

    rows = await _rows(db_session)
    assert len(rows) == 2
    assert {json.loads(r.detail_json)["username"] for r in rows} == {"bulk_one", "bulk_two"}
