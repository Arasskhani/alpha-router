import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useReadOnly } from "../context/ReadOnlyContext";
/** Consistent admin page shell: fluid width, responsive typography. */
export default function AdminPage({ title, children, actions }) {
    const readOnly = useReadOnly();
    return (_jsxs("div", { className: `admin-page${readOnly ? " admin-page--read-only" : ""}`, children: [_jsxs("header", { className: "admin-page-header", children: [_jsx("h1", { children: title }), actions ? _jsx("div", { className: "admin-page-actions", children: actions }) : null] }), children] }));
}
