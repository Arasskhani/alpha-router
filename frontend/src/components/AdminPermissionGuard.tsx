import { useEffect, useMemo, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api } from "../api";
import { getSessionUser } from "../lib/session";
import {
  filterAdminNavFromSession,
  firstAllowedAdminPath,
  isAdminPathAllowedForSession,
  normalizeRole,
  type SessionRbac,
} from "../lib/rbac";
import { adminNavSections } from "../nav/adminNav";
import type { NavSection } from "../nav/types";

type Props = {
  nav: NavSection[];
  session: SessionRbac | null;
  children: React.ReactNode;
};

export default function AdminPermissionGuard({ nav, session, children }: Props) {
  const loc = useLocation();
  const fallbackRole = normalizeRole(getSessionUser()?.role);
  const path = loc.pathname.replace(/\/$/, "") || "/";

  if (!isAdminPathAllowedForSession(path, session, fallbackRole)) {
    const fallback = firstAllowedAdminPath(nav);
    return <Navigate to={fallback} replace />;
  }

  return <>{children}</>;
}

export function useAdminShellNav() {
  const [session, setSession] = useState<SessionRbac | null>(null);
  // Whether the live session has actually been read. Without it, "no session
  // yet" and "the session request failed" were the same value, and
  // userCanWriteAdminPath falls back to the cached role from localStorage when
  // it sees null - so a deactivated administrator whose fetch failed got a
  // fully write-enabled admin UI, and kept it until they reloaded. The server
  // still refuses the writes; a read-only UI that fails open is not a control.
  const [sessionKnown, setSessionKnown] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await api<SessionRbac>("/api/auth/session");
        if (cancelled) return;
        setSession(data);
        setSessionKnown(true);
      } catch {
        if (cancelled) return;
        setSession(null);
        setSessionKnown(false);
      }
    }

    void load();
    // An account deactivated mid-session should not keep the write UI until a
    // manual reload; coming back to the tab is the cheapest moment to re-ask.
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  const fallbackRole = getSessionUser()?.role ?? "user";
  const role = session?.role ?? fallbackRole;
  const nav = useMemo(
    () => filterAdminNavFromSession(adminNavSections, session, normalizeRole(fallbackRole)),
    [session, fallbackRole],
  );

  return { nav, role: normalizeRole(role), session, sessionKnown };
}
