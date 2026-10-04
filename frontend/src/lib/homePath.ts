import type { SessionInfo } from "../api";
import { adminNavSections } from "../nav/adminNav";
import { filterAdminNav, firstAllowedAdminPath, isAdminPanelRole, normalizeRole } from "./rbac";
import { userHomePath } from "./userPanelNav";

/**
 * Where a signed-in user starts: an admin-panel role on the first admin page it
 * may open, everyone else in chat (or, with Chat closed by Feature Access, the
 * first section that is open). Used after sign-in and when "/" is opened
 * (the installed app starts there).
 */
export function homePathFor(session: Pick<SessionInfo, "role"> & { features?: unknown }): string {
  if (!isAdminPanelRole(session.role)) return userHomePath(session);
  return firstAllowedAdminPath(filterAdminNav(adminNavSections, normalizeRole(session.role)));
}
