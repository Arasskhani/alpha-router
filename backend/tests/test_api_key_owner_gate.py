"""A scoped admin cannot mint a gateway key that inherits Super Admin's reach.

``resolve_key_subject`` answers ``unrestricted=True`` for a key whose *owner*
has Super Admin access, so the key sees every private model in the catalogue.
Naming the owner was gated on nothing but the user existing.

The API Key Admin role - documented as "full access to the API Keys admin menu"
- therefore satisfied ``require_api_keys_write``, could post
``owner_user_id`` of a Super Admin with ``unlimited_budget: true``, and read the
raw secret out of the response body: unlimited spend against no budget, every
private model, plus the owner's Knowledge and Agent read access.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.admin import _ensure_actor_may_own_key
from app.core.security import hash_password
from app.models.user import User
from app.services.rbac import (
    API_KEY_ADMIN_SLUG,
    READ_ONLY_SUPER_ADMIN_SLUG,
    SUPER_ADMIN_SLUG,
    USER_SLUG,
)
from app.services.user_role_service import set_user_roles


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


async def test_a_scoped_admin_cannot_name_a_super_admin_as_owner(db_session):
    actor = await _person(db_session, "key_admin", [API_KEY_ADMIN_SLUG])
    owner = await _person(db_session, "the_super_admin", [SUPER_ADMIN_SLUG])

    with pytest.raises(HTTPException) as exc:
        await _ensure_actor_may_own_key(db_session, actor, owner)
    assert exc.value.status_code == 403


async def test_a_scoped_admin_cannot_name_a_read_only_super_admin_either(db_session):
    """It grants sight of every menu, so it is a platform-wide account too."""

    actor = await _person(db_session, "key_admin_2", [API_KEY_ADMIN_SLUG])
    owner = await _person(db_session, "read_only_super", [READ_ONLY_SUPER_ADMIN_SLUG])

    with pytest.raises(HTTPException):
        await _ensure_actor_may_own_key(db_session, actor, owner)


async def test_a_scoped_admin_may_still_name_an_ordinary_user(db_session):
    """The gate must not break the role's actual job."""

    actor = await _person(db_session, "key_admin_3", [API_KEY_ADMIN_SLUG])
    owner = await _person(db_session, "ordinary", [USER_SLUG])

    await _ensure_actor_may_own_key(db_session, actor, owner)


async def test_a_super_admin_may_name_anyone(db_session):
    actor = await _person(db_session, "the_boss", [SUPER_ADMIN_SLUG])
    owner = await _person(db_session, "another_boss", [SUPER_ADMIN_SLUG])

    await _ensure_actor_may_own_key(db_session, actor, owner)


async def test_every_endpoint_that_accepts_an_owner_is_gated():
    """Create, patch and email-credentials all name an owner."""

    import inspect

    from app.api import admin

    for name in ("create_alpha_router_key", "patch_alpha_router_key", "email_api_key_credentials"):
        source = inspect.getsource(getattr(admin, name))
        assert "_ensure_actor_may_own_key" in source, f"{name} accepts an owner without the gate"
