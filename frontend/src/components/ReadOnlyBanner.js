import { jsx as _jsx } from "react/jsx-runtime";
import { useLocation } from "react-router-dom";
export default function ReadOnlyBanner({ className = "" }) {
    const path = useLocation().pathname;
    const adminReadOnly = path.startsWith("/admin");
    return (_jsx("div", { className: `readonly-account-banner alert alert-warning${className ? ` ${className}` : ""}`, children: adminReadOnly
            ? "Read-only administrator: you can browse admin pages and dashboards, but cannot create, edit, or delete anything."
            : "Your account is disabled (read-only). Browse your chat history here; use the profile menu for Activity. You cannot send messages or use models." }));
}
