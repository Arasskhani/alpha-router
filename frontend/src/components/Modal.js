import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect } from "react";
export default function Modal({ open, title, onClose, children, compactHeader, closeOnBackdrop = true, closeOnEscape = true, panelClassName = "", bodyClassName = "", headerActions, }) {
    useEffect(() => {
        if (!open || !closeOnEscape)
            return;
        const onKey = (e) => e.key === "Escape" && onClose();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, onClose, closeOnEscape]);
    if (!open)
        return null;
    return (_jsx("div", { className: "modal-overlay", onClick: closeOnBackdrop ? onClose : undefined, role: "presentation", children: _jsxs("div", { className: `modal-panel${panelClassName ? ` ${panelClassName}` : ""}`, onClick: (e) => e.stopPropagation(), role: "dialog", "aria-modal": "true", "aria-label": title || undefined, children: [_jsxs("div", { className: `modal-header${compactHeader ? " modal-header--compact" : ""}`, children: [compactHeader || !title ? _jsx("span", { "aria-hidden": "true" }) : _jsx("h3", { children: title }), _jsxs("div", { className: "modal-header-end", children: [headerActions, _jsx("button", { type: "button", className: "modal-close", onClick: onClose, "aria-label": "Close", children: "\u00D7" })] })] }), _jsx("div", { className: `modal-body${bodyClassName ? ` ${bodyClassName}` : ""}`, children: children })] }) }));
}
