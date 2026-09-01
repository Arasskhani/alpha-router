import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
export default function ConfirmModal({ open, title, message, emphasize, emphasizeDanger = false, confirmLabel = "Yes", cancelLabel = "No", secondaryLabel, danger = false, promptLabel, promptDefault = "", promptRequired = false, promptExactMatch, onConfirm, onCancel, onSecondary, }) {
    const [promptValue, setPromptValue] = useState(promptDefault);
    useEffect(() => {
        if (open)
            setPromptValue(promptDefault);
    }, [open, promptDefault]);
    useEffect(() => {
        if (!open)
            return;
        const onKey = (e) => {
            if (e.key === "Escape")
                onCancel();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, onCancel]);
    if (!open)
        return null;
    const emphasisIndex = emphasize ? message.indexOf(emphasize) : -1;
    const renderedMessage = emphasize && emphasisIndex >= 0 ? (_jsxs(_Fragment, { children: [message.slice(0, emphasisIndex), _jsx("strong", { className: emphasizeDanger ? "confirm-message__emphasis--danger" : undefined, children: emphasize }), message.slice(emphasisIndex + emphasize.length)] })) : (message);
    const trimmed = promptValue.trim();
    const confirmDisabled = promptExactMatch
        ? trimmed !== promptExactMatch
        : Boolean(promptLabel && promptRequired && !trimmed);
    return createPortal(_jsx("div", { className: "modal-overlay modal-overlay-confirm", onClick: onCancel, role: "presentation", children: _jsxs("div", { className: "modal-panel modal-panel-confirm", onClick: (e) => e.stopPropagation(), role: "alertdialog", "aria-modal": "true", children: [_jsx("div", { className: "modal-header", children: _jsx("h3", { children: title }) }), _jsxs("div", { className: "modal-body", children: [_jsx("p", { className: "confirm-message", children: renderedMessage }), promptLabel ? (_jsxs("label", { className: "confirm-prompt", children: [_jsx("span", { children: promptLabel }), _jsx("input", { type: "text", value: promptValue, onChange: (e) => setPromptValue(e.target.value), autoFocus: true, onKeyDown: (e) => {
                                        if (e.key === "Enter" && !confirmDisabled) {
                                            e.preventDefault();
                                            onConfirm(trimmed);
                                        }
                                    } })] })) : null, _jsxs("div", { className: `dialog-actions${secondaryLabel ? " dialog-actions-three" : ""}`, children: [_jsx("button", { type: "button", className: danger ? "btn btn-danger" : "btn", onClick: () => onConfirm(promptLabel ? trimmed : undefined), disabled: confirmDisabled, autoFocus: !promptLabel, children: confirmLabel }), secondaryLabel && onSecondary ? (_jsx("button", { type: "button", className: "btn btn-ghost", onClick: onSecondary, children: secondaryLabel })) : null, _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: onCancel, children: cancelLabel })] })] })] }) }), document.body);
}
