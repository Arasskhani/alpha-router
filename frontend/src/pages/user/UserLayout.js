import { jsx as _jsx } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import ReadOnlyRouteGuard from "../../components/ReadOnlyRouteGuard";
import Shell from "../../components/Shell";
import { api } from "../../api";
import { ReadOnlyProvider } from "../../context/ReadOnlyContext";
import { filterAdminNavFromSession, firstAllowedAdminPath, } from "../../lib/rbac";
import { isSessionActive, setSessionActive } from "../../lib/session";
import { USER_SIDEBAR_NAV } from "../../lib/userPanelNav";
import { adminNavSections } from "../../nav/adminNav";
export default function UserLayout() {
    const [active, setActive] = useState(isSessionActive());
    const [session, setSession] = useState(null);
    const refreshSessionStatus = useCallback(() => {
        api("/api/auth/session")
            .then((s) => {
            const ok = s.is_active !== false;
            setSessionActive(ok);
            setActive(ok);
            setSession(s);
        })
            .catch(() => {
            setActive(isSessionActive());
        });
    }, []);
    useEffect(() => {
        refreshSessionStatus();
        window.addEventListener("focus", refreshSessionStatus);
        return () => window.removeEventListener("focus", refreshSessionStatus);
    }, [refreshSessionStatus]);
    const readOnly = !active;
    const nav = useMemo(() => {
        const items = [...USER_SIDEBAR_NAV];
        if (session?.is_admin_panel) {
            const adminNav = filterAdminNavFromSession(adminNavSections, session, session.role);
            const adminHome = firstAllowedAdminPath(adminNav);
            if (adminHome.startsWith("/admin")) {
                items.push({ to: adminHome, label: "Administration" });
            }
        }
        return items;
    }, [session]);
    return (_jsx(ReadOnlyProvider, { value: readOnly, children: _jsx(ReadOnlyRouteGuard, { children: _jsx(Shell, { nav: nav }) }) }));
}
