import type { SessionInfo } from "../api";
import { adminNavSections } from "../nav/adminNav";
import { filterAdminNav, firstAllowedAdminPath, isAdminPanelRole, normalizeRole } from "./rbac";

/**
 * Where a signed-in user starts: an admin-panel role on the first admin page it
 * may open, everyone else in chat. Used after sign-in and when "/" is opened
 * (the installed app starts there).
 */
export function homePathFor(session: Pick<SessionInfo, "role">): string {
  if (!isAdminPanelRole(session.role)) return "/app/chat";
  return firstAllowedAdminPath(filterAdminNav(adminNavSections, normalizeRole(session.role)));
}
