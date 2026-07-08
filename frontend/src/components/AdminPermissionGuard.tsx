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

  useEffect(() => {
    api<SessionRbac>("/api/auth/session")
      .then((data) => {
        setSession(data);
        localStorage.setItem("nitro_role", normalizeRole(data.role));
      })
      .catch(() => {
        setSession(null);
      });
  }, []);

  const fallbackRole = getSessionUser()?.role ?? "user";
  const role = session?.role ?? fallbackRole;
  const nav = useMemo(
    () => filterAdminNavFromSession(adminNavSections, session, normalizeRole(fallbackRole)),
    [session, fallbackRole],
  );

  return { nav, role: normalizeRole(role), session };
}
