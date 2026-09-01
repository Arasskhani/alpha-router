import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
const MENU_WIDTH = 220;
export default function ComposerAttachMenu({ open, anchorRef, onClose, onUpload, onScreenshot, onFromMedia, }) {
    const [pos, setPos] = useState(null);
    useEffect(() => {
        if (!open)
            return;
        const onKey = (e) => {
            if (e.key === "Escape")
                onClose();
        };
        const onDoc = (e) => {
            const target = e.target;
            if (anchorRef.current?.contains(target))
                return;
            if (target instanceof Element && target.closest(".alpha-router-attach-menu"))
                return;
            onClose();
        };
        window.addEventListener("keydown", onKey);
        document.addEventListener("mousedown", onDoc);
        return () => {
            window.removeEventListener("keydown", onKey);
            document.removeEventListener("mousedown", onDoc);
        };
    }, [open, onClose, anchorRef]);
    useLayoutEffect(() => {
        if (!open) {
            setPos(null);
            return;
        }
        const place = () => {
            const el = anchorRef.current;
            if (!el)
                return;
            const rect = el.getBoundingClientRect();
            const width = Math.min(MENU_WIDTH, window.innerWidth - 16);
            const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
            const bottom = window.innerHeight - rect.top + 8;
            setPos({ left, bottom });
        };
        place();
        window.addEventListener("resize", place);
        window.addEventListener("scroll", place, true);
        return () => {
            window.removeEventListener("resize", place);
            window.removeEventListener("scroll", place, true);
        };
    }, [open, anchorRef]);
    if (!open || !pos)
        return null;
    return createPortal(_jsxs("div", { className: "alpha-router-attach-menu", role: "menu", "aria-label": "Attach", style: { left: pos.left, bottom: pos.bottom, width: Math.min(MENU_WIDTH, window.innerWidth - 16) }, onMouseDown: (e) => e.stopPropagation(), children: [_jsxs("button", { type: "button", role: "menuitem", className: "alpha-router-attach-menu__item", onClick: onUpload, children: [_jsx("span", { className: "alpha-router-attach-menu__icon", "aria-hidden": true, children: _jsx("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "2", children: _jsx("path", { d: "m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.64 16.2a2 2 0 0 1-2.83-2.83l8.49-8.49" }) }) }), "Upload file"] }), _jsxs("button", { type: "button", role: "menuitem", className: "alpha-router-attach-menu__item", onClick: onScreenshot, children: [_jsx("span", { className: "alpha-router-attach-menu__icon", "aria-hidden": true, children: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "2", children: [_jsx("rect", { x: "3", y: "6", width: "18", height: "14", rx: "2" }), _jsx("circle", { cx: "12", cy: "13", r: "3.2" }), _jsx("path", { d: "M8 6 9.2 3.8h5.6L16 6" })] }) }), "Screenshot"] }), _jsxs("button", { type: "button", role: "menuitem", className: "alpha-router-attach-menu__item", onClick: onFromMedia, children: [_jsx("span", { className: "alpha-router-attach-menu__icon", "aria-hidden": true, children: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "2", children: [_jsx("rect", { x: "3", y: "4", width: "18", height: "16", rx: "2" }), _jsx("path", { d: "m3 15 5-4 4 3 3-2 6 5" })] }) }), "From Media"] })] }), document.body);
}
