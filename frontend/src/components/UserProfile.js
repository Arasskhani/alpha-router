import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { clearStoredImageGenerationForCurrentUser } from "../lib/chatStorage";
import { formatSessionDuration, getMyActivityPath, getSessionUser, logout } from "../lib/session";
import { MY_USAGE_AND_ACTIVITY_LABEL } from "../lib/usageActivityLabel";
import { IconActivity, IconLogout } from "./icons/navIcons";
import SettingsModal from "./SettingsModal";
import ThemePicker from "./ThemePicker";
function formatBudgetUsd(value) {
    const rounded = Math.round(value * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}
function formatBudgetLine(budget, loading) {
    if (loading)
        return "…";
    if (!budget)
        return "—";
    if ((budget.monthly_budget_usd ?? 0) <= 0)
        return "No Plan";
    const used = formatBudgetUsd(budget.used_usd ?? 0);
    const total = formatBudgetUsd(budget.monthly_budget_usd ?? 0);
    return `${used}/${total} $`;
}
function IconGear() {
    return (_jsxs("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("circle", { cx: "12", cy: "12", r: "3" }), _jsx("path", { d: "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" })] }));
}
export default function UserProfile({ theme, onThemeChange }) {
    const [open, setOpen] = useState(false);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [duration, setDuration] = useState("");
    const [budget, setBudget] = useState(null);
    const [budgetLoading, setBudgetLoading] = useState(false);
    const wrapRef = useRef(null);
    const user = getSessionUser();
    useEffect(() => {
        if (!user)
            return;
        const tick = () => setDuration(formatSessionDuration(user.loginAt));
        tick();
        const id = window.setInterval(tick, 30_000);
        return () => window.clearInterval(id);
    }, [user?.loginAt]);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (e) => {
            if (wrapRef.current && !wrapRef.current.contains(e.target))
                setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [open]);
    useEffect(() => {
        if (!open)
            return;
        setBudgetLoading(true);
        api("/api/user/budget")
            .then(setBudget)
            .catch(() => setBudget(null))
            .finally(() => setBudgetLoading(false));
    }, [open]);
    if (!user)
        return null;
    // Single letter matches the faint reference topbar avatar style.
    const initials = (user.username.trim().charAt(0) || "?").toUpperCase();
    return (_jsxs("div", { className: "user-profile", ref: wrapRef, children: [_jsxs("button", { type: "button", className: "user-profile-trigger", onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "menu", children: [_jsx("span", { className: "user-avatar", children: initials }), _jsx("span", { className: "user-profile-name", children: user.username }), _jsx("span", { className: "user-profile-chevron", "aria-hidden": true, children: "\u25BE" })] }), open && (_jsxs("div", { className: "user-profile-menu", role: "menu", children: [_jsxs("div", { className: "user-profile-menu-head", children: [_jsx("span", { className: "user-avatar user-avatar-lg", children: initials }), _jsxs("div", { children: [_jsx("div", { className: "user-profile-menu-name", children: user.username }), _jsx("div", { className: "user-profile-menu-role", children: user.role === "admin" ? "Administrator" : "User" })] })] }), _jsxs("div", { className: "user-profile-menu-meta", children: [_jsx("span", { className: "user-profile-meta-label", children: "Signed in for" }), _jsx("span", { className: "user-profile-meta-value", children: duration || "—" })] }), _jsxs("div", { className: "user-profile-menu-meta", children: [_jsx("span", { className: "user-profile-meta-label", children: "Budget" }), _jsx("span", { className: "user-profile-meta-value", children: formatBudgetLine(budget, budgetLoading) })] }), _jsx("div", { className: "user-profile-menu-divider" }), _jsxs(Link, { to: getMyActivityPath(user.role), className: "user-profile-menu-item", role: "menuitem", onClick: () => setOpen(false), children: [_jsx("span", { className: "user-profile-menu-icon", children: _jsx(IconActivity, {}) }), _jsx("span", { children: MY_USAGE_AND_ACTIVITY_LABEL })] }), _jsxs("button", { type: "button", className: "user-profile-menu-item", role: "menuitem", onClick: () => {
                            setOpen(false);
                            setSettingsOpen(true);
                        }, children: [_jsx("span", { className: "user-profile-menu-icon", children: _jsx(IconGear, {}) }), _jsx("span", { children: "Settings" })] }), _jsxs("button", { type: "button", className: "user-profile-menu-item user-profile-menu-item-danger", role: "menuitem", onClick: () => {
                            void clearStoredImageGenerationForCurrentUser().finally(() => logout());
                        }, children: [_jsx("span", { className: "user-profile-menu-icon", children: _jsx(IconLogout, {}) }), _jsx("span", { children: "Log out" })] }), _jsx("div", { className: "user-profile-menu-divider" }), _jsx("div", { className: "user-profile-theme", children: _jsx(ThemePicker, { value: theme, onChange: onThemeChange, compact: true }) })] })), _jsx(SettingsModal, { open: settingsOpen, onClose: () => setSettingsOpen(false), theme: theme, onThemeChange: onThemeChange })] }));
}
