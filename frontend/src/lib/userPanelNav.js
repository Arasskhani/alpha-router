import { adminNavSections } from "../nav/adminNav";
import { filterAdminNavFromSession, firstAllowedAdminPath, } from "./rbac";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "./usageActivityLabel";
/** User panel left sidebar (non-admin accounts). */
export const USER_SIDEBAR_NAV = [
    { to: "/app/chat", label: "Chat", icon: "chat" },
    { to: "/app/projects", label: "Projects", icon: "projects" },
    { to: "/app/media", label: "Media", icon: "media" },
    { to: "/app/my-activity", label: MY_USAGE_AND_ACTIVITY_LABEL, icon: "activity" },
    { to: "/app/manual", label: "User Manual", icon: "manual" },
];
/** True for `/app/projects/:id` and `/admin/projects/:id`, not the list or invite page. */
export function isProjectWorkspacePath(pathname) {
    const path = pathname.replace(/\/$/, "") || "/";
    const match = path.match(/^\/(app|admin)\/projects\/([^/]+)$/);
    if (!match)
        return false;
    return match[2] !== "invite";
}
/** Topbar shortcuts, with the caller's first permitted admin page as the final item. */
export function topbarShortcutsForSession(session) {
    const items = [...USER_SIDEBAR_NAV];
    if (!session?.is_admin_panel)
        return items;
    const adminNav = filterAdminNavFromSession(adminNavSections, session, session.role);
    const adminHome = firstAllowedAdminPath(adminNav);
    if (!adminHome.startsWith("/admin"))
        return items;
    items.push({ to: adminHome, label: "Administration", icon: "admin" });
    return items;
}
/** Routes allowed for disabled (read-only) users besides direct URL blocking. */
export const USER_READ_ONLY_PATHS = [
    "/app/chat",
    "/app/projects",
    "/app/media",
    "/app/my-activity",
    "/app/manual",
];
export function isUserReadOnlyPath(pathname) {
    const path = pathname.replace(/\/$/, "") || "/";
    return USER_READ_ONLY_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}
