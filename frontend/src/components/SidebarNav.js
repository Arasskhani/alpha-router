import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { NavIcon } from "./icons/navIcons";
import { flattenNav, isNavGrouped } from "../nav/types";
import { STORAGE_KEYS } from "../lib/brand";
function NavLink({ item, active, className, onNavigate, }) {
    return (_jsxs(Link, { to: item.to, className: active ? `active ${className ?? ""}`.trim() : className, onClick: onNavigate, children: [item.icon ? _jsx(NavIcon, { name: item.icon }) : null, _jsx("span", { className: "sidebar-nav-label", children: item.label })] }));
}
/** true = expanded; missing key = expanded (default open). */
function loadOpenSections() {
    try {
        const raw = localStorage.getItem(STORAGE_KEYS.adminSidebarOpenSections);
        if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                return parsed;
            }
        }
    }
    catch {
        /* ignore */
    }
    return {};
}
function sectionIsOpen(openSections, title) {
    return openSections[title] !== false;
}
export default function SidebarNav({ nav, className = "", linkClassName, onNavigate }) {
    const loc = useLocation();
    const pathname = loc.pathname.replace(/\/$/, "") || "/";
    const [openSections, setOpenSections] = useState(() => loadOpenSections());
    const userClosedRef = useRef(new Set());
    const isActive = (to) => {
        const target = to.replace(/\/$/, "") || "/";
        return pathname === target;
    };
    const grouped = isNavGrouped(nav);
    useEffect(() => {
        localStorage.setItem(STORAGE_KEYS.adminSidebarOpenSections, JSON.stringify(openSections));
    }, [openSections]);
    useEffect(() => {
        if (!grouped)
            return;
        setOpenSections((prev) => {
            let changed = false;
            const next = { ...prev };
            for (const section of nav) {
                const hasActive = section.items.some((item) => isActive(item.to));
                if (!hasActive || userClosedRef.current.has(section.title))
                    continue;
                if (next[section.title] === false) {
                    next[section.title] = true;
                    changed = true;
                }
            }
            return changed ? next : prev;
        });
        // Only re-expand for the active route when the path changes — not when toggling.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pathname, grouped]);
    function toggleSection(title, event) {
        event.preventDefault();
        event.stopPropagation();
        setOpenSections((prev) => {
            const currentlyOpen = sectionIsOpen(prev, title);
            const nextOpen = !currentlyOpen;
            if (nextOpen) {
                userClosedRef.current.delete(title);
            }
            else {
                userClosedRef.current.add(title);
            }
            return { ...prev, [title]: nextOpen };
        });
    }
    if (!grouped) {
        return (_jsx("nav", { className: className, children: nav.map((n) => (_jsx(NavLink, { item: n, active: isActive(n.to), className: linkClassName, onNavigate: onNavigate }, n.to))) }));
    }
    const navClass = [className, "sidebar-nav--grouped"].filter(Boolean).join(" ");
    return (_jsx("nav", { className: navClass, children: nav.map((section) => {
            const isOpen = sectionIsOpen(openSections, section.title);
            const sectionActive = section.items.some((item) => isActive(item.to));
            return (_jsxs("div", { className: `sidebar-nav-section${section.muted ? " sidebar-nav-section--muted" : ""}${isOpen ? "" : " sidebar-nav-section--collapsed"}${sectionActive ? " sidebar-nav-section--active" : ""}`, children: [_jsxs("button", { type: "button", className: "sidebar-nav-section-toggle", onClick: (e) => toggleSection(section.title, e), "aria-expanded": isOpen, "aria-controls": `sidebar-section-${section.title.replace(/\s+/g, "-").toLowerCase()}`, children: [_jsx("span", { className: "sidebar-nav-section-title", children: section.title }), _jsx("span", { className: "sidebar-nav-section-chevron", "aria-hidden": true, children: isOpen ? "▾" : "▸" })] }), isOpen ? (_jsx("div", { id: `sidebar-section-${section.title.replace(/\s+/g, "-").toLowerCase()}`, className: "sidebar-nav-section-items", children: section.items.map((n) => (_jsx(NavLink, { item: n, active: isActive(n.to), className: linkClassName, onNavigate: onNavigate }, n.to))) })) : null] }, section.title));
        }) }));
}
/** Flat list for mobile drawer title search etc. */
export { flattenNav };
