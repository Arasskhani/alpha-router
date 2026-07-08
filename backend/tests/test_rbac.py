"""Tests for RBAC role definitions and permission checks."""

from app.services.rbac import (
    ASSIGNABLE_ADMIN_MENUS,
    FULL_ADMIN_SLUG,
    READ_ONLY_FULL_ADMIN_SLUG,
    SUPER_ADMIN_SLUG,
    USER_SLUG,
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


def test_role_catalog_excludes_removed_administrator_roles():
    roles = list_roles()
    slugs = {r["slug"] for r in roles}
    assert FULL_ADMIN_SLUG not in slugs
    assert READ_ONLY_FULL_ADMIN_SLUG not in slugs
    assert USER_SLUG in slugs
    assert "api_keys_full_administrator" in slugs
    assert "users_full_administrator" in slugs
    assert "dashboard_full_administrator" not in slugs
    assert "deleted_users_full_administrator" not in slugs
    assert "roles_full_administrator" not in slugs
    assert "database_full_administrator" not in slugs
    assert "recommendations_full_administrator" not in slugs
    assert "chat_full_administrator" not in slugs
    assert "media_full_administrator" not in slugs
    assert "admin_guide_full_administrator" not in slugs
    assert "user_manual_full_administrator" not in slugs
    assert "storage_full_administrator" not in slugs
    assert "storage_read_only_administrator" not in slugs
    assert "overview_full_administrator" not in slugs
    assert SUPER_ADMIN_SLUG in slugs
    assert len(roles) == 2 + len(ASSIGNABLE_ADMIN_MENUS) * 2


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


def test_super_admin_access_from_all_assignable_full_roles():
    slugs = [f"{menu}_full_administrator" for menu in sorted(ASSIGNABLE_ADMIN_MENUS)]
    assert user_has_super_admin_access(slugs)
    assert effective_accessible_menu_keys(slugs) is None
    assert can_access_menu(slugs[0], "api_keys")


def test_super_read_only_access_from_all_assignable_read_only_roles():
    slugs = [f"{menu}_read_only_administrator" for menu in sorted(ASSIGNABLE_ADMIN_MENUS)]
    assert user_has_super_read_only_access(slugs)
    assert effective_accessible_menu_keys(slugs) is None


def test_read_only_full_administrator_legacy_still_grants_all_menus():
    assert is_admin_panel_role(READ_ONLY_FULL_ADMIN_SLUG)
    assert is_read_only_role(READ_ONLY_FULL_ADMIN_SLUG)
    assert effective_accessible_menu_keys([READ_ONLY_FULL_ADMIN_SLUG]) is None


def test_menu_role_limited_to_one_menu():
    role = "api_keys_full_administrator"
    assert can_access_menu(role, "api_keys")
    assert not can_access_menu(role, "connections")
    assert can_write_menu(role, "api_keys")
    assert not can_write_menu(role, "connections")


def test_user_is_not_admin_panel():
    assert not is_admin_panel_role(USER_SLUG)
    assert not is_full_administrator(USER_SLUG)


def test_multi_role_lowest_write_access_on_same_menu():
    slugs = ["api_keys_full_administrator", "api_keys_read_only_administrator"]
    assert not user_can_write_menu(slugs, "api_keys")
    assert user_can_access_menu(slugs, "api_keys")


def test_multi_role_global_read_only_blocks_write():
    slugs = bootstrap_super_admin_role_slugs() + [READ_ONLY_FULL_ADMIN_SLUG]
    assert not user_can_write_menu(slugs, "api_keys")
    assert not user_can_write_menu(slugs)
    assert user_is_read_only_admin(slugs)


def test_multi_menu_roles_do_not_expand_globally():
    slugs = ["api_keys_full_administrator", "users_read_only_administrator"]
    allowed = effective_accessible_menu_keys(slugs)
    assert allowed == frozenset({"api_keys", "users"})
    assert user_can_write_menu(slugs, "api_keys")
    assert not user_can_write_menu(slugs, "users")
    assert not user_can_access_menu(slugs, "connections")
    assert not user_can_access_menu(slugs, "database")


def test_section_full_administrator_is_not_global_full():
    assert not user_has_super_admin_access(["api_keys_full_administrator"])
    allowed = effective_accessible_menu_keys(["api_keys_full_administrator"])
    assert allowed == frozenset({"api_keys"})
    assert not user_can_access_menu(["api_keys_full_administrator"], "database")
    assert not user_can_access_menu(["api_keys_full_administrator"], "dashboard")


def test_scoped_read_only_admin_is_not_globally_read_only():
    slugs = ["api_keys_read_only_administrator"]
    assert not user_is_read_only_admin(slugs)
    payload = session_payload_for_slugs(slugs)
    assert payload["read_only"] is False
    assert not user_can_write_menu(slugs, "api_keys")
    assert user_can_write_menu(slugs, "chat")


def test_scoped_admin_only_sees_assigned_menus():
    allowed = effective_accessible_menu_keys(["groups_full_administrator"])
    assert allowed == frozenset({"groups"})
    payload = session_payload_for_slugs(["groups_full_administrator"])
    assert payload["menus"] == ["groups"]
    assert payload["is_admin_panel"] is True
    assert user_can_access_menu(["users_full_administrator"], "users")
    assert not user_can_access_menu(["users_full_administrator"], "chat")
    assert not user_can_access_menu(["users_full_administrator"], "database")
    assert not user_can_access_menu(["users_full_administrator"], "deleted_users")
    assert not user_can_access_menu(["users_full_administrator"], "roles")
    assert user_can_write_menu(["users_full_administrator"], "users")
    assert not user_can_write_menu(["users_read_only_administrator"], "users")
    assert path_to_menu("/admin/my-activity") == "dashboard"


def test_primary_role_picks_lowest_privilege():
    assert primary_role_slug([SUPER_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG]) == READ_ONLY_FULL_ADMIN_SLUG
    assert primary_role_slug([SUPER_ADMIN_SLUG, "api_keys_full_administrator"]) == "api_keys_full_administrator"
    all_full = [f"{menu}_full_administrator" for menu in sorted(ASSIGNABLE_ADMIN_MENUS)]
    assert primary_role_slug(all_full + [READ_ONLY_FULL_ADMIN_SLUG]) == READ_ONLY_FULL_ADMIN_SLUG


def test_storage_menu_super_admin_only():
    assert not can_access_menu("reports_full_administrator", "storage")
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
