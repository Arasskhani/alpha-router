import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useReadOnly } from "../context/ReadOnlyContext";
import { ADMIN_WRITE_LOCK_TITLE } from "../lib/adminWriteLock";
const MENU_MIN_WIDTH = 168;
const MENU_MAX_HEIGHT = 260;
const VIEWPORT_PAD = 8;
export default function RowActionsMenu({ actions, label = "Actions", menuClassName = "" }) {
    const readOnly = useReadOnly();
    const [open, setOpen] = useState(false);
    const [menuPos, setMenuPos] = useState(null);
    const triggerRef = useRef(null);
    const rootRef = useRef(null);
    const menuRef = useRef(null);
    const visible = actions.filter((a) => !a.disabled);
    useEffect(() => {
        if (readOnly)
            setOpen(false);
    }, [readOnly]);
    function updatePosition() {
        const btn = triggerRef.current;
        if (!btn)
            return;
        const rect = btn.getBoundingClientRect();
        const menuWidth = Math.min(Math.max(MENU_MIN_WIDTH, 184), window.innerWidth - VIEWPORT_PAD * 2);
        let left = rect.right - menuWidth;
        left = Math.max(VIEWPORT_PAD, Math.min(left, window.innerWidth - menuWidth - VIEWPORT_PAD));
        const estimatedHeight = Math.min(MENU_MAX_HEIGHT, visible.length * 36 + 14);
        let top = rect.bottom + 6;
        if (top + estimatedHeight > window.innerHeight - VIEWPORT_PAD) {
            top = Math.max(VIEWPORT_PAD, rect.top - estimatedHeight - 6);
        }
        setMenuPos({ top, left });
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
    }, [open]);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (e) => {
            const t = e.target;
            if (rootRef.current?.contains(t) || menuRef.current?.contains(t))
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
    const menu = open && menuPos
        ? createPortal(_jsx("div", { ref: menuRef, className: `row-actions-menu row-actions-menu--portal${menuClassName ? ` ${menuClassName}` : ""}`, role: "menu", style: {
                position: "fixed",
                top: menuPos.top,
                left: menuPos.left,
                minWidth: MENU_MIN_WIDTH,
                maxWidth: `min(16rem, calc(100vw - ${VIEWPORT_PAD * 2}px))`,
            }, children: visible.map((a) => (_jsx("button", { type: "button", role: "menuitem", className: `row-actions-item${a.danger ? " row-actions-item-danger" : ""}${a.menuWrap ? " row-actions-item--wrap" : ""}`, onClick: () => {
                    a.onClick();
                    setOpen(false);
                }, children: a.label }, a.label))) }), document.body)
        : null;
    return (_jsxs("div", { className: "row-actions", ref: rootRef, children: [_jsxs("button", { ref: triggerRef, type: "button", className: "btn-sm btn-ghost row-actions-trigger", onClick: () => setOpen((o) => !o), "aria-expanded": open, "aria-haspopup": "menu", disabled: readOnly || visible.length === 0, title: readOnly ? ADMIN_WRITE_LOCK_TITLE : undefined, children: [label, label !== "⋯" && label !== "⋮" ? _jsx("span", { "aria-hidden": true, children: "\u25BE" }) : null] }), menu] }));
}
