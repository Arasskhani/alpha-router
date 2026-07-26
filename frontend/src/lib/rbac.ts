import type { CategoryKey, MenuKey, NavSection } from "../nav/types";

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
};

const FULL_ADMIN = "full_administrator";
const READ_ONLY_FULL_ADMIN = "read_only_full_administrator";
const SUPER_ADMIN = "super_admin";
const LEGACY_READ_ONLY_ADMIN = "read_only_administrator";
const USER = "user";
const LEGACY_ADMIN = "admin";

/** End-user features — not gated by scoped admin read-only roles. */
export const USER_APP_MENUS: MenuKey[] = ["chat", "media", "recommendations", "user_manual"];

export function isUserAppPath(pathname: string): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  return path === "/app" || path.startsWith("/app/");
}

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

export function isReadOnlyAdminRole(role: string | undefined | null): boolean {
  const slug = normalizeRole(role);
  return slug === READ_ONLY_FULL_ADMIN || slug.endsWith("_read_only_administrator");
}

export function isFullAdministrator(role: string | undefined | null): boolean {
  const slug = normalizeRole(role);
  return slug === FULL_ADMIN || slug === SUPER_ADMIN;
}

/** Matches backend ``user_has_super_admin_access`` (super_admin or full/legacy admin). */
export function userHasSuperAdminAccess(
  roles: string[] | undefined | null,
  fallbackRole?: string | null,
): boolean {
  const slugs = (roles?.length ? roles : fallbackRole ? [fallbackRole] : []).map(normalizeRole);
  return slugs.some((s) => s === SUPER_ADMIN || s === FULL_ADMIN);
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
  recommendations: ["/admin/recommendations"],
  storage: ["/admin/storage-management", "/admin/retention-policy", "/admin/storage"],
  reports: ["/admin/reports"],
  api_logs: ["/admin/logs"],
  operations: ["/admin/operations", "/admin/debug"],
  database: ["/admin/database"],
  admin_guide: ["/admin/docs"],
  user_manual: ["/admin/manual"],
};

const MENU_TO_CATEGORY: Record<MenuKey, CategoryKey> = {
  dashboard: "overview",
  chat: "overview",
  recommendations: "overview",
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
  operations: "monitoring",
  database: "monitoring",
  admin_guide: "developer",
  user_manual: "developer",
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

export function accessibleMenuKeys(role: string | undefined | null): MenuKey[] | null {
  const slug = normalizeRole(role);
  if (slug === FULL_ADMIN || slug === READ_ONLY_FULL_ADMIN || slug === SUPER_ADMIN) return null;
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

export function accessibleMenuKeysFromRoles(roles: string[] | undefined | null): MenuKey[] | null {
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

export function isAdminPathAllowed(pathname: string, role: string | undefined | null): boolean {
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

export function groupRolesByCategory(roles: RoleRecord[]): Map<string, RoleRecord[]> {
  const map = new Map<string, RoleRecord[]>();
  for (const role of roles) {
    const group = role.category;
    if (!map.has(group)) map.set(group, []);
    map.get(group)!.push(role);
  }
  return map;
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

  if (allowed === null) {
    return sections.map((section) => ({ ...section, items: [...section.items] }));
  }
  const allowedSet = new Set(allowed);
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => item.menuKey == null || allowedSet.has(item.menuKey)),
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
  if (session && session.menus !== undefined) {
    if (session.menus === null) return true;
    return session.menus.some((menu) => pathMatchesMenu(path, menu));
  }
  return isAdminPathAllowed(path, session?.role ?? fallbackRole);
}

export function canWriteMenu(role: string | undefined | null, menu: MenuKey): boolean {
  const slug = normalizeRole(role);
  if (!isAdminPanelRole(slug)) return false;
  if (USER_APP_MENUS.includes(menu)) return true;
  if (!canAccessMenu(slug, menu)) return false;
  if (slug === READ_ONLY_FULL_ADMIN || slug === LEGACY_READ_ONLY_ADMIN) return false;
  if (slug.endsWith("_read_only_administrator")) return false;
  return true;
}

export function userCanWriteMenu(roles: string[] | undefined | null, menu: MenuKey): boolean {
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
