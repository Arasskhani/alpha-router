import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { groupByLabel } from "./formatters";
const OPTIONS = [
    { value: "model", label: "By Model" },
    { value: "user", label: "By Creator" },
    { value: "app", label: "By API Key" },
];
export default function ActivityGroupByMenu({ value, onChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (e) => {
            if (ref.current && !ref.current.contains(e.target))
                setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [open]);
    return (_jsxs("div", { className: "activity-period-menu", ref: ref, children: [_jsx("button", { type: "button", className: `activity-period-trigger${open ? " activity-period-trigger--open" : ""}`, onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "listbox", children: _jsx("span", { children: groupByLabel(value) }) }), open ? (_jsx("div", { className: "activity-period-panel activity-period-panel--narrow card", role: "listbox", children: OPTIONS.map((item) => (_jsxs("button", { type: "button", role: "option", "aria-selected": value === item.value, className: `activity-menu-item${value === item.value ? " activity-menu-item--active" : ""}`, onClick: () => {
                        onChange(item.value);
                        setOpen(false);
                    }, children: [item.label, value === item.value ? " ✓" : ""] }, item.value))) })) : null] }));
}
