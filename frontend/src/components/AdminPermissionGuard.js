import { jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api } from "../api";
import { getSessionUser } from "../lib/session";
import { filterAdminNavFromSession, firstAllowedAdminPath, isAdminPathAllowedForSession, normalizeRole, } from "../lib/rbac";
import { adminNavSections } from "../nav/adminNav";
export default function AdminPermissionGuard({ nav, session, children }) {
    const loc = useLocation();
    const fallbackRole = normalizeRole(getSessionUser()?.role);
    const path = loc.pathname.replace(/\/$/, "") || "/";
    if (!isAdminPathAllowedForSession(path, session, fallbackRole)) {
        const fallback = firstAllowedAdminPath(nav);
        return _jsx(Navigate, { to: fallback, replace: true });
    }
    return _jsx(_Fragment, { children: children });
}
export function useAdminShellNav() {
    const [session, setSession] = useState(null);
    useEffect(() => {
        api("/api/auth/session")
            .then((data) => {
            setSession(data);
        })
            .catch(() => {
            setSession(null);
        });
    }, []);
    const fallbackRole = getSessionUser()?.role ?? "user";
    const role = session?.role ?? fallbackRole;
    const nav = useMemo(() => filterAdminNavFromSession(adminNavSections, session, normalizeRole(fallbackRole)), [session, fallbackRole]);
    return { nav, role: normalizeRole(role), session };
}
