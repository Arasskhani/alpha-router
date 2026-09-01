import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
export const DEFAULT_OPS_RANGE = "past_1d";
const RELATIVE = [
    { value: "past_15m", label: "Past 15 Minutes" },
    { value: "past_30m", label: "Past 30 Minutes" },
    { value: "past_1h", label: "Past 1 Hour" },
    { value: "past_3h", label: "Past 3 Hours" },
    { value: "past_1d", label: "Past 1 Day" },
    { value: "past_2d", label: "Past 2 Days" },
    { value: "past_1w", label: "Past 1 Week" },
    { value: "past_1mo", label: "Past 1 Month" },
    { value: "past_1y", label: "Past 1 Year" },
];
const PERIODS = [
    { value: "today", label: "Today" },
    { value: "yesterday", label: "Yesterday" },
    { value: "this_week", label: "This Week" },
    { value: "prev_week", label: "Prev Week" },
];
const META = {
    past_15m: { label: "Past 15 Minutes", badge: "15m" },
    past_30m: { label: "Past 30 Minutes", badge: "30m" },
    past_1h: { label: "Past 1 Hour", badge: "1h" },
    past_3h: { label: "Past 3 Hours", badge: "3h" },
    past_1d: { label: "Past 1 Day", badge: "1d" },
    past_2d: { label: "Past 2 Days", badge: "2d" },
    past_1w: { label: "Past 1 Week", badge: "1w" },
    past_1mo: { label: "Past 1 Month", badge: "1mo" },
    past_1y: { label: "Past 1 Year", badge: "1y" },
    today: { label: "Today", badge: "TD" },
    yesterday: { label: "Yesterday", badge: "YD" },
    this_week: { label: "This Week", badge: "TW" },
    prev_week: { label: "Prev Week", badge: "PW" },
};
export function parseOpsRangeKey(raw) {
    if (raw && raw in META)
        return raw;
    return DEFAULT_OPS_RANGE;
}
export default function OperationsTimeRangeMenu({ value, onChange, disabled }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const meta = META[value];
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
    function pick(key) {
        onChange(key);
        setOpen(false);
    }
    return (_jsxs("div", { className: "activity-period-menu operations-time-range-menu", ref: ref, children: [_jsxs("button", { type: "button", className: `activity-period-trigger${open ? " activity-period-trigger--open" : ""}`, onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "listbox", disabled: disabled, "aria-label": "Time range", children: [_jsx("span", { className: "activity-period-trigger__badge", children: meta.badge }), _jsx("span", { children: meta.label }), _jsx("svg", { viewBox: "0 0 24 24", width: "14", height: "14", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("path", { d: "m6 9 6 6 6-6" }) })] }), open ? (_jsxs("div", { className: "activity-period-panel card operations-time-range-panel", role: "listbox", children: [_jsx("p", { className: "activity-menu-heading", children: "Relative" }), RELATIVE.map((item) => (_jsxs("button", { type: "button", role: "option", "aria-selected": value === item.value, className: `activity-menu-item${value === item.value ? " activity-menu-item--active" : ""}`, onClick: () => pick(item.value), children: [item.label, value === item.value ? " ✓" : ""] }, item.value))), _jsx("p", { className: "activity-menu-heading", children: "Periods" }), _jsx("div", { className: "activity-period-grid", children: PERIODS.map((item) => (_jsx("button", { type: "button", role: "option", "aria-selected": value === item.value, className: `activity-period-grid__btn${value === item.value ? " activity-period-grid__btn--active" : ""}`, onClick: () => pick(item.value), children: item.label }, item.value))) })] })) : null] }));
}
