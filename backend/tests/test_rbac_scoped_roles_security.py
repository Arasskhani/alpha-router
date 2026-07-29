"""Security tests for re-enabled scoped admin roles (Dashboard View, Reports Access)."""

from app.services.rbac import (
    API_KEY_ADMIN_SLUG,
    DASHBOARD_VIEW_SLUG,
    MENU_LABELS,
    REPORTS_ACCESS_SLUG,
    SUPER_ADMIN_SLUG,
    USER_SLUG,
    actor_may_assign_roles,
    can_access_menu,
    can_write_menu,
    effective_accessible_menu_keys,
    expand_legacy_role_slug,
    is_admin_panel_role,
    is_read_only_role,
    session_payload_for_slugs,
    user_can_access_menu,
    user_can_write_menu,
    user_has_super_admin_access,
    user_has_super_read_only_access,
    user_is_read_only_admin,
)

SENSITIVE_MENUS = tuple(
    menu
    for menu in MENU_LABELS
    if menu
    not in {
        "dashboard",
        "reports",
        "chat",
        "media",
        "user_manual",
    }
)


def test_dashboard_view_positive_access_and_no_write():
    assert is_admin_panel_role(DASHBOARD_VIEW_SLUG)
    assert is_read_only_role(DASHBOARD_VIEW_SLUG)
    assert effective_accessible_menu_keys([DASHBOARD_VIEW_SLUG]) == frozenset({"dashboard"})
    assert can_access_menu(DASHBOARD_VIEW_SLUG, "dashboard")
    assert not can_write_menu(DASHBOARD_VIEW_SLUG, "dashboard")
    assert user_can_access_menu([DASHBOARD_VIEW_SLUG], "dashboard")
    assert not user_can_write_menu([DASHBOARD_VIEW_SLUG], "dashboard")


def test_reports_access_positive_access_and_write():
    assert is_admin_panel_role(REPORTS_ACCESS_SLUG)
    assert not is_read_only_role(REPORTS_ACCESS_SLUG)
    assert effective_accessible_menu_keys([REPORTS_ACCESS_SLUG]) == frozenset({"reports"})
    assert can_access_menu(REPORTS_ACCESS_SLUG, "reports")
    assert can_write_menu(REPORTS_ACCESS_SLUG, "reports")
    assert user_can_access_menu([REPORTS_ACCESS_SLUG], "reports")
    assert user_can_write_menu([REPORTS_ACCESS_SLUG], "reports")


def test_combined_roles_least_privilege_write():
    slugs = [DASHBOARD_VIEW_SLUG, REPORTS_ACCESS_SLUG]
    assert effective_accessible_menu_keys(slugs) == frozenset({"dashboard", "reports"})
    assert user_can_access_menu(slugs, "dashboard")
    assert user_can_access_menu(slugs, "reports")
    assert not user_can_write_menu(slugs, "dashboard")
    assert user_can_write_menu(slugs, "reports")


def test_dashboard_view_denies_other_admin_menus():
    for menu in SENSITIVE_MENUS:
        assert not user_can_access_menu([DASHBOARD_VIEW_SLUG], menu), menu
        assert not user_can_write_menu([DASHBOARD_VIEW_SLUG], menu), menu
    assert not user_can_access_menu([DASHBOARD_VIEW_SLUG], "reports")
    assert not user_can_write_menu([DASHBOARD_VIEW_SLUG], "reports")


def test_reports_access_denies_other_admin_menus():
    for menu in SENSITIVE_MENUS:
        assert not user_can_access_menu([REPORTS_ACCESS_SLUG], menu), menu
        assert not user_can_write_menu([REPORTS_ACCESS_SLUG], menu), menu
    assert not user_can_access_menu([REPORTS_ACCESS_SLUG], "dashboard")
    assert not user_can_write_menu([REPORTS_ACCESS_SLUG], "dashboard")


def test_scoped_roles_cannot_escalate_to_super_admin():
    for actor in ([DASHBOARD_VIEW_SLUG], [REPORTS_ACCESS_SLUG], [DASHBOARD_VIEW_SLUG, REPORTS_ACCESS_SLUG]):
        assert not actor_may_assign_roles(actor, [SUPER_ADMIN_SLUG])
        assert not actor_may_assign_roles(actor, [USER_SLUG], previous_slugs=[SUPER_ADMIN_SLUG])
        assert not user_has_super_admin_access(actor)
        assert not user_has_super_read_only_access(actor)


def test_dashboard_view_is_not_global_read_only_admin_flag():
    # Scoped read-only must not freeze unrelated menus when combined later.
    assert not user_is_read_only_admin([DASHBOARD_VIEW_SLUG])
    assert not user_is_read_only_admin([DASHBOARD_VIEW_SLUG, REPORTS_ACCESS_SLUG])


def test_session_payload_for_scoped_roles():
    dash = session_payload_for_slugs([DASHBOARD_VIEW_SLUG])
    assert dash["menus"] == ["dashboard"]
    assert dash["is_admin_panel"] is True
    assert dash["role_name"] == "Dashboard View"
    assert "api_keys" not in (dash["menus"] or [])

    reports = session_payload_for_slugs([REPORTS_ACCESS_SLUG])
    assert reports["menus"] == ["reports"]
    assert reports["role_name"] == "Reports Access"
    assert reports["is_admin_panel"] is True

    both = session_payload_for_slugs([DASHBOARD_VIEW_SLUG, REPORTS_ACCESS_SLUG])
    assert both["menus"] == ["dashboard", "reports"]


def test_expand_legacy_keeps_new_roles_and_still_drops_siblings():
    assert expand_legacy_role_slug(DASHBOARD_VIEW_SLUG) == [DASHBOARD_VIEW_SLUG]
    assert expand_legacy_role_slug(REPORTS_ACCESS_SLUG) == [REPORTS_ACCESS_SLUG]
    # Sibling / write variant of dashboard stays removed.
    assert expand_legacy_role_slug("dashboard_full_administrator") == []
    assert expand_legacy_role_slug("reports_read_only_administrator") == []
    # Section bundles must not resurrect scoped roles via ASSIGNABLE_ADMIN_MENUS.
    assert expand_legacy_role_slug("overview_full_administrator") == []
    assert expand_legacy_role_slug("data_reports_full_administrator") == []
    assert expand_legacy_role_slug("models_api_full_administrator") == [API_KEY_ADMIN_SLUG]


def test_existing_api_key_admin_unchanged_by_scoped_roles():
    assert effective_accessible_menu_keys([API_KEY_ADMIN_SLUG]) == frozenset({"api_keys"})
    assert user_can_write_menu([API_KEY_ADMIN_SLUG], "api_keys")
    assert not user_can_access_menu([API_KEY_ADMIN_SLUG], "dashboard")
    assert not user_can_access_menu([API_KEY_ADMIN_SLUG], "reports")
