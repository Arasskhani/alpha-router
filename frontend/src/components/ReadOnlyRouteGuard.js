import { jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { Navigate, useLocation } from "react-router-dom";
import { isUserReadOnlyPath, USER_SIDEBAR_NAV } from "../lib/userPanelNav";
import { useReadOnly } from "../context/ReadOnlyContext";
export default function ReadOnlyRouteGuard({ children }) {
    const readOnly = useReadOnly();
    const { pathname } = useLocation();
    if (readOnly && !isUserReadOnlyPath(pathname)) {
        return _jsx(Navigate, { to: USER_SIDEBAR_NAV[0].to, replace: true });
    }
    return _jsx(_Fragment, { children: children });
}
