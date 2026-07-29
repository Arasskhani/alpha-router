import type { NavItem } from "../nav/types";
import { adminNavSections } from "../nav/adminNav";
import {
  filterAdminNavFromSession,
  firstAllowedAdminPath,
  type SessionRbac,
} from "./rbac";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "./usageActivityLabel";

/** User panel left sidebar (non-admin accounts). */
export const USER_SIDEBAR_NAV: NavItem[] = [
  { to: "/app/chat", label: "Chat" },
  { to: "/app/media", label: "Media" },
  { to: "/app/my-activity", label: MY_USAGE_AND_ACTIVITY_LABEL },
  { to: "/app/manual", label: "User Manual" },
];

/** Topbar shortcuts, with the caller's first permitted admin page as the final item. */
export function topbarShortcutsForSession(session: SessionRbac | null): NavItem[] {
  const items = [...USER_SIDEBAR_NAV];
  if (!session?.is_admin_panel) return items;

  const adminNav = filterAdminNavFromSession(adminNavSections, session, session.role);
  const adminHome = firstAllowedAdminPath(adminNav);
  if (!adminHome.startsWith("/admin")) return items;

  items.push({ to: adminHome, label: "Administration" });
  return items;
}

/** Routes allowed for disabled (read-only) users besides direct URL blocking. */
export const USER_READ_ONLY_PATHS = [
  "/app/chat",
  "/app/media",
  "/app/my-activity",
  "/app/manual",
] as const;

export function isUserReadOnlyPath(pathname: string): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  return USER_READ_ONLY_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}
