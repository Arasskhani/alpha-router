import type { CategoryKey, MenuKey, NavItem, NavSection } from "../nav/types";

export type { CategoryKey, MenuKey };

export type RoleRecord = {
  slug: string;
  name: string;
  description: string;
  category: string;
  category_key: CategoryKey | null;
  menu_key: MenuKey | null;
  read_only: boolean;
  is_user_panel: boolean;
};

export type SessionRbac = {
  username: string;
  role: string;
  roles?: string[];
  role_name?: string;
  role_names?: string[];
  is_active: boolean;
  read_only?: boolean;
  is_admin_panel?: boolean;
  menus?: MenuKey[] | null;
  categories?: CategoryKey[] | null;
  /** Server feature flags (Phase 4.5). Missing = feature on, for older backends. */
  features?: { agents_platform?: boolean } | null;
};

/** Menus that belong to preview features and disappear when the feature is off. */
const PREVIEW_FEATURE_MENUS: Record<string, MenuKey> = { agents_platform: "agents" };

function disabledPreviewMenus(session: SessionRbac | null): Set<MenuKey> {
  const off = new Set<MenuKey>();
  const features = session?.features;
  if (!features) return off;
  for (const [feature, menu] of Object.entries(PREVIEW_FEATURE_MENUS)) {
    if ((features as Record<string, boolean | undefined>)[feature] === false) off.add(menu);
  }
  return off;
}

const FULL_ADMIN = "full_administrator";
const READ_ONLY_FULL_ADMIN = "read_only_full_administrator";
const SUPER_ADMIN = "super_admin";
const LEGACY_READ_ONLY_ADMIN = "read_only_administrator";
const USER = "user";
const LEGACY_ADMIN = "admin";
const READ_ONLY_SUPER_ADMIN = "read_only_super_admin";

/**
 * Roles that answer for the whole platform rather than naming one menu.
 *
 * These two sets are the mirror of the backend's GLOBAL_FULL_ADMIN_SLUGS and
 * GLOBAL_READ_ONLY_SLUGS. Keeping them as sets rather than inline comparisons
 * matters here: accessibleMenuKeys gives an unrecognised slug *zero* menus, so
 * a global role this file has not been told about disappears from the UI
 * entirely rather than failing loudly.
 */
const GLOBAL_WRITE_ROLES = new Set([SUPER_ADMIN, FULL_ADMIN, LEGACY_ADMIN]);
const GLOBAL_READ_ONLY_ROLES = new Set([READ_ONLY_SUPER_ADMIN, READ_ONLY_FULL_ADMIN, LEGACY_READ_ONLY_ADMIN]);
const GLOBAL_ROLES = new Set([...GLOBAL_WRITE_ROLES, ...GLOBAL_READ_ONLY_ROLES]);
const AGENT_PLATFORM_ROLES = new Set([
  "agents_administrator",
  "agent_designer",
  "agent_publisher",
  "knowledge_administrator",
  "knowledge_curator",
  "knowledge_publisher",
  "agent_domain_approver",
  "agent_tool_administrator",
  "agent_operations_administrator",
  "agent_auditor",
]);

/** End-user features — not gated by scoped admin read-only roles. */
const USER_APP_MENUS: MenuKey[] = ["chat", "media", "user_manual"];
export function normalizeRole(role: string | undefined | null): string {
  const slug = (role || USER).trim().toLowerCase();
  if (slug === LEGACY_ADMIN) return FULL_ADMIN;
  if (slug === LEGACY_READ_ONLY_ADMIN) return READ_ONLY_FULL_ADMIN;
  return slug;
}

export function isAdminPanelRole(role: string | undefined | null): boolean {
  const slug = normalizeRole(role);
  return slug !== USER && !slug.endsWith("_user");
}

/** Matches backend ``user_has_super_admin_access`` (super_admin or full/legacy admin). */
export function userHasSuperAdminAccess(
  roles: string[] | undefined | null,
  fallbackRole?: string | null,
): boolean {
  const slugs = (roles?.length ? roles : fallbackRole ? [fallbackRole] : []).map(normalizeRole);
  return slugs.some((s) => GLOBAL_WRITE_ROLES.has(s));
}

const MENU_PATH_PREFIXES: Record<MenuKey, string[]> = {
  dashboard: ["/admin", "/admin/my-activity"],
  chat: ["/admin/chat"],
  media: ["/admin/media"],
  connections: ["/admin/connections"],
  models: ["/admin/models"],
  api_keys: ["/admin/api-keys"],
  roles: ["/admin/roles"],
  users: ["/admin/users"],
  deleted_users: ["/admin/deleted-users"],
  groups: ["/admin/groups"],
  plans: ["/admin/plans"],
  authentication: ["/admin/authentication"],
  smtp: ["/admin/smtp"],
  storage: ["/admin/storage-management", "/admin/retention-policy", "/admin/memory", "/admin/storage"],
  reports: ["/admin/reports", "/admin/project-usage"],
  api_logs: ["/admin/logs", "/admin/admin-logs"],
  operations: ["/admin/operations", "/admin/debug", "/admin/code-interpreter"],
  database: ["/admin/database"],
  agents: [
    "/admin/agents",
    "/admin/knowledge",
    "/admin/agent-tools",
    "/admin/agent-evaluations",
    "/admin/agent-approvals",
    "/admin/agent-activity",
  ],
  admin_guide: ["/admin/docs"],
  user_manual: ["/admin/manual"],
  security_settings: ["/admin/security-settings"],
};

const MENU_TO_CATEGORY: Record<MenuKey, CategoryKey> = {
  dashboard: "overview",
  chat: "overview",
  media: "overview",
  connections: "models_api",
  models: "models_api",
  api_keys: "models_api",
  roles: "people_access",
  users: "people_access",
  deleted_users: "people_access",
  groups: "people_access",
  plans: "people_access",
  authentication: "people_access",
  smtp: "integrations",
  storage: "data_reports",
  reports: "data_reports",
  api_logs: "data_reports",
  operations: "overview",
  database: "overview",
  agents: "agents_knowledge",
  admin_guide: "developer",
  user_manual: "developer",
  security_settings: "security",
};

function pathMatchesMenu(path: string, menu: MenuKey): boolean {
  return MENU_PATH_PREFIXES[menu].some((prefix) => {
    if (prefix === "/admin") {
      return path === "/admin";
    }
    return path === prefix || path.startsWith(`${prefix}/`);
  });
}

export function pathToMenu(pathname: string): MenuKey | null {
  const path = pathname.replace(/\/$/, "") || "/";
  let best: MenuKey | null = null;
  let bestLen = -1;
  for (const menu of Object.keys(MENU_PATH_PREFIXES) as MenuKey[]) {
    for (const prefix of MENU_PATH_PREFIXES[menu]) {
      const matches =
        prefix === "/admin" ? path === "/admin" : path === prefix || path.startsWith(`${prefix}/`);
      if (matches && prefix.length > bestLen) {
        best = menu;
        bestLen = prefix.length;
      }
    }
  }
  return best;
}

export function isAdminUserFeaturePath(pathname: string): boolean {
  const menu = pathToMenu(pathname);
  return menu !== null && USER_APP_MENUS.includes(menu);
}

function accessibleMenuKeys(role: string | undefined | null): MenuKey[] | null {
  const slug = normalizeRole(role);
  if (GLOBAL_ROLES.has(slug)) return null;
  if (AGENT_PLATFORM_ROLES.has(slug)) return ["agents"];
  const match = slug.match(
    /^([a-z_]+)_(full|read_only)_administrator$/,
  );
  if (!match) return [];
  const menuKey = match[1] as MenuKey;
  return menuKey in MENU_PATH_PREFIXES ? [menuKey] : [];
}

export function canAccessMenu(role: string | undefined | null, menu: MenuKey): boolean {
  if (!isAdminPanelRole(role)) return false;
  const allowed = accessibleMenuKeys(role);
  if (allowed === null) return true;
  return allowed.includes(menu);
}

function accessibleMenuKeysFromRoles(roles: string[] | undefined | null): MenuKey[] | null {
  const slugs = (roles ?? []).map(normalizeRole).filter(Boolean);
  if (!slugs.length) return [];
  let all = false;
  const merged = new Set<MenuKey>();
  for (const slug of slugs) {
    const allowed = accessibleMenuKeys(slug);
    if (allowed === null) {
      all = true;
      break;
    }
    for (const menu of allowed) merged.add(menu);
  }
  return all ? null : [...merged];
}

export function firstAllowedAdminPath(sections: NavSection[]): string {
  for (const section of sections) {
    for (const item of section.items) {
      if (item.menuKey != null && item.to.startsWith("/admin")) {
        return item.to;
      }
    }
  }
  return "/app/chat";
}

export function filterAdminNav(sections: NavSection[], role: string | undefined | null): NavSection[] {
  const allowed = accessibleMenuKeys(role);
  if (allowed === null) return sections.map((s) => ({ ...s, items: [...s.items] }));
  const allowedSet = new Set(allowed);
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => item.menuKey == null || allowedSet.has(item.menuKey)),
    }))
    .filter((section) => section.items.length > 0);
}

function isAdminPathAllowed(pathname: string, role: string | undefined | null): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  if (!path.startsWith("/admin")) return false;
  const allowed = accessibleMenuKeys(role);
  if (allowed === null) return true;
  return allowed.some((menu) => pathMatchesMenu(path, menu));
}

export function getMyActivityPath(role: string): string {
  return isAdminPanelRole(role) ? "/admin/my-activity" : "/app/my-activity";
}

export function roleLabel(catalog: RoleRecord[], slug: string): string {
  return catalog.find((r) => r.slug === normalizeRole(slug))?.name ?? normalizeRole(slug);
}
export function filterAdminNavFromSession(
  sections: NavSection[],
  session: SessionRbac | null,
  fallbackRole: string,
): NavSection[] {
  const allowed =
    session?.menus !== undefined
      ? session.menus
      : accessibleMenuKeysFromRoles(session?.roles?.length ? session.roles : [session?.role ?? fallbackRole]);

  const hidden = disabledPreviewMenus(session);
  const visible = (item: NavItem) => item.menuKey == null || !hidden.has(item.menuKey);
  if (allowed === null) {
    return sections
      .map((section) => ({ ...section, items: section.items.filter(visible) }))
      .filter((section) => section.items.length > 0);
  }
  const allowedSet = new Set(allowed);
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => visible(item) && (item.menuKey == null || allowedSet.has(item.menuKey))),
    }))
    .filter((section) => section.items.length > 0);
}

export function isAdminPathAllowedForSession(
  pathname: string,
  session: SessionRbac | null,
  fallbackRole?: string,
): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  if (!path.startsWith("/admin")) return false;
  for (const menu of disabledPreviewMenus(session)) {
    if (pathMatchesMenu(path, menu)) return false;
  }
  if (session && session.menus !== undefined) {
    if (session.menus === null) return true;
    return session.menus.some((menu) => pathMatchesMenu(path, menu));
  }
  return isAdminPathAllowed(path, session?.role ?? fallbackRole);
}

function canWriteMenu(role: string | undefined | null, menu: MenuKey): boolean {
  const slug = normalizeRole(role);
  if (!isAdminPanelRole(slug)) return false;
  if (USER_APP_MENUS.includes(menu)) return true;
  if (!canAccessMenu(slug, menu)) return false;
  // Before the suffix test below, which only catches slugs named after a menu:
  // a global read-only slug named after the role would slip past it and be
  // granted write access.
  if (GLOBAL_READ_ONLY_ROLES.has(slug)) return false;
  if (slug.endsWith("_read_only_administrator")) return false;
  return true;
}

function userCanWriteMenu(roles: string[] | undefined | null, menu: MenuKey): boolean {
  const slugs = (roles ?? []).map(normalizeRole).filter(isAdminPanelRole);
  if (!slugs.length) return false;
  const contributors = slugs.filter((slug) => canAccessMenu(slug, menu));
  if (!contributors.length) return false;
  return contributors.every((slug) => canWriteMenu(slug, menu));
}

export function userCanWriteAdminPath(
  pathname: string,
  session: SessionRbac | null,
  fallbackRole?: string,
): boolean {
  if (session?.is_active === false) return false;
  if (isAdminUserFeaturePath(pathname)) return true;
  const menu = pathToMenu(pathname);
  if (!menu) return false;
  const roles = session?.roles?.length ? session.roles : [session?.role ?? fallbackRole ?? USER];
  return userCanWriteMenu(roles, menu);
}

export function menuCategory(menu: MenuKey): CategoryKey {
  return MENU_TO_CATEGORY[menu];
}
