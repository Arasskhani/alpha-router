import { Navigate, useLocation } from "react-router-dom";
import { getCachedSession } from "../api";
import { isUserReadOnlyPath, userHomePath } from "../lib/userPanelNav";
import { useReadOnly } from "../context/ReadOnlyContext";

export default function ReadOnlyRouteGuard({ children }: { children: React.ReactNode }) {
  const readOnly = useReadOnly();
  const { pathname } = useLocation();

  if (readOnly && !isUserReadOnlyPath(pathname)) {
    return <Navigate to={userHomePath(getCachedSession())} replace />;
  }

  return <>{children}</>;
}
