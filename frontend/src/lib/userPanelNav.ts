import type { NavItem } from "../nav/types";
import { adminNavSections } from "../nav/adminNav";
import {
  filterAdminNavFromSession,
  firstAllowedAdminPath,
  type SessionRbac,
} from "./rbac";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "./usageActivityLabel";

/** User panel left sidebar (non-admin accounts); drawn through userSidebarNavForSession. */
const USER_SIDEBAR_NAV: NavItem[] = [
  { to: "/app/chat", label: "Chat", icon: "chat" },
  { to: "/app/projects", label: "Projects", icon: "projects" },
  { to: "/app/media", label: "Media", icon: "media" },
  { to: "/app/my-activity", label: MY_USAGE_AND_ACTIVITY_LABEL, icon: "activity" },
  { to: "/app/manual", label: "User Manual", icon: "manual" },
];

/** The web sections Feature Access can close for an account. */
export type WebSection = "chat" | "projects";

const SECTION_PATHS: Record<WebSection, string> = { chat: "/app/chat", projects: "/app/projects" };

/** Any session shape: only its `features` block is read. */
type SectionSession = object | null | undefined;

/**
 * Whether this account may open a web section (`/api/auth/session.features.chat` / `.projects`).
 * Missing means open: an older server does not send it.
 */
export function sectionEnabled(session: SectionSession, section: WebSection): boolean {
  const features = (session as { features?: Record<string, unknown> | null } | null | undefined)?.features;
  return features?.[section] !== false;
}

/** The user sidebar without the sections Feature Access closed for this account. */
export function userSidebarNavForSession(session: SectionSession): NavItem[] {
  return USER_SIDEBAR_NAV.filter((item) =>
    (Object.keys(SECTION_PATHS) as WebSection[]).every(
      (section) => SECTION_PATHS[section] !== item.to || sectionEnabled(session, section),
    ),
  );
}

/** Where a user starts: Chat when it is open, else the first section that is. */
export function userHomePath(session: SectionSession): string {
  return userSidebarNavForSession(session)[0]?.to ?? "/app/media";
}

/** True for `/app/projects/:id` and `/admin/projects/:id`, not the list or invite page. */
export function isProjectWorkspacePath(pathname: string): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  const match = path.match(/^\/(app|admin)\/projects\/([^/]+)$/);
  if (!match) return false;
  return match[2] !== "invite";
}

/** Topbar shortcuts, with the caller's first permitted admin page as the final item. */
export function topbarShortcutsForSession(session: SessionRbac | null): NavItem[] {
  const items = userSidebarNavForSession(session);
  if (!session?.is_admin_panel) return items;

  const adminNav = filterAdminNavFromSession(adminNavSections, session, session.role);
  const adminHome = firstAllowedAdminPath(adminNav);
  if (!adminHome.startsWith("/admin")) return items;

  items.push({ to: adminHome, label: "Administration", icon: "admin" });
  return items;
}

/** Routes allowed for disabled (read-only) users besides direct URL blocking. */
const USER_READ_ONLY_PATHS = [
  "/app/chat",
  "/app/projects",
  "/app/media",
  "/app/my-activity",
  "/app/manual",
] as const;

export function isUserReadOnlyPath(pathname: string): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  return USER_READ_ONLY_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}
