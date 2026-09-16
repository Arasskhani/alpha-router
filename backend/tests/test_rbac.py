"""Tests for RBAC role definitions and permission checks."""

from app.services.rbac import (
    ALL_SECTIONS_CATEGORY,
    AGENT_AUDITOR_SLUG,
    AGENT_DESIGNER_SLUG,
    AGENT_OPERATIONS_ADMIN_SLUG,
    AGENT_PUBLISHER_SLUG,
    AGENTS_ADMIN_SLUG,
    API_KEY_ADMIN_SLUG,
    CATEGORY_LABELS,
    DASHBOARD_VIEW_SLUG,
    DOMAIN_APPROVER_SLUG,
    FULL_ADMIN_SLUG,
    KNOWLEDGE_ADMIN_SLUG,
    KNOWLEDGE_CURATOR_SLUG,
    KNOWLEDGE_PUBLISHER_SLUG,
    MENU_GROUP_KEYS,
    MENUS_BY_CATEGORY,
    READ_ONLY_FULL_ADMIN_SLUG,
    READ_ONLY_SUPER_ADMIN_SLUG,
    REPORTS_ACCESS_SLUG,
    SUPER_ADMIN_SLUG,
    TOOL_ADMIN_SLUG,
    USER_SLUG,
    MENU_LABELS,
    USER_APP_MENUS,
    accessible_menu_keys,
    is_valid_role_slug,
    actor_may_assign_roles,
    agent_permissions_for_slugs,
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
    expand_legacy_role_slug,
    user_has_agent_permission,
    user_has_super_admin_access,
    user_has_super_read_only_access,
    user_is_read_only_admin,
)


def test_legacy_admin_normalizes_to_full_administrator():
    assert normalize_role_slug("admin") == FULL_ADMIN_SLUG


def test_legacy_read_only_normalizes_to_read_only_full_administrator():
    assert normalize_role_slug("read_only_administrator") == READ_ONLY_FULL_ADMIN_SLUG


def test_role_catalog_keeps_existing_roles_and_adds_scoped_views():
    roles = list_roles()
    by_slug = {r["slug"]: r for r in roles}
    # Existing roles unchanged.
    assert by_slug[USER_SLUG]["name"] == "User"
    assert by_slug[USER_SLUG]["is_user_panel"] is True
    assert by_slug[SUPER_ADMIN_SLUG]["name"] == "Super Admin"
    assert by_slug[SUPER_ADMIN_SLUG]["read_only"] is False
    assert by_slug[API_KEY_ADMIN_SLUG]["name"] == "API Key Admin"
    assert by_slug[API_KEY_ADMIN_SLUG]["menu_key"] == "api_keys"
    assert by_slug[API_KEY_ADMIN_SLUG]["read_only"] is False
    # New scoped roles.
    assert by_slug[DASHBOARD_VIEW_SLUG]["name"] == "Dashboard View"
    assert by_slug[DASHBOARD_VIEW_SLUG]["menu_key"] == "dashboard"
    assert by_slug[DASHBOARD_VIEW_SLUG]["read_only"] is True
    assert by_slug[REPORTS_ACCESS_SLUG]["name"] == "Reports Access"
    assert by_slug[REPORTS_ACCESS_SLUG]["menu_key"] == "reports"
    assert by_slug[REPORTS_ACCESS_SLUG]["read_only"] is False
    assert set(by_slug) == {
        USER_SLUG,
        SUPER_ADMIN_SLUG,
        READ_ONLY_SUPER_ADMIN_SLUG,
        API_KEY_ADMIN_SLUG,
        DASHBOARD_VIEW_SLUG,
        REPORTS_ACCESS_SLUG,
        AGENTS_ADMIN_SLUG,
        AGENT_DESIGNER_SLUG,
        AGENT_PUBLISHER_SLUG,
        KNOWLEDGE_ADMIN_SLUG,
        KNOWLEDGE_CURATOR_SLUG,
        KNOWLEDGE_PUBLISHER_SLUG,
        DOMAIN_APPROVER_SLUG,
        TOOL_ADMIN_SLUG,
        AGENT_OPERATIONS_ADMIN_SLUG,
        AGENT_AUDITOR_SLUG,
    }
    assert FULL_ADMIN_SLUG not in by_slug
    assert READ_ONLY_FULL_ADMIN_SLUG not in by_slug
    assert "users_full_administrator" not in by_slug
    assert "api_keys_read_only_administrator" not in by_slug
    assert "groups_full_administrator" not in by_slug
    assert "dashboard_full_administrator" not in by_slug
    assert "storage_full_administrator" not in by_slug
    assert "reports_read_only_administrator" not in by_slug
    assert by_slug[AGENT_DESIGNER_SLUG]["menu_key"] == "agents"
    assert by_slug[AGENT_AUDITOR_SLUG]["read_only"] is True


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
    assert path_to_menu("/admin/project-usage") == "reports"
    assert path_to_menu("/admin/users/5/activity") == "users"
    assert path_to_menu("/admin") == "dashboard"
    assert path_to_menu("/admin/connections/1/activity") == "connections"
    assert path_to_menu("/admin/retention-policy") == "storage"
    assert path_to_menu("/admin/storage-management") == "storage"
    assert path_to_menu("/admin/storage") == "storage"
    assert path_to_menu("/admin/security-settings") == "security_settings"


def test_operations_and_database_live_under_overview():
    assert "monitoring" not in CATEGORY_LABELS
    assert MENU_GROUP_KEYS["operations"] == "overview"
    assert MENU_GROUP_KEYS["database"] == "overview"
    overview = MENUS_BY_CATEGORY["overview"]
    assert overview[:3] == ("dashboard", "operations", "database")
    assert "operations" in overview
    assert "database" in overview


def test_security_category_and_settings_menu():
    assert CATEGORY_LABELS["security"] == "Security"
    assert MENU_GROUP_KEYS["security_settings"] == "security"
    assert MENUS_BY_CATEGORY["security"] == ("security_settings",)
    assert path_to_menu("/admin/security-settings") == "security_settings"
    assert can_access_menu(SUPER_ADMIN_SLUG, "security_settings")
    assert not can_access_menu(API_KEY_ADMIN_SLUG, "security_settings")


def test_agents_category_and_routes_are_single_menu_surface():
    assert CATEGORY_LABELS["agents_knowledge"] == "Agents & Knowledge"
    assert MENU_GROUP_KEYS["agents"] == "agents_knowledge"
    assert MENUS_BY_CATEGORY["agents_knowledge"] == ("agents",)
    assert path_to_menu("/admin/agents") == "agents"
    assert path_to_menu("/admin/agents/abc/activity") == "agents"
    assert path_to_menu("/admin/knowledge/kb-1/documents") == "agents"
    assert path_to_menu("/admin/agent-evaluations/runs") == "agents"


def test_agent_roles_use_action_level_permissions():
    assert user_can_access_menu([AGENT_DESIGNER_SLUG], "agents")
    assert user_has_agent_permission([AGENT_DESIGNER_SLUG], "agent.create")
    assert user_has_agent_permission([AGENT_DESIGNER_SLUG], "agent.test")
    assert not user_has_agent_permission([AGENT_DESIGNER_SLUG], "agent.publish")

    assert user_has_agent_permission([AGENT_PUBLISHER_SLUG], "agent.publish")
    assert not user_has_agent_permission([AGENT_PUBLISHER_SLUG], "agent.edit")
    assert user_has_agent_permission([KNOWLEDGE_CURATOR_SLUG], "knowledge.documents.write")
    assert not user_has_agent_permission([KNOWLEDGE_CURATOR_SLUG], "knowledge.publish")
    assert user_has_agent_permission([DOMAIN_APPROVER_SLUG], "approval.approve")
    assert user_has_agent_permission([SUPER_ADMIN_SLUG], "operations.reindex")
    assert not user_has_agent_permission([USER_SLUG], "agent.read")


def test_agent_permission_union_is_composable():
    permissions = agent_permissions_for_slugs([AGENT_DESIGNER_SLUG, KNOWLEDGE_PUBLISHER_SLUG])
    assert "agent.edit" in permissions
    assert "knowledge.publish" in permissions
    assert "tool.manage" not in permissions


class TestReadOnlySuperAdmin:
    """Sees everything Super Admin sees; changes none of it.

    The codebase already carried a retired platform-wide read-only role
    (``read_only_full_administrator``) that every guard understood but nothing
    could assign. This is that capability, made assignable under the name it is
    asked for, with the legacy slugs kept working beside it.
    """

    SLUG = READ_ONLY_SUPER_ADMIN_SLUG

    def _admin_menus(self):
        return [m for m in MENU_LABELS if m not in USER_APP_MENUS]

    def test_it_is_in_the_catalog_and_assignable(self):
        by_slug = {r["slug"]: r for r in list_roles()}
        role = by_slug[self.SLUG]
        assert role["name"] == "Read Only Super Admin"
        assert role["read_only"] is True
        assert role["menu_key"] is None
        assert role["category"] == ALL_SECTIONS_CATEGORY
        assert is_valid_role_slug(self.SLUG)

    def test_it_sees_every_admin_menu(self):
        assert accessible_menu_keys(self.SLUG) is None
        assert effective_accessible_menu_keys([self.SLUG]) is None
        for menu in MENU_LABELS:
            assert can_access_menu(self.SLUG, menu), menu

    def test_it_writes_to_none_of_them(self):
        """The one that matters. can_write_menu ends with a suffix test on
        '_read_only_administrator', which this slug does not match - so a missed
        check here reads as full write access, not as no access."""
        for menu in self._admin_menus():
            assert not can_write_menu(self.SLUG, menu), menu
            assert not user_can_write_menu([self.SLUG], menu), menu
        assert not user_can_write_menu([self.SLUG])

    def test_chat_and_media_stay_usable(self):
        """Read-only means it changes no administration, not that the person
        cannot use the product."""
        for menu in USER_APP_MENUS:
            assert can_write_menu(self.SLUG, menu), menu

    def test_it_holds_no_agent_permissions(self):
        assert agent_permissions_for_slugs([self.SLUG]) == frozenset()
        for permission in ("agent.publish", "knowledge.purge", "governance.retention.run"):
            assert not user_has_agent_permission([self.SLUG], permission)

    def test_it_is_an_admin_but_not_a_super_admin(self):
        assert is_admin_panel_role(self.SLUG)
        assert is_read_only_role(self.SLUG)
        assert user_is_read_only_admin([self.SLUG])
        assert user_has_super_read_only_access([self.SLUG])
        assert not user_has_super_admin_access([self.SLUG])
        assert not is_full_administrator(self.SLUG)

    def test_holding_it_alongside_super_admin_vetoes_writes(self):
        """A user given both is read-only in effect: user_can_write_menu needs
        every role covering the menu to allow the write."""
        both = [SUPER_ADMIN_SLUG, self.SLUG]
        assert effective_accessible_menu_keys(both) is None
        for menu in self._admin_menus():
            assert not user_can_write_menu(both, menu), menu
        assert primary_role_slug(both) == self.SLUG

    def test_the_session_payload_reports_it(self):
        payload = session_payload_for_slugs([self.SLUG])
        assert payload["role"] == self.SLUG
        assert payload["role_name"] == "Read Only Super Admin"
        assert payload["read_only"] is True
        assert payload["is_admin_panel"] is True
        assert payload["menus"] is None

    def test_granting_it_requires_super_admin(self):
        """It grants sight of every menu - API keys, security settings, the
        whole audit trail - so handing it out is a platform-wide decision."""
        assert actor_may_assign_roles([SUPER_ADMIN_SLUG], [self.SLUG])
        assert not actor_may_assign_roles([API_KEY_ADMIN_SLUG], [self.SLUG])
        assert not actor_may_assign_roles([USER_SLUG], [self.SLUG])
        # and revoking it, in the other direction
        assert not actor_may_assign_roles([API_KEY_ADMIN_SLUG], [USER_SLUG], [self.SLUG])
        assert actor_may_assign_roles([SUPER_ADMIN_SLUG], [USER_SLUG], [self.SLUG])

    def test_the_retired_global_read_only_slugs_behave_the_same(self):
        for legacy in (READ_ONLY_FULL_ADMIN_SLUG, "read_only_administrator"):
            assert accessible_menu_keys(legacy) is None, legacy
            assert not user_can_write_menu([legacy], "users"), legacy
            assert user_is_read_only_admin([legacy]), legacy

    def test_the_legacy_remap_no_longer_escalates(self):
        """It used to return super_admin: a read-only administrator came out of
        the migration able to change everything, because there was no
        platform-wide read-only role to migrate them into."""
        assert expand_legacy_role_slug(READ_ONLY_FULL_ADMIN_SLUG) == [self.SLUG]
        assert expand_legacy_role_slug("read_only_administrator") == [self.SLUG]
        assert expand_legacy_role_slug(FULL_ADMIN_SLUG) == [SUPER_ADMIN_SLUG]
