"""Tests for RBAC menu migration from legacy section roles."""

from app.services.rbac import ASSIGNABLE_ADMIN_MENUS, SUPER_ADMIN_SLUG, expand_legacy_role_slug


def test_expand_legacy_section_full_administrator():
    expanded = expand_legacy_role_slug("overview_full_administrator")
    assert expanded == []
    assert "connections_full_administrator" not in expanded


def test_expand_legacy_read_only_administrator_to_all_assignable_read_only():
    expanded = expand_legacy_role_slug("read_only_administrator")
    assert expanded == [f"{menu}_read_only_administrator" for menu in sorted(ASSIGNABLE_ADMIN_MENUS)]


def test_expand_legacy_admin_to_super_admin():
    assert expand_legacy_role_slug("admin") == [SUPER_ADMIN_SLUG]
    assert expand_legacy_role_slug("full_administrator") == [SUPER_ADMIN_SLUG]
    assert expand_legacy_role_slug("super_admin") == [SUPER_ADMIN_SLUG]


def test_expand_removed_menu_role_returns_empty():
    assert expand_legacy_role_slug("chat_full_administrator") == []
    assert expand_legacy_role_slug("dashboard_full_administrator") == []
    assert expand_legacy_role_slug("roles_full_administrator") == []
    assert expand_legacy_role_slug("full_administrator") == [SUPER_ADMIN_SLUG]


def test_expand_menu_role_unchanged():
    assert expand_legacy_role_slug("api_keys_full_administrator") == ["api_keys_full_administrator"]
