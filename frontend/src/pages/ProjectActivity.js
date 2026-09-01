import { jsx as _jsx } from "react/jsx-runtime";
import { useMemo } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import ActivityView from "../components/activity/ActivityView";
import { getCachedSession } from "../api";
import { canAccessMenu } from "../lib/rbac";
import { USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";
/** Keep a single Activity URL: /app/projects/:id/activity */
export function AdminProjectActivityRedirect() {
    const { projectId = "" } = useParams();
    const { search } = useLocation();
    return _jsx(Navigate, { to: `/app/projects/${projectId}/activity${search}`, replace: true });
}
function sessionCanAccessReports(session) {
    if (!session?.is_admin_panel)
        return false;
    if (session.menus == null)
        return true;
    return session.menus.includes("reports") || canAccessMenu(session.role, "reports");
}
export default function ProjectActivity() {
    const { projectId = "" } = useParams();
    const session = getCachedSession();
    const reportsAdmin = sessionCanAccessReports(session);
    const backLink = useMemo(() => {
        if (reportsAdmin)
            return { to: "/admin/project-usage", label: "← Projects usage" };
        return { to: `/app/projects/${projectId}`, label: "← Project" };
    }, [projectId, reportsAdmin]);
    return (_jsx(ActivityView, { scope: "project", projectId: projectId, title: USAGE_AND_ACTIVITY_LABEL, backLink: backLink }));
}
