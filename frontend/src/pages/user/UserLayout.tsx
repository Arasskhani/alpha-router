import { useCallback, useEffect, useMemo, useState } from "react";
import ReadOnlyRouteGuard from "../../components/ReadOnlyRouteGuard";
import Shell from "../../components/Shell";
import { bootstrapSession, getCachedSession, onSessionReady } from "../../api";
import { ReadOnlyProvider } from "../../context/ReadOnlyContext";
import {
  filterAdminNavFromSession,
  firstAllowedAdminPath,
  type SessionRbac,
} from "../../lib/rbac";
import { isSessionActive, setSessionActive } from "../../lib/session";
import { userSidebarNavForSession } from "../../lib/userPanelNav";
import { adminNavSections } from "../../nav/adminNav";
import type { NavItem } from "../../nav/types";

export default function UserLayout() {
  const [active, setActive] = useState(isSessionActive());
  const [session, setSession] = useState<SessionRbac | null>(() => getCachedSession() as SessionRbac | null);

  const refreshSessionStatus = useCallback(() => {
    // Through the shared session, so a section Feature Access opened or closed meanwhile
    // reaches every menu and SectionGate, not this sidebar alone.
    bootstrapSession(true)
      .then((value) => {
        const s = value as SessionRbac;
        const ok = s.is_active !== false;
        setSessionActive(ok);
        setActive(ok);
        setSession(s);
      })
      .catch(() => {
        setActive(isSessionActive());
      });
  }, []);

  // A refresh from elsewhere (a Feature Access refusal) redraws the sidebar too.
  useEffect(() => onSessionReady((s) => setSession(s as SessionRbac)), []);

  useEffect(() => {
    refreshSessionStatus();
    window.addEventListener("focus", refreshSessionStatus);
    return () => window.removeEventListener("focus", refreshSessionStatus);
  }, [refreshSessionStatus]);

  const readOnly = !active;

  const nav = useMemo((): NavItem[] => {
    const items: NavItem[] = userSidebarNavForSession(session);
    if (session?.is_admin_panel) {
      const adminNav = filterAdminNavFromSession(adminNavSections, session, session.role);
      const adminHome = firstAllowedAdminPath(adminNav);
      if (adminHome.startsWith("/admin")) {
        items.push({ to: adminHome, label: "Administration" });
      }
    }
    return items;
  }, [session]);

  return (
    <ReadOnlyProvider value={readOnly}>
      <ReadOnlyRouteGuard>
        <Shell nav={nav} />
      </ReadOnlyRouteGuard>
    </ReadOnlyProvider>
  );
}
