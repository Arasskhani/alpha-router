import { useMemo } from "react";
import { useLocation } from "react-router-dom";
import Shell from "../../components/Shell";
import AdminPermissionGuard, { useAdminShellNav } from "../../components/AdminPermissionGuard";
import { ReadOnlyProvider } from "../../context/ReadOnlyContext";
import { isAdminUserFeaturePath, userCanWriteAdminPath } from "../../lib/rbac";

export default function AdminLayout() {
  const { nav, session, role } = useAdminShellNav();
  const loc = useLocation();

  const readOnly = useMemo(() => {
    if (session?.is_active === false) return true;
    if (isAdminUserFeaturePath(loc.pathname)) return false;
    return !userCanWriteAdminPath(loc.pathname, session, role);
  }, [loc.pathname, session, role]);

  return (
    <ReadOnlyProvider value={readOnly}>
      <AdminPermissionGuard nav={nav} session={session}>
        <Shell nav={nav} />
      </AdminPermissionGuard>
    </ReadOnlyProvider>
  );
}
