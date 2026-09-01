import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import Modal from "./Modal";
export const FOLDER_COLOR_PRESETS = [
    { id: "default", value: null, label: "Default" },
    { id: "indigo", value: "#6366f1", label: "Indigo" },
    { id: "violet", value: "#8b5cf6", label: "Violet" },
    { id: "blue", value: "#3b82f6", label: "Blue" },
    { id: "cyan", value: "#06b6d4", label: "Cyan" },
    { id: "teal", value: "#14b8a6", label: "Teal" },
    { id: "green", value: "#22c55e", label: "Green" },
    { id: "amber", value: "#f59e0b", label: "Amber" },
    { id: "orange", value: "#f97316", label: "Orange" },
    { id: "red", value: "#ef4444", label: "Red" },
    { id: "pink", value: "#ec4899", label: "Pink" },
    { id: "slate", value: "#64748b", label: "Slate" },
];
export default function ColorPickerModal({ open, title = "Choose color", value, onClose, onChange, }) {
    const custom = value && !FOLDER_COLOR_PRESETS.some((p) => p.value === value) ? value : "#6366f1";
    return (_jsx(Modal, { open: open, title: title, onClose: onClose, children: _jsxs("div", { className: "color-picker", children: [_jsx("p", { className: "color-picker-hint muted-text", children: "Pick a color for this folder." }), _jsx("div", { className: "color-picker-grid", role: "listbox", "aria-label": "Preset colors", children: FOLDER_COLOR_PRESETS.map((preset) => {
                        const selected = (preset.value === null && !value) || (preset.value !== null && preset.value === value);
                        return (_jsx("button", { type: "button", role: "option", "aria-selected": selected, className: `color-picker-swatch${selected ? " is-selected" : ""}${preset.value === null ? " is-default" : ""}`, style: preset.value ? { background: preset.value } : undefined, title: preset.label, onClick: () => {
                                onChange(preset.value);
                                onClose();
                            }, children: preset.value === null ? _jsx("span", { className: "color-picker-swatch-label", children: "Aa" }) : null }, preset.id));
                    }) }), _jsxs("label", { className: "color-picker-custom", children: [_jsx("span", { children: "Custom" }), _jsx("input", { type: "color", value: custom, onChange: (e) => onChange(e.target.value), "aria-label": "Custom color" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => {
                                onChange(custom);
                                onClose();
                            }, children: "Apply custom" })] })] }) }));
}
