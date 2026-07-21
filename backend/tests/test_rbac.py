"""Tests for RBAC role definitions and permission checks."""

from app.services.rbac import (
    API_KEY_ADMIN_SLUG,
    FULL_ADMIN_SLUG,
    READ_ONLY_FULL_ADMIN_SLUG,
    SUPER_ADMIN_SLUG,
    USER_SLUG,
    actor_may_assign_roles,
    bootstrap_super_admin_role_slugs,
    can_access_menu,
    can_write_menu,
    effective_accessible_menu_keys,
    is_admin_panel_role,
    is_full_administrator,
    is_read_only_role,
    list_roles,
    normalize_role_slug,
    path_to_menu,
    primary_role_slug,
    session_payload_for_slugs,
    user_can_access_menu,
    user_can_write_menu,
    user_has_super_admin_access,
    user_has_super_read_only_access,
    user_is_read_only_admin,
)


def test_legacy_admin_normalizes_to_full_administrator():
    assert normalize_role_slug("admin") == FULL_ADMIN_SLUG


def test_legacy_read_only_normalizes_to_read_only_full_administrator():
    assert normalize_role_slug("read_only_administrator") == READ_ONLY_FULL_ADMIN_SLUG


def test_role_catalog_only_keeps_three_assignable_roles():
    roles = list_roles()
    slugs = {r["slug"] for r in roles}
    assert slugs == {USER_SLUG, SUPER_ADMIN_SLUG, API_KEY_ADMIN_SLUG}
    assert len(roles) == 3
    api_key_role = next(r for r in roles if r["slug"] == API_KEY_ADMIN_SLUG)
    assert api_key_role["name"] == "API Key Admin"
    assert FULL_ADMIN_SLUG not in slugs
    assert READ_ONLY_FULL_ADMIN_SLUG not in slugs
    assert "users_full_administrator" not in slugs
    assert "api_keys_read_only_administrator" not in slugs
    assert "groups_full_administrator" not in slugs
    assert "dashboard_full_administrator" not in slugs
    assert "storage_full_administrator" not in slugs


def test_super_admin_role_has_full_access():
    slugs = bootstrap_super_admin_role_slugs()
    assert slugs == [SUPER_ADMIN_SLUG]
    assert user_has_super_admin_access(slugs)
    assert is_full_administrator(SUPER_ADMIN_SLUG)
    assert effective_accessible_menu_keys(slugs) is None
    assert can_access_menu(SUPER_ADMIN_SLUG, "api_keys")
    assert can_access_menu(SUPER_ADMIN_SLUG, "roles")
    assert can_write_menu(SUPER_ADMIN_SLUG, "users")
    assert not user_is_read_only_admin(slugs)


def test_api_key_admin_is_not_super_admin():
    assert not user_has_super_admin_access([API_KEY_ADMIN_SLUG])
    assert effective_accessible_menu_keys([API_KEY_ADMIN_SLUG]) == frozenset({"api_keys"})


def test_non_super_cannot_grant_or_revoke_super_admin():
    api_key_admin = [API_KEY_ADMIN_SLUG]
    assert not actor_may_assign_roles(api_key_admin, [SUPER_ADMIN_SLUG])
    assert not actor_may_assign_roles(
        api_key_admin,
        [USER_SLUG],
        previous_slugs=[SUPER_ADMIN_SLUG],
    )
    assert actor_may_assign_roles(api_key_admin, [USER_SLUG])
    assert actor_may_assign_roles(api_key_admin, [API_KEY_ADMIN_SLUG])
    assert actor_may_assign_roles([SUPER_ADMIN_SLUG], [SUPER_ADMIN_SLUG])
    assert actor_may_assign_roles(
        [SUPER_ADMIN_SLUG],
        [USER_SLUG],
        previous_slugs=[SUPER_ADMIN_SLUG],
    )


def test_read_only_full_administrator_legacy_still_grants_all_menus():
    assert is_admin_panel_role(READ_ONLY_FULL_ADMIN_SLUG)
    assert is_read_only_role(READ_ONLY_FULL_ADMIN_SLUG)
    assert user_has_super_read_only_access([READ_ONLY_FULL_ADMIN_SLUG])
    assert effective_accessible_menu_keys([READ_ONLY_FULL_ADMIN_SLUG]) is None


def test_menu_role_limited_to_one_menu():
    role = API_KEY_ADMIN_SLUG
    assert can_access_menu(role, "api_keys")
    assert not can_access_menu(role, "connections")
    assert can_write_menu(role, "api_keys")
    assert not can_write_menu(role, "connections")


def test_user_is_not_admin_panel():
    assert not is_admin_panel_role(USER_SLUG)
    assert not is_full_administrator(USER_SLUG)


def test_multi_role_global_read_only_blocks_write():
    slugs = bootstrap_super_admin_role_slugs() + [READ_ONLY_FULL_ADMIN_SLUG]
    assert not user_can_write_menu(slugs, "api_keys")
    assert not user_can_write_menu(slugs)
    assert user_is_read_only_admin(slugs)


def test_api_key_admin_session_payload():
    payload = session_payload_for_slugs([API_KEY_ADMIN_SLUG])
    assert payload["menus"] == ["api_keys"]
    assert payload["is_admin_panel"] is True
    assert payload["role_name"] == "API Key Admin"
    assert not user_can_access_menu([API_KEY_ADMIN_SLUG], "database")
    assert not user_can_access_menu([API_KEY_ADMIN_SLUG], "dashboard")
    assert not user_can_access_menu([API_KEY_ADMIN_SLUG], "users")


def test_removed_menu_roles_no_longer_grant_access():
    assert not is_admin_panel_role("users_full_administrator")
    assert not is_admin_panel_role("groups_full_administrator")
    assert not user_can_access_menu(["users_full_administrator"], "users")
    assert effective_accessible_menu_keys(["groups_full_administrator"]) == frozenset()
    assert path_to_menu("/admin/my-activity") == "dashboard"


def test_primary_role_picks_lowest_privilege():
    assert primary_role_slug([SUPER_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG]) == READ_ONLY_FULL_ADMIN_SLUG
    assert primary_role_slug([SUPER_ADMIN_SLUG, API_KEY_ADMIN_SLUG]) == API_KEY_ADMIN_SLUG


def test_storage_menu_super_admin_only():
    assert not can_access_menu(API_KEY_ADMIN_SLUG, "storage")
    assert can_access_menu(SUPER_ADMIN_SLUG, "storage")
    roles = list_roles()
    slugs = {r["slug"] for r in roles}
    assert "storage_full_administrator" not in slugs
    assert "storage_read_only_administrator" not in slugs


def test_path_to_menu():
    assert path_to_menu("/admin/api-keys") == "api_keys"
    assert path_to_menu("/admin/users/5/activity") == "users"
    assert path_to_menu("/admin") == "dashboard"
    assert path_to_menu("/admin/connections/1/activity") == "connections"
    assert path_to_menu("/admin/retention-policy") == "storage"
    assert path_to_menu("/admin/storage-management") == "storage"
    assert path_to_menu("/admin/storage") == "storage"
