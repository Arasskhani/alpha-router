import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useReadOnly } from "../context/ReadOnlyContext";
import { ADMIN_WRITE_LOCK_TITLE } from "../lib/adminWriteLock";
import { normalizeRole, roleLabel } from "../lib/rbac";
const MENU_MIN_WIDTH = 220;
const MENU_MAX_HEIGHT = 360;
const VIEWPORT_PAD = 8;
function summaryText(slugs, catalog) {
    if (slugs.length === 0)
        return roleLabel(catalog, "user");
    if (slugs.length === 1)
        return roleLabel(catalog, slugs[0]);
    if (slugs.length === 2)
        return slugs.map((s) => roleLabel(catalog, s)).join(", ");
    return `${roleLabel(catalog, slugs[0])} +${slugs.length - 1}`;
}
export default function RoleMultiSelect({ value, roles, onChange, className }) {
    const readOnly = useReadOnly();
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState([]);
    const [query, setQuery] = useState("");
    const [menuPos, setMenuPos] = useState(null);
    const triggerRef = useRef(null);
    const menuRef = useRef(null);
    const searchRef = useRef(null);
    const normalizedValue = useMemo(() => value.map(normalizeRole).filter(Boolean), [value]);
    const sortedRoles = useMemo(() => [...roles].sort((a, b) => a.name.localeCompare(b.name)), [roles]);
    const filteredRoles = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return sortedRoles;
        return sortedRoles.filter((role) => role.name.toLowerCase().includes(q) ||
            role.description.toLowerCase().includes(q) ||
            role.category.toLowerCase().includes(q));
    }, [query, sortedRoles]);
    useEffect(() => {
        if (readOnly)
            setOpen(false);
    }, [readOnly]);
    useEffect(() => {
        if (open) {
            setDraft([...normalizedValue]);
            setQuery("");
        }
    }, [open, normalizedValue]);
    useEffect(() => {
        if (!open)
            return;
        const t = window.setTimeout(() => searchRef.current?.focus(), 0);
        return () => window.clearTimeout(t);
    }, [open]);
    function updatePosition() {
        const btn = triggerRef.current;
        if (!btn)
            return;
        const rect = btn.getBoundingClientRect();
        const menuWidth = Math.min(Math.max(MENU_MIN_WIDTH, rect.width), window.innerWidth - VIEWPORT_PAD * 2);
        let left = rect.left;
        left = Math.max(VIEWPORT_PAD, Math.min(left, window.innerWidth - menuWidth - VIEWPORT_PAD));
        const estimatedHeight = Math.min(MENU_MAX_HEIGHT, filteredRoles.length * 32 + 96);
        let top = rect.bottom + 6;
        if (top + estimatedHeight > window.innerHeight - VIEWPORT_PAD) {
            top = Math.max(VIEWPORT_PAD, rect.top - estimatedHeight - 6);
        }
        setMenuPos({ top, left, width: menuWidth });
    }
    useLayoutEffect(() => {
        if (!open) {
            setMenuPos(null);
            return;
        }
        updatePosition();
        window.addEventListener("resize", updatePosition);
        window.addEventListener("scroll", updatePosition, true);
        return () => {
            window.removeEventListener("resize", updatePosition);
            window.removeEventListener("scroll", updatePosition, true);
        };
    }, [open, filteredRoles.length]);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (e) => {
            const t = e.target;
            if (triggerRef.current?.contains(t) || menuRef.current?.contains(t))
                return;
            setOpen(false);
        };
        const onKey = (e) => {
            if (e.key === "Escape")
                setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("mousedown", onDoc);
            document.removeEventListener("keydown", onKey);
        };
    }, [open]);
    function toggleSlug(slug) {
        const s = normalizeRole(slug);
        setDraft((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
    }
    function apply() {
        const next = (draft.length ? draft : ["user"]).map(normalizeRole);
        setOpen(false);
        const prevKey = [...normalizedValue].sort().join("|");
        const nextKey = [...next].sort().join("|");
        if (prevKey !== nextKey)
            onChange(next);
    }
    const pos = menuPos;
    const title = normalizedValue.map((s) => roleLabel(roles, s)).join(", ");
    const menu = open && pos
        ? createPortal(_jsxs("div", { ref: menuRef, className: "role-multi-select__menu role-multi-select__menu--portal", role: "dialog", "aria-label": "Select roles", style: {
                position: "fixed",
                top: pos.top,
                left: pos.left,
                minWidth: MENU_MIN_WIDTH,
                width: pos.width,
                maxWidth: `min(20rem, calc(100vw - ${VIEWPORT_PAD * 2}px))`,
            }, children: [_jsx("div", { className: "role-multi-select__search-wrap", children: _jsx("input", { ref: searchRef, type: "search", className: "role-multi-select__search", placeholder: "Search roles\u2026", value: query, onChange: (e) => setQuery(e.target.value), onKeyDown: (e) => e.stopPropagation() }) }), _jsxs("div", { className: "role-multi-select__list", children: [filteredRoles.map((role) => {
                            const checked = draft.includes(normalizeRole(role.slug));
                            return (_jsxs("label", { className: "role-multi-select__option", children: [_jsx("input", { type: "checkbox", checked: checked, onChange: () => toggleSlug(role.slug) }), _jsx("span", { children: role.name })] }, role.slug));
                        }), filteredRoles.length === 0 && (_jsx("p", { className: "role-multi-select__empty muted-text", children: "No roles match your search." }))] }), _jsxs("div", { className: "role-multi-select__actions", children: [_jsx("button", { type: "button", className: "btn btn-sm", onClick: apply, children: "Apply" }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => setOpen(false), children: "Cancel" })] })] }), document.body)
        : null;
    return (_jsxs(_Fragment, { children: [_jsxs("button", { ref: triggerRef, type: "button", className: `role-multi-select__trigger${className ? ` ${className}` : ""}`, onClick: () => !readOnly && setOpen((v) => !v), disabled: readOnly, title: readOnly ? ADMIN_WRITE_LOCK_TITLE : title, "aria-haspopup": "dialog", "aria-expanded": open, children: [_jsx("span", { className: "role-multi-select__label", children: summaryText(normalizedValue, roles) }), _jsx("span", { className: "role-multi-select__caret", "aria-hidden": true, children: "\u25BE" })] }), menu] }));
}
