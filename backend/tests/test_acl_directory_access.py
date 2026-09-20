"""The group and role directories, for every page that edits an ACL.

The bug: ``ResourceAccessEditor`` fetches ``/api/admin/groups`` and
``/api/admin/roles`` to offer something to grant to, and both were gated on
menus that have nothing to do with the page the editor is on - Groups for one,
Users or Roles for the other. The component catches the 403 and falls back to
an empty list, so the operator saw two empty dropdowns and no reason why. It
was already true of Agent Studio and Knowledge Bases; Chat Tools would have
been the third.

Reading the directory is not managing it, and these are names the grantee is
about to be shown anyway. Handing every operator who can grant something the
Groups menu instead would have been the larger widening.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import ACL_EDITING_MENUS, require_acl_directory
from app.models.user import User
from app.services.rbac import MENU_PATH_PREFIXES


async def _user_with_role(db, username: str, slug: str) -> User:
    from app.core.security import hash_password
    from app.services.user_role_service import set_user_roles

    row = User(
        username=username,
        email=f"{username}@test",
        hashed_password=hash_password("x"),
        auth_provider="local",
        is_active=True,
    )
    db.add(row)
    await db.flush()
    await set_user_roles(db, row, [slug])
    await db.commit()
    await db.refresh(row)
    return row


def test_every_menu_named_as_an_acl_editor_exists():
    assert set(ACL_EDITING_MENUS) <= set(MENU_PATH_PREFIXES)


def test_the_page_with_the_newest_access_editor_is_covered():
    assert "chat_tools" in ACL_EDITING_MENUS


@pytest.mark.parametrize(
    "slug",
    ["super_admin", "read_only_super_admin", "agents_administrator", "knowledge_curator"],
)
async def test_an_administrator_of_a_page_with_an_access_editor_may_read_it(db_session, slug):
    person = await _user_with_role(db_session, f"admin_{slug}", slug)
    assert await require_acl_directory(user=person, db=db_session) is person


@pytest.mark.parametrize("slug", ["api_keys_full_administrator", "reports_full_administrator"])
async def test_an_administrator_of_something_else_may_not(db_session, slug):
    """Widening the read to every ACL page is not widening it to everybody."""
    person = await _user_with_role(db_session, f"admin_{slug}", slug)
    with pytest.raises(HTTPException) as caught:
        await require_acl_directory(user=person, db=db_session)
    assert caught.value.status_code == 403


async def test_an_ordinary_user_may_not(db_session, user):
    with pytest.raises(HTTPException):
        await require_acl_directory(user=user, db=db_session)


async def test_a_deactivated_administrator_may_not(db_session):
    person = await _user_with_role(db_session, "admin_gone", "super_admin")
    person.is_active = False
    await db_session.commit()
    with pytest.raises(HTTPException):
        await require_acl_directory(user=person, db=db_session)


def test_the_group_list_and_the_role_list_use_it():
    from app.api import admin, groups
    from app.api.deps import require_role_catalog

    def guards(router, name):
        route = next(r for r in router.routes if r.name == name)
        return [dep.call for dep in route.dependant.dependencies]

    assert require_acl_directory in guards(groups.router, "list_groups")
    # The role catalog keeps its own name for the Users and Roles screens and
    # defers to the same check.
    assert require_role_catalog in guards(admin.router, "list_rbac_roles")


def test_managing_groups_still_needs_the_groups_menu():
    """Only the read widened. Creating, renaming and deleting did not."""
    from app.api import groups
    from app.api.deps import require_groups, require_groups_write

    managed = [
        dep.call
        for route in groups.router.routes
        if route.name != "list_groups"
        for dep in route.dependant.dependencies
    ]
    assert require_acl_directory not in managed
    assert require_groups in managed or require_groups_write in managed
