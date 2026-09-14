"""Role-based access control for the Alpharouter admin panel (per-menu roles)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MenuKey = Literal[
    "dashboard",
    "chat",
    "media",
    "connections",
    "models",
    "api_keys",
    "roles",
    "users",
    "deleted_users",
    "groups",
    "plans",
    "authentication",
    "smtp",
    "storage",
    "reports",
    "api_logs",
    "operations",
    "database",
    "agents",
    "admin_guide",
    "user_manual",
    "security_settings",
]

# Nav group label shown in the Roles table Category column.
CategoryKey = Literal[
    "overview",
    "models_api",
    "people_access",
    "integrations",
    "data_reports",
    "agents_knowledge",
    "developer",
    "security",
]

ALL_SECTIONS_CATEGORY = "All sections"
USER_CATEGORY = "User"

LEGACY_ADMIN_SLUG = "admin"
FULL_ADMIN_SLUG = "full_administrator"
READ_ONLY_FULL_ADMIN_SLUG = "read_only_full_administrator"
LEGACY_READ_ONLY_ADMIN_SLUG = "read_only_administrator"
USER_SLUG = "user"
SUPER_ADMIN_SLUG = "super_admin"
API_KEY_ADMIN_SLUG = "api_keys_full_administrator"
DASHBOARD_VIEW_SLUG = "dashboard_read_only_administrator"
REPORTS_ACCESS_SLUG = "reports_full_administrator"
AGENTS_ADMIN_SLUG = "agents_administrator"
AGENT_DESIGNER_SLUG = "agent_designer"
AGENT_PUBLISHER_SLUG = "agent_publisher"
KNOWLEDGE_ADMIN_SLUG = "knowledge_administrator"
KNOWLEDGE_CURATOR_SLUG = "knowledge_curator"
KNOWLEDGE_PUBLISHER_SLUG = "knowledge_publisher"
DOMAIN_APPROVER_SLUG = "agent_domain_approver"
TOOL_ADMIN_SLUG = "agent_tool_administrator"
AGENT_OPERATIONS_ADMIN_SLUG = "agent_operations_administrator"
AGENT_AUDITOR_SLUG = "agent_auditor"

# Explicitly re-enabled scoped roles (must stay assignable; not section-bundle generated).
REENABLED_SCOPED_ROLE_SLUGS: frozenset[str] = frozenset({DASHBOARD_VIEW_SLUG, REPORTS_ACCESS_SLUG})

MENU_DEFINITIONS: tuple[tuple[MenuKey, str, CategoryKey], ...] = (
    ("dashboard", "Dashboard", "overview"),
    ("operations", "Operations", "overview"),
    ("database", "Database", "overview"),
    ("chat", "Chat", "overview"),
    ("media", "Media", "overview"),
    ("connections", "Connections", "models_api"),
    ("models", "Models", "models_api"),
    ("api_keys", "API Keys", "models_api"),
    ("roles", "Roles", "people_access"),
    ("users", "Users", "people_access"),
    ("deleted_users", "Deleted Users", "people_access"),
    ("groups", "Groups", "people_access"),
    ("plans", "Plans", "people_access"),
    ("authentication", "Authentication", "people_access"),
    ("smtp", "SMTP Server", "integrations"),
    ("storage", "Storage", "data_reports"),
    ("reports", "Reports", "data_reports"),
    ("api_logs", "API Logs", "data_reports"),
    ("agents", "Agents & Knowledge", "agents_knowledge"),
    ("admin_guide", "Admin Guide", "developer"),
    ("user_manual", "User Manual", "developer"),
    ("security_settings", "Security Settings", "security"),
)

# Only API Keys keeps a dedicated assignable admin role (API Key Admin).
ASSIGNABLE_ADMIN_MENUS: frozenset[MenuKey] = frozenset({"api_keys"})

# All other menus are Super Admin only (no dedicated assignable role).
MENUS_WITHOUT_ASSIGNABLE_ROLES: frozenset[MenuKey] = frozenset(
    menu for menu, _, _ in MENU_DEFINITIONS if menu not in ASSIGNABLE_ADMIN_MENUS
)

# End-user features (chat, media, …) — not admin RBAC menus; always writable when the account is active.
USER_APP_MENUS: frozenset[MenuKey] = frozenset(
    {
        "chat",
        "media",
        "user_manual",
    }
)


def _all_historical_menu_role_slugs() -> frozenset[str]:
    slugs: set[str] = set()
    for menu, _, _ in MENU_DEFINITIONS:
        slugs.add(f"{menu}_full_administrator")
        slugs.add(f"{menu}_read_only_administrator")
    return frozenset(slugs)


# Legacy / retired slugs removed from the assignable catalog (still remapped on migration).
REMOVED_ASSIGNABLE_ROLE_SLUGS: frozenset[str] = frozenset(
    {
        FULL_ADMIN_SLUG,
        READ_ONLY_FULL_ADMIN_SLUG,
        # Historical role slugs for a removed menu (keep for assignment remaps).
        "recommendations_full_administrator",
        "recommendations_read_only_administrator",
    }
    | (_all_historical_menu_role_slugs() - {API_KEY_ADMIN_SLUG} - REENABLED_SCOPED_ROLE_SLUGS)
)

LEGACY_SUPER_ADMIN_SLUGS: frozenset[str] = frozenset(
    {FULL_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG, LEGACY_READ_ONLY_ADMIN_SLUG, LEGACY_ADMIN_SLUG}
)

GLOBAL_FULL_ADMIN_SLUGS: frozenset[str] = frozenset({SUPER_ADMIN_SLUG, FULL_ADMIN_SLUG, LEGACY_ADMIN_SLUG})

MENU_LABELS: dict[MenuKey, str] = {m[0]: m[1] for m in MENU_DEFINITIONS}
MENU_GROUP_KEYS: dict[MenuKey, CategoryKey] = {m[0]: m[2] for m in MENU_DEFINITIONS}
CATEGORY_LABELS: dict[CategoryKey, str] = {
    "overview": "Overview",
    "models_api": "Models & API",
    "people_access": "People & access",
    "integrations": "Integrations",
    "data_reports": "Data & reports",
    "agents_knowledge": "Agents & Knowledge",
    "developer": "Developer",
    "security": "Security",
}

MENU_PATH_PREFIXES: dict[MenuKey, tuple[str, ...]] = {
    "dashboard": ("/admin", "/admin/my-activity"),
    "chat": ("/admin/chat",),
    "media": ("/admin/media",),
    "connections": ("/admin/connections",),
    "models": ("/admin/models",),
    "api_keys": ("/admin/api-keys",),
    "roles": ("/admin/roles",),
    "users": ("/admin/users",),
    "deleted_users": ("/admin/deleted-users",),
    "groups": ("/admin/groups",),
    "plans": ("/admin/plans",),
    "authentication": ("/admin/authentication",),
    "smtp": ("/admin/smtp",),
    "storage": ("/admin/storage-management", "/admin/retention-policy", "/admin/memory", "/admin/storage"),
    "reports": ("/admin/reports", "/admin/project-usage"),
    "api_logs": ("/admin/logs",),
    "operations": ("/admin/operations", "/admin/debug"),
    "database": ("/admin/database",),
    "agents": (
        "/admin/agents",
        "/admin/knowledge",
        "/admin/agent-tools",
        "/admin/agent-evaluations",
        "/admin/agent-approvals",
        "/admin/agent-activity",
    ),
    "admin_guide": ("/admin/docs",),
    "user_manual": ("/admin/manual",),
    "security_settings": ("/admin/security-settings",),
}

MENUS_BY_CATEGORY: dict[CategoryKey, tuple[MenuKey, ...]] = {}
for _menu, _, _group in MENU_DEFINITIONS:
    MENUS_BY_CATEGORY.setdefault(_group, ())
    MENUS_BY_CATEGORY[_group] = (*MENUS_BY_CATEGORY[_group], _menu)


@dataclass(frozen=True)
class RoleDefinition:
    slug: str
    name: str
    description: str
    category: str
    menu_key: MenuKey | None
    read_only: bool
    is_user_panel: bool = False


def bootstrap_super_admin_role_slugs() -> list[str]:
    """Single Super Admin role — full platform access for the default local admin account."""
    return [SUPER_ADMIN_SLUG]


def is_legacy_super_admin_slug(slug: str | None) -> bool:
    return normalize_role_slug(slug) in (FULL_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG)


def user_has_super_admin_access(slugs: list[str]) -> bool:
    normalized = {normalize_role_slug(s) for s in slugs if s}
    if SUPER_ADMIN_SLUG in normalized:
        return True
    if FULL_ADMIN_SLUG in normalized or LEGACY_ADMIN_SLUG in normalized:
        return True
    return False


def actor_may_assign_roles(
    actor_slugs: list[str],
    new_slugs: list[str],
    previous_slugs: list[str] | None = None,
) -> bool:
    """Return whether ``actor_slugs`` may apply ``new_slugs`` to a target user.

    Super Admin privilege may only be granted, changed, or revoked by an actor
    that already has Super Admin access (explicit ``super_admin`` or legacy
    global full-admin slugs). API Key Admin and User must not escalate to
    platform-wide control.
    """
    actor_is_super = user_has_super_admin_access(actor_slugs)
    if user_has_super_admin_access(new_slugs) and not actor_is_super:
        return False
    if previous_slugs is not None and user_has_super_admin_access(previous_slugs) and not actor_is_super:
        return False
    return True


def user_has_super_read_only_access(slugs: list[str]) -> bool:
    normalized = {normalize_role_slug(s) for s in slugs if s}
    if READ_ONLY_FULL_ADMIN_SLUG in normalized or LEGACY_READ_ONLY_ADMIN_SLUG in normalized:
        return True
    return False


def _build_role_catalog() -> tuple[RoleDefinition, ...]:
    return (
        RoleDefinition(
            slug=USER_SLUG,
            name="User",
            description="Standard end-user access to Chat, Media, Activity, and the User Manual.",
            category=USER_CATEGORY,
            menu_key=None,
            read_only=False,
            is_user_panel=True,
        ),
        RoleDefinition(
            slug=SUPER_ADMIN_SLUG,
            name="Super Admin",
            description="Full read and write access to every admin menu and the entire platform.",
            category=ALL_SECTIONS_CATEGORY,
            menu_key=None,
            read_only=False,
        ),
        RoleDefinition(
            slug=API_KEY_ADMIN_SLUG,
            name="API Key Admin",
            description="Full read and write access to the API Keys admin menu.",
            category=CATEGORY_LABELS["models_api"],
            menu_key="api_keys",
            read_only=False,
        ),
        RoleDefinition(
            slug=DASHBOARD_VIEW_SLUG,
            name="Dashboard View",
            description="View-only access to the Dashboard admin menu.",
            category=CATEGORY_LABELS["overview"],
            menu_key="dashboard",
            read_only=True,
        ),
        RoleDefinition(
            slug=REPORTS_ACCESS_SLUG,
            name="Reports Access",
            description="Access to the Reports admin menu, including preview and export.",
            category=CATEGORY_LABELS["data_reports"],
            menu_key="reports",
            read_only=False,
        ),
        RoleDefinition(
            slug=AGENTS_ADMIN_SLUG,
            name="Agents Administrator",
            description="Manage the full Agents & Knowledge domain without bypassing required approvals.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=AGENT_DESIGNER_SLUG,
            name="Agent Designer",
            description="Create, clone, edit, test, and submit Agent drafts without publishing.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=AGENT_PUBLISHER_SLUG,
            name="Agent Publisher",
            description="Review, publish, archive, and roll back Agent versions.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=KNOWLEDGE_ADMIN_SLUG,
            name="Knowledge Administrator",
            description="Manage Knowledge Bases, ACLs, retrieval policy, and Agent bindings.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=KNOWLEDGE_CURATOR_SLUG,
            name="Knowledge Curator",
            description="Manage documents, metadata, sources, connectors, and ingestion drafts.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=KNOWLEDGE_PUBLISHER_SLUG,
            name="Knowledge Publisher",
            description="Review, publish, archive, and roll back Knowledge releases.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=DOMAIN_APPROVER_SLUG,
            name="Agent Domain Approver",
            description="Approve sensitive HR, Legal, and Finance changes and bindings.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=TOOL_ADMIN_SLUG,
            name="Agent Tool Administrator",
            description="Register and govern Agent tools, permissions, and compatibility.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=AGENT_OPERATIONS_ADMIN_SLUG,
            name="Agent Operations Administrator",
            description="Operate ingestion jobs, dead-letter queues, indexes, and reconciliation.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=False,
        ),
        RoleDefinition(
            slug=AGENT_AUDITOR_SLUG,
            name="Agent Auditor",
            description="Read-only access to Agent evaluation, activity, and audit evidence.",
            category=CATEGORY_LABELS["agents_knowledge"],
            menu_key="agents",
            read_only=True,
        ),
    )


ROLE_CATALOG: tuple[RoleDefinition, ...] = _build_role_catalog()
ROLE_BY_SLUG: dict[str, RoleDefinition] = {r.slug: r for r in ROLE_CATALOG}
VALID_ROLE_SLUGS: frozenset[str] = frozenset(ROLE_BY_SLUG.keys()) | LEGACY_SUPER_ADMIN_SLUGS

AGENT_DOMAIN_PERMISSIONS: frozenset[str] = frozenset(
    {
        "agent.read",
        "agent.create",
        "agent.edit",
        "agent.test",
        "agent.submit",
        "agent.review",
        "agent.publish",
        "agent.rollback",
        "agent.archive",
        "agent.access.manage",
        "agent.knowledge.bind",
        "knowledge.read",
        "knowledge.create",
        "knowledge.edit",
        "knowledge.access.manage",
        "knowledge.documents.write",
        "knowledge.connectors.manage",
        "knowledge.sync.run",
        "knowledge.review",
        "knowledge.publish",
        "knowledge.rollback",
        "knowledge.purge",
        "tool.read",
        "tool.manage",
        "evaluation.read",
        "evaluation.run",
        "evaluation.manage",
        "approval.read",
        "approval.approve",
        "activity.read",
        "governance.read",
        "governance.hold.manage",
        "governance.retention.run",
        "operations.read",
        "operations.retry",
        "operations.reindex",
    }
)

AGENT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    AGENTS_ADMIN_SLUG: AGENT_DOMAIN_PERMISSIONS,
    AGENT_DESIGNER_SLUG: frozenset(
        {
            "agent.read",
            "agent.create",
            "agent.edit",
            "agent.test",
            "agent.submit",
            "knowledge.read",
            "tool.read",
            "evaluation.read",
            "evaluation.run",
        }
    ),
    AGENT_PUBLISHER_SLUG: frozenset(
        {
            "agent.read",
            "agent.review",
            "agent.publish",
            "agent.rollback",
            "agent.archive",
            "knowledge.read",
            "evaluation.read",
            "approval.read",
        }
    ),
    KNOWLEDGE_ADMIN_SLUG: frozenset(
        {
            "agent.read",
            "agent.knowledge.bind",
            "knowledge.read",
            "knowledge.create",
            "knowledge.edit",
            "knowledge.access.manage",
            "knowledge.documents.write",
            "knowledge.connectors.manage",
            "knowledge.sync.run",
            "knowledge.purge",
            "operations.read",
        }
    ),
    KNOWLEDGE_CURATOR_SLUG: frozenset(
        {
            "knowledge.read",
            "knowledge.edit",
            "knowledge.documents.write",
            "knowledge.connectors.manage",
            "knowledge.sync.run",
            "operations.read",
        }
    ),
    KNOWLEDGE_PUBLISHER_SLUG: frozenset(
        {
            "knowledge.read",
            "knowledge.review",
            "knowledge.publish",
            "knowledge.rollback",
            "approval.read",
        }
    ),
    DOMAIN_APPROVER_SLUG: frozenset(
        {
            "agent.read",
            "knowledge.read",
            "approval.read",
            "approval.approve",
            "activity.read",
        }
    ),
    TOOL_ADMIN_SLUG: frozenset(
        {
            "agent.read",
            "tool.read",
            "tool.manage",
            "activity.read",
        }
    ),
    AGENT_OPERATIONS_ADMIN_SLUG: frozenset(
        {
            "knowledge.read",
            "operations.read",
            "operations.retry",
            "operations.reindex",
            "activity.read",
            "governance.read",
            "governance.hold.manage",
            "governance.retention.run",
        }
    ),
    AGENT_AUDITOR_SLUG: frozenset(
        {
            "agent.read",
            "knowledge.read",
            "tool.read",
            "evaluation.read",
            "approval.read",
            "activity.read",
            "governance.read",
            "operations.read",
        }
    ),
}

# Legacy section-scoped slugs removed after migration (still recognized for remap).
LEGACY_SECTION_ROLE_PREFIXES: tuple[str, ...] = tuple(CATEGORY_LABELS.keys())


def expand_legacy_role_slug(slug: str) -> list[str]:
    """Map legacy admin/section roles to current assignable slugs (for DB migration)."""
    raw = (slug or "").strip().lower()
    if raw in (LEGACY_ADMIN_SLUG, FULL_ADMIN_SLUG, SUPER_ADMIN_SLUG):
        return [SUPER_ADMIN_SLUG]
    if raw in (LEGACY_READ_ONLY_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG):
        # Former platform-wide admins keep platform access as Super Admin.
        return [SUPER_ADMIN_SLUG]
    if raw == API_KEY_ADMIN_SLUG:
        return [API_KEY_ADMIN_SLUG]
    if raw in REMOVED_ASSIGNABLE_ROLE_SLUGS:
        return []
    if raw in ROLE_BY_SLUG:
        return [raw]
    for section, menus in MENUS_BY_CATEGORY.items():
        assignable = [menu for menu in menus if menu in ASSIGNABLE_ADMIN_MENUS]
        if raw == f"{section}_full_administrator":
            return [f"{menu}_full_administrator" for menu in assignable]
        if raw == f"{section}_read_only_administrator":
            # Read-only section bundles are retired; drop them.
            return []
    return []


def normalize_role_slug(role: str | None) -> str:
    slug = (role or USER_SLUG).strip().lower()
    if slug == LEGACY_ADMIN_SLUG:
        return FULL_ADMIN_SLUG
    if slug == LEGACY_READ_ONLY_ADMIN_SLUG:
        return READ_ONLY_FULL_ADMIN_SLUG
    return slug


def is_assignable_role_slug(role: str | None) -> bool:
    slug = normalize_role_slug(role)
    return slug in ROLE_BY_SLUG and slug not in REMOVED_ASSIGNABLE_ROLE_SLUGS


def get_role_definition(role: str | None) -> RoleDefinition | None:
    slug = normalize_role_slug(role)
    if slug in REMOVED_ASSIGNABLE_ROLE_SLUGS:
        return None
    return ROLE_BY_SLUG.get(slug)


def list_roles() -> list[dict]:
    return [
        {
            "slug": r.slug,
            "name": r.name,
            "description": r.description,
            "category": r.category,
            "category_key": MENU_GROUP_KEYS[r.menu_key] if r.menu_key else None,
            "menu_key": r.menu_key,
            "read_only": r.read_only,
            "is_user_panel": r.is_user_panel,
        }
        for r in ROLE_CATALOG
    ]


def is_valid_role_slug(role: str | None) -> bool:
    return is_assignable_role_slug(role)


def agent_permissions_for_slugs(slugs: list[str]) -> frozenset[str]:
    """Union action-level permissions for the Agents & Knowledge domain."""

    normalized = {normalize_role_slug(slug) for slug in slugs if slug}
    if any(user_has_super_admin_access([slug]) for slug in normalized):
        return AGENT_DOMAIN_PERMISSIONS
    permissions: set[str] = set()
    for slug in normalized:
        permissions.update(AGENT_ROLE_PERMISSIONS.get(slug, ()))
    return frozenset(permissions)


def user_has_agent_permission(slugs: list[str], permission: str) -> bool:
    normalized_permission = (permission or "").strip().lower()
    return normalized_permission in AGENT_DOMAIN_PERMISSIONS and normalized_permission in agent_permissions_for_slugs(
        slugs
    )


def is_admin_panel_role(role: str | None) -> bool:
    slug = normalize_role_slug(role)
    if slug in REMOVED_ASSIGNABLE_ROLE_SLUGS - {FULL_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG}:
        return False
    if slug in (FULL_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG):
        return True
    definition = get_role_definition(slug)
    return definition is not None and not definition.is_user_panel


def is_full_administrator(role: str | None) -> bool:
    return normalize_role_slug(role) in GLOBAL_FULL_ADMIN_SLUGS


def is_global_platform_role(role: str | None) -> bool:
    slug = normalize_role_slug(role)
    if slug == SUPER_ADMIN_SLUG:
        return True
    return is_legacy_super_admin_slug(role)


def is_read_only_role(role: str | None) -> bool:
    slug = normalize_role_slug(role)
    if slug in (READ_ONLY_FULL_ADMIN_SLUG, LEGACY_READ_ONLY_ADMIN_SLUG):
        return True
    definition = get_role_definition(role)
    return bool(definition and definition.read_only)


def accessible_menu_keys(role: str | None) -> frozenset[MenuKey] | None:
    """Return None when the role can access all admin menus."""
    slug = normalize_role_slug(role)
    if slug in (SUPER_ADMIN_SLUG, FULL_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG):
        return None
    definition = get_role_definition(slug)
    if not definition or definition.is_user_panel or not definition.menu_key:
        return frozenset()
    return frozenset({definition.menu_key})


def can_access_menu(role: str | None, menu: MenuKey) -> bool:
    if not is_admin_panel_role(role):
        return False
    allowed = accessible_menu_keys(role)
    if allowed is None:
        return True
    return menu in allowed


def can_write_menu(role: str | None, menu: MenuKey | None = None) -> bool:
    if not is_admin_panel_role(role):
        return False
    slug = normalize_role_slug(role)
    if menu is not None:
        if menu in USER_APP_MENUS:
            return True
        if not can_access_menu(role, menu):
            return False
    if slug in (READ_ONLY_FULL_ADMIN_SLUG, LEGACY_READ_ONLY_ADMIN_SLUG):
        return False
    if slug.endswith("_read_only_administrator"):
        return False
    return True


# Category helpers (any menu in the group).
def can_access_category(role: str | None, category: CategoryKey) -> bool:
    return any(can_access_menu(role, menu) for menu in MENUS_BY_CATEGORY.get(category, ()))


def can_write(role: str | None, category: CategoryKey | None = None) -> bool:
    if category is None:
        return can_write_menu(role)
    return any(can_write_menu(role, menu) for menu in MENUS_BY_CATEGORY.get(category, ()))


def accessible_category_keys(role: str | None) -> frozenset[CategoryKey] | None:
    allowed_menus = accessible_menu_keys(role)
    if allowed_menus is None:
        return None
    groups: set[CategoryKey] = set()
    for menu in allowed_menus:
        groups.add(MENU_GROUP_KEYS[menu])
    return frozenset(groups)


def path_to_menu(path: str) -> MenuKey | None:
    normalized = path.rstrip("/") or "/"
    best: MenuKey | None = None
    best_len = -1
    for menu, prefixes in MENU_PATH_PREFIXES.items():
        for prefix in prefixes:
            if prefix == "/admin":
                if normalized == "/admin":
                    if len(prefix) > best_len:
                        best, best_len = menu, len(prefix)
                continue
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                if len(prefix) > best_len:
                    best, best_len = menu, len(prefix)
    return best


def session_payload(role: str | None) -> dict:
    return session_payload_for_slugs([normalize_role_slug(role)])


def _role_privilege_rank(slug: str) -> int:
    slug = normalize_role_slug(slug)
    if slug == USER_SLUG:
        return 0
    if slug == READ_ONLY_FULL_ADMIN_SLUG:
        return 10
    if is_read_only_role(slug):
        return 20
    if slug == SUPER_ADMIN_SLUG:
        return 50
    if slug == FULL_ADMIN_SLUG:
        return 40
    if slug.endswith("_full_administrator"):
        return 30
    if is_admin_panel_role(slug):
        return 25
    return 0


def primary_role_slug(slugs: list[str]) -> str:
    normalized = [normalize_role_slug(s) for s in slugs if s]
    if not normalized:
        return USER_SLUG
    admin_slugs = [s for s in normalized if is_admin_panel_role(s)]
    if admin_slugs:
        return min(admin_slugs, key=_role_privilege_rank)
    if USER_SLUG in normalized:
        return USER_SLUG
    return min(normalized, key=_role_privilege_rank)


def _admin_role_slugs(slugs: list[str]) -> list[str]:
    return [normalize_role_slug(s) for s in slugs if is_admin_panel_role(s)]


def effective_accessible_menu_keys(slugs: list[str]) -> frozenset[MenuKey] | None:
    admin_slugs = _admin_role_slugs(slugs)
    if not admin_slugs:
        return frozenset()

    normalized = [normalize_role_slug(s) for s in admin_slugs]
    if user_has_super_admin_access(admin_slugs) or user_has_super_read_only_access(admin_slugs):
        return None

    merged: set[MenuKey] = set()
    for slug in normalized:
        if slug in (SUPER_ADMIN_SLUG, FULL_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG):
            continue
        allowed = accessible_menu_keys(slug)
        if allowed is not None:
            merged |= allowed

    return frozenset(merged) if merged else frozenset()


def user_can_access_menu(slugs: list[str], menu: MenuKey) -> bool:
    return any(can_access_menu(s, menu) for s in slugs)


def user_can_write_menu(slugs: list[str], menu: MenuKey | None = None) -> bool:
    """Write allowed only when every role covering the menu permits writes (lowest access)."""
    admin_slugs = _admin_role_slugs(slugs)
    if not admin_slugs:
        return False
    if menu is not None and menu in USER_APP_MENUS:
        return True
    if menu is not None:
        contributors = [s for s in admin_slugs if can_access_menu(s, menu)]
        if not contributors:
            return False
        return all(can_write_menu(s, menu) for s in contributors)
    admin_menus = [m for m in MENU_LABELS if m not in USER_APP_MENUS]
    return any(user_can_write_menu(slugs, m) for m in admin_menus)


def user_can_access_category(slugs: list[str], category: CategoryKey) -> bool:
    return any(user_can_access_menu(slugs, menu) for menu in MENUS_BY_CATEGORY.get(category, ()))


def user_can_write(slugs: list[str], category: CategoryKey | None = None) -> bool:
    if category is not None:
        menus = MENUS_BY_CATEGORY.get(category, ())
        if not menus:
            return False
        return any(user_can_write_menu(slugs, menu) for menu in menus)
    return user_can_write_menu(slugs)


def user_is_read_only_admin(slugs: list[str]) -> bool:
    """Global read-only admin flag for session/UI — scoped per-menu read-only roles are excluded."""
    if not user_is_admin_panel(slugs):
        return False
    return user_has_super_read_only_access(slugs)


def user_is_admin_panel(slugs: list[str]) -> bool:
    return any(is_admin_panel_role(s) for s in slugs)


def session_payload_for_slugs(slugs: list[str]) -> dict:
    normalized = [normalize_role_slug(s) for s in slugs if s] or [USER_SLUG]
    primary = primary_role_slug(normalized)
    definition = get_role_definition(primary)
    allowed = effective_accessible_menu_keys(normalized)
    names = [get_role_definition(s).name if get_role_definition(s) else s for s in normalized]
    categories = effective_accessible_category_keys(normalized)
    return {
        "role": primary,
        "roles": normalized,
        "role_name": definition.name if definition else primary,
        "role_names": names,
        "read_only": user_is_read_only_admin(normalized),
        "is_admin_panel": user_is_admin_panel(normalized),
        "menus": None if allowed is None else sorted(allowed),
        "categories": None if categories is None else sorted(categories),
    }


def effective_accessible_category_keys(slugs: list[str]) -> frozenset[CategoryKey] | None:
    allowed_menus = effective_accessible_menu_keys(slugs)
    if allowed_menus is None:
        return None
    groups: set[CategoryKey] = set()
    for menu in allowed_menus:
        groups.add(MENU_GROUP_KEYS[menu])
    return frozenset(groups)


union_accessible_category_keys = effective_accessible_category_keys
