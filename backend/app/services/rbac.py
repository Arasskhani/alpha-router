"""Role-based access control for NITRO admin panel (per-menu roles)."""

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
    "recommendations",
    "storage",
    "reports",
    "api_logs",
    "operations",
    "database",
    "admin_guide",
    "user_manual",
]

# Nav group label shown in the Roles table Category column.
CategoryKey = Literal[
    "overview",
    "models_api",
    "people_access",
    "integrations",
    "data_reports",
    "monitoring",
    "developer",
]

ALL_SECTIONS_CATEGORY = "All sections"
USER_CATEGORY = "User"

LEGACY_ADMIN_SLUG = "admin"
FULL_ADMIN_SLUG = "full_administrator"
READ_ONLY_FULL_ADMIN_SLUG = "read_only_full_administrator"
LEGACY_READ_ONLY_ADMIN_SLUG = "read_only_administrator"
USER_SLUG = "user"
SUPER_ADMIN_SLUG = "super_admin"

MENU_DEFINITIONS: tuple[tuple[MenuKey, str, CategoryKey], ...] = (
    ("dashboard", "Dashboard", "overview"),
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
    ("recommendations", "Recommendations", "overview"),
    ("smtp", "SMTP Server", "integrations"),
    ("storage", "Storage", "data_reports"),
    ("reports", "Reports", "data_reports"),
    ("api_logs", "API Logs", "data_reports"),
    ("operations", "Operations", "monitoring"),
    ("database", "Database", "monitoring"),
    ("admin_guide", "Admin Guide", "developer"),
    ("user_manual", "User Manual", "developer"),
)

# Menus available to every admin-panel user (no dedicated administrator role).
MENUS_WITHOUT_ASSIGNABLE_ROLES: frozenset[MenuKey] = frozenset(
    {
        "dashboard",
        "chat",
        "media",
        "recommendations",
        "roles",
        "deleted_users",
        "storage",
        "database",
        "admin_guide",
        "user_manual",
    }
)

ASSIGNABLE_ADMIN_MENUS: frozenset[MenuKey] = frozenset(
    menu for menu, _, _ in MENU_DEFINITIONS if menu not in MENUS_WITHOUT_ASSIGNABLE_ROLES
)

# End-user features (chat, media, …) — not admin RBAC menus; always writable when the account is active.
USER_APP_MENUS: frozenset[MenuKey] = frozenset(
    {
        "chat",
        "media",
        "recommendations",
        "user_manual",
    }
)

# Legacy slugs removed from the assignable catalog (still recognized for migration/access).
REMOVED_ASSIGNABLE_ROLE_SLUGS: frozenset[str] = frozenset(
    {
        FULL_ADMIN_SLUG,
        READ_ONLY_FULL_ADMIN_SLUG,
        "dashboard_full_administrator",
        "dashboard_read_only_administrator",
        "chat_full_administrator",
        "chat_read_only_administrator",
        "media_full_administrator",
        "media_read_only_administrator",
        "recommendations_full_administrator",
        "recommendations_read_only_administrator",
        "roles_full_administrator",
        "roles_read_only_administrator",
        "deleted_users_full_administrator",
        "deleted_users_read_only_administrator",
        "database_full_administrator",
        "database_read_only_administrator",
        "admin_guide_full_administrator",
        "admin_guide_read_only_administrator",
        "user_manual_full_administrator",
        "user_manual_read_only_administrator",
        "storage_full_administrator",
        "storage_read_only_administrator",
    }
)

LEGACY_SUPER_ADMIN_SLUGS: frozenset[str] = frozenset(
    {FULL_ADMIN_SLUG, READ_ONLY_FULL_ADMIN_SLUG, LEGACY_READ_ONLY_ADMIN_SLUG, LEGACY_ADMIN_SLUG}
)

GLOBAL_FULL_ADMIN_SLUGS: frozenset[str] = frozenset(
    {SUPER_ADMIN_SLUG, FULL_ADMIN_SLUG, LEGACY_ADMIN_SLUG}
)

MENU_LABELS: dict[MenuKey, str] = {m[0]: m[1] for m in MENU_DEFINITIONS}
MENU_GROUP_KEYS: dict[MenuKey, CategoryKey] = {m[0]: m[2] for m in MENU_DEFINITIONS}
CATEGORY_LABELS: dict[CategoryKey, str] = {
    "overview": "Overview",
    "models_api": "Models & API",
    "people_access": "People & access",
    "integrations": "Integrations",
    "data_reports": "Data & reports",
    "monitoring": "Monitoring",
    "developer": "Developer",
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
    "recommendations": ("/admin/recommendations",),
    "storage": ("/admin/storage-management", "/admin/retention-policy", "/admin/storage"),
    "reports": ("/admin/reports",),
    "api_logs": ("/admin/logs",),
    "operations": ("/admin/operations", "/admin/debug"),
    "database": ("/admin/database",),
    "admin_guide": ("/admin/docs",),
    "user_manual": ("/admin/manual",),
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


def _menu_roles(menu_key: MenuKey, label: str, group: CategoryKey) -> tuple[RoleDefinition, RoleDefinition]:
    group_label = CATEGORY_LABELS[group]
    full_slug = f"{menu_key}_full_administrator"
    read_slug = f"{menu_key}_read_only_administrator"
    return (
        RoleDefinition(
            slug=full_slug,
            name=f"{label} Full Administrator",
            description=f"Full read and write access to the {label} admin menu.",
            category=group_label,
            menu_key=menu_key,
            read_only=False,
        ),
        RoleDefinition(
            slug=read_slug,
            name=f"{label} Read Only Administrator",
            description=f"Read-only access to the {label} admin menu — view data but cannot change settings.",
            category=group_label,
            menu_key=menu_key,
            read_only=True,
        ),
    )


def _assignable_full_role_slugs() -> list[str]:
    return [f"{menu}_full_administrator" for menu in sorted(ASSIGNABLE_ADMIN_MENUS)]


def _assignable_read_only_role_slugs() -> list[str]:
    return [f"{menu}_read_only_administrator" for menu in sorted(ASSIGNABLE_ADMIN_MENUS)]


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
    required = set(_assignable_full_role_slugs())
    return required.issubset(normalized)


def user_has_super_read_only_access(slugs: list[str]) -> bool:
    normalized = {normalize_role_slug(s) for s in slugs if s}
    if READ_ONLY_FULL_ADMIN_SLUG in normalized or LEGACY_READ_ONLY_ADMIN_SLUG in normalized:
        return True
    if user_has_super_admin_access(slugs):
        return False
    required = set(_assignable_read_only_role_slugs())
    return required.issubset(normalized)


def _build_role_catalog() -> tuple[RoleDefinition, ...]:
    roles: list[RoleDefinition] = [
        RoleDefinition(
            slug=USER_SLUG,
            name="User",
            description="Standard end-user access to Chat, Media, My Usage & Activity, and the User Manual.",
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
    ]
    for menu_key, label, group in MENU_DEFINITIONS:
        if menu_key in MENUS_WITHOUT_ASSIGNABLE_ROLES:
            continue
        roles.extend(_menu_roles(menu_key, label, group))
    return tuple(roles)


ROLE_CATALOG: tuple[RoleDefinition, ...] = _build_role_catalog()
ROLE_BY_SLUG: dict[str, RoleDefinition] = {r.slug: r for r in ROLE_CATALOG}
VALID_ROLE_SLUGS: frozenset[str] = frozenset(ROLE_BY_SLUG.keys()) | LEGACY_SUPER_ADMIN_SLUGS

# Legacy section-scoped slugs removed after migration (still recognized for remap).
LEGACY_SECTION_ROLE_PREFIXES: tuple[str, ...] = tuple(CATEGORY_LABELS.keys())


def expand_legacy_role_slug(slug: str) -> list[str]:
    """Map legacy admin/section roles to current per-menu slugs (for DB migration)."""
    raw = (slug or "").strip().lower()
    if raw in (LEGACY_ADMIN_SLUG, FULL_ADMIN_SLUG, SUPER_ADMIN_SLUG):
        return [SUPER_ADMIN_SLUG]
    if raw == LEGACY_READ_ONLY_ADMIN_SLUG:
        return _assignable_read_only_role_slugs()
    if raw == READ_ONLY_FULL_ADMIN_SLUG:
        return _assignable_read_only_role_slugs()
    if raw in REMOVED_ASSIGNABLE_ROLE_SLUGS:
        return []
    if raw in ROLE_BY_SLUG:
        return [raw]
    for section, menus in MENUS_BY_CATEGORY.items():
        assignable = [menu for menu in menus if menu in ASSIGNABLE_ADMIN_MENUS]
        if raw == f"{section}_full_administrator":
            return [f"{menu}_full_administrator" for menu in assignable]
        if raw == f"{section}_read_only_administrator":
            return [f"{menu}_read_only_administrator" for menu in assignable]
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
