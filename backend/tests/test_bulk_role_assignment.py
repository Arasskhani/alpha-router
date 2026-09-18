"""Assigning roles in bulk can express more than one role.

``set_user_roles`` replaces the user's whole role set - that is its documented
contract. The bulk endpoint accepted a single scalar ``role``, and the Roles
page, whose own copy invites the administrator to "select one or more roles …
apply them", posted one slug.

So assigning "Reports" to someone who also held "API Logs" removed "API Logs".
Silently: no confirmation, no undo, no audit row, and a flash message that said
only how many users were changed. The single-user endpoint already accepted a
list; only the bulk one could not express what the page offered.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.admin import UsersBulkIn, bulk_update_users


from app.core.security import hash_password
from app.models.user import User
from app.services.rbac import SUPER_ADMIN_SLUG
from app.services.user_role_service import get_user_role_slugs, set_user_roles


class _Request:
    """Enough of a Request for the audit row's client IP."""

    client = type("C", (), {"host": "203.0.113.10"})()
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


async def _actor(db_session) -> User:
    return await _person(db_session, "the_admin", [SUPER_ADMIN_SLUG])


async def test_several_roles_can_be_assigned_at_once(db_session):
    actor = await _actor(db_session)
    target = await _person(db_session, "multi", ["reports_full_administrator"])

    await bulk_update_users(
        UsersBulkIn(user_ids=[target.id], roles=["reports_full_administrator", "api_keys_full_administrator"]),
        _Request(),
        db_session,
        actor,
    )
    await db_session.flush()

    assert sorted(await get_user_role_slugs(db_session, target.id)) == sorted(
        ["reports_full_administrator", "api_keys_full_administrator"]
    )


async def test_the_set_is_replaced_not_merged(db_session):
    """Replacement is the contract; the page now says so, but it must still hold."""

    actor = await _actor(db_session)
    target = await _person(db_session, "replaced", ["reports_full_administrator", "api_keys_full_administrator"])

    await bulk_update_users(
        UsersBulkIn(user_ids=[target.id], roles=["reports_full_administrator"]), _Request(), db_session, actor
    )
    await db_session.flush()

    assert await get_user_role_slugs(db_session, target.id) == ["reports_full_administrator"]


async def test_duplicates_in_the_request_collapse(db_session):
    actor = await _actor(db_session)
    target = await _person(db_session, "deduped", ["user"])

    await bulk_update_users(
        UsersBulkIn(user_ids=[target.id], roles=["reports_full_administrator", "reports_full_administrator"]),
        _Request(),
        db_session,
        actor,
    )
    await db_session.flush()

    assert await get_user_role_slugs(db_session, target.id) == ["reports_full_administrator"]


async def test_an_empty_list_is_refused(db_session):
    actor = await _actor(db_session)
    target = await _person(db_session, "unchanged", ["reports_full_administrator"])

    with pytest.raises(HTTPException) as exc:
        await bulk_update_users(UsersBulkIn(user_ids=[target.id], roles=[]), _Request(), db_session, actor)
    assert exc.value.status_code == 400
    assert await get_user_role_slugs(db_session, target.id) == ["reports_full_administrator"]


async def test_the_scalar_field_still_works(db_session):
    """Existing callers post ``role``; they must keep working."""

    actor = await _actor(db_session)
    target = await _person(db_session, "legacy_caller", ["user"])

    await bulk_update_users(
        UsersBulkIn(user_ids=[target.id], role="reports_full_administrator"), _Request(), db_session, actor
    )
    await db_session.flush()

    assert await get_user_role_slugs(db_session, target.id) == ["reports_full_administrator"]
