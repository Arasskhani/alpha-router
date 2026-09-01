import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { getCachedSession } from "../api";
import { getSessionUser } from "../lib/session";
import { isProjectWorkspacePath, topbarShortcutsForSession } from "../lib/userPanelNav";
import { listProjects, projectRoleLabel } from "../lib/projectsApi";
import { NavIcon } from "./icons/navIcons";
import UserProfile from "./UserProfile";
function ProjectsShortcut({ to, label, active, }) {
    const navigate = useNavigate();
    const [open, setOpen] = useState(false);
    const [recent, setRecent] = useState(null);
    const wrapRef = useRef(null);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (event) => {
            if (wrapRef.current && !wrapRef.current.contains(event.target)) {
                setOpen(false);
            }
        };
        const onKey = (event) => {
            if (event.key === "Escape")
                setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("mousedown", onDoc);
            document.removeEventListener("keydown", onKey);
        };
    }, [open]);
    useEffect(() => {
        if (!open)
            return;
        let cancelled = false;
        void listProjects("recent", { limit: 8 })
            .then((data) => {
            if (!cancelled)
                setRecent(data.projects);
        })
            .catch(() => {
            if (!cancelled)
                setRecent([]);
        });
        return () => {
            cancelled = true;
        };
    }, [open]);
    return (_jsxs("div", { className: "topbar-shortcut-split", ref: wrapRef, children: [_jsxs(NavLink, { to: to, className: `topbar-shortcut${active ? " topbar-shortcut--active" : ""}`, title: label, "aria-label": label, children: [_jsx(NavIcon, { name: "projects" }), _jsx("span", { className: "topbar-shortcut__label", children: label })] }), _jsx("button", { type: "button", className: `topbar-shortcut-chevron${open || active ? " topbar-shortcut-chevron--active" : ""}`, "aria-label": "Recent projects", "aria-haspopup": "menu", "aria-expanded": open, onClick: (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setOpen((prev) => !prev);
                }, children: _jsx("svg", { width: "10", height: "10", viewBox: "0 0 12 12", "aria-hidden": true, children: _jsx("path", { d: "M2.5 4.5 L6 8 L9.5 4.5", fill: "none", stroke: "currentColor", strokeWidth: "1.5" }) }) }), open ? (_jsxs("div", { className: "topbar-projects-menu", role: "menu", children: [recent == null ? (_jsx("p", { className: "topbar-projects-menu__empty", children: "Loading\u2026" })) : recent.length === 0 ? (_jsx("p", { className: "topbar-projects-menu__empty", children: "No recent projects" })) : (recent.map((project) => (_jsxs("button", { type: "button", role: "menuitem", className: "topbar-projects-menu__item", onClick: () => {
                            setOpen(false);
                            navigate(`/app/projects/${encodeURIComponent(project.id)}`);
                        }, children: [_jsx("span", { className: "topbar-projects-menu__name", children: project.name }), project.myRole ? (_jsx("span", { className: "topbar-projects-menu__role", children: projectRoleLabel(project.myRole) })) : null] }, project.id)))), _jsx("button", { type: "button", className: "topbar-projects-menu__item topbar-projects-menu__item--all", onClick: () => {
                            setOpen(false);
                            navigate(to);
                        }, children: "All projects" })] })) : null] }));
}
/** Top-bar actions: text shortcuts + faint profile menu (OpenRouter-style). */
export default function TopbarNav({ theme, onThemeChange }) {
    const user = getSessionUser();
    const location = useLocation();
    if (!user)
        return null;
    const shortcuts = topbarShortcutsForSession(getCachedSession());
    const inProjectWorkspace = isProjectWorkspacePath(location.pathname);
    return (_jsxs("div", { className: "topbar-nav", children: [_jsx("nav", { className: "topbar-shortcuts", "aria-label": "Quick links", children: shortcuts.map((item) => {
                    if (item.icon === "projects") {
                        const projectActive = inProjectWorkspace ||
                            location.pathname === item.to ||
                            location.pathname.startsWith(`${item.to}/`);
                        return (_jsx(ProjectsShortcut, { to: item.to, label: item.label, active: projectActive }, item.to));
                    }
                    return (_jsxs(NavLink, { to: item.to, title: item.label, "aria-label": item.label, className: ({ isActive }) => {
                            const chatActive = item.icon === "chat" && inProjectWorkspace ? false : isActive;
                            return `topbar-shortcut${chatActive ? " topbar-shortcut--active" : ""}`;
                        }, children: [item.icon ? _jsx(NavIcon, { name: item.icon }) : null, _jsx("span", { className: "topbar-shortcut__label", children: item.label })] }, item.to));
                }) }), _jsx(UserProfile, { theme: theme, onThemeChange: onThemeChange })] }));
}
