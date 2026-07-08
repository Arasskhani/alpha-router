import { Navigate, useLocation } from "react-router-dom";
import { isUserReadOnlyPath, USER_SIDEBAR_NAV } from "../lib/userPanelNav";
import { useReadOnly } from "../context/ReadOnlyContext";

export default function ReadOnlyRouteGuard({ children }: { children: React.ReactNode }) {
  const readOnly = useReadOnly();
  const { pathname } = useLocation();

  if (readOnly && !isUserReadOnlyPath(pathname)) {
    return <Navigate to={USER_SIDEBAR_NAV[0].to} replace />;
  }

  return <>{children}</>;
}
