import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { periodLabel, periodShortBadge } from "./formatters";
const RELATIVE = [
    { value: "15m", label: "Past 15 Minutes" },
    { value: "30m", label: "Past 30 Minutes" },
    { value: "1h", label: "Past 1 Hour" },
    { value: "3h", label: "Past 3 Hours" },
    { value: "day", label: "Past 1 Day" },
    { value: "2d", label: "Past 2 Days" },
    { value: "week", label: "Past 1 Week" },
    { value: "month", label: "Past 1 Month" },
    { value: "year", label: "Past 1 Year" },
];
const CALENDAR = [
    { value: "day", label: "Today" },
    { value: "day", label: "Yesterday" },
    { value: "week", label: "This Week" },
    { value: "week", label: "Prev Week" },
    { value: "month", label: "This Month" },
    { value: "month", label: "Prev Month" },
    { value: "year", label: "This Year" },
    { value: "year", label: "Prev Year" },
];
export function parseActivityPeriod(raw) {
    const allowed = new Set(RELATIVE.map((r) => r.value));
    if (raw && allowed.has(raw))
        return raw;
    return "day";
}
export default function ActivityPeriodMenu({ value, onChange }) {
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
    function pick(p) {
        onChange(p);
        setOpen(false);
    }
    return (_jsxs("div", { className: "activity-period-menu", ref: ref, children: [_jsxs("button", { type: "button", className: `activity-period-trigger${open ? " activity-period-trigger--open" : ""}`, onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "listbox", children: [_jsx("span", { className: "activity-period-trigger__badge", children: periodShortBadge(value) }), _jsx("span", { children: periodLabel(value) })] }), open ? (_jsxs("div", { className: "activity-period-panel card", role: "listbox", children: [_jsx("p", { className: "activity-menu-heading", children: "Relative" }), RELATIVE.map((item) => (_jsxs("button", { type: "button", role: "option", "aria-selected": value === item.value, className: `activity-menu-item${value === item.value ? " activity-menu-item--active" : ""}`, onClick: () => pick(item.value), children: [item.label, value === item.value ? " ✓" : ""] }, item.label))), _jsx("p", { className: "activity-menu-heading", children: "Periods" }), _jsx("div", { className: "activity-period-grid", children: CALENDAR.map((item) => (_jsx("button", { type: "button", className: `activity-period-grid__btn${value === item.value ? " activity-period-grid__btn--active" : ""}`, onClick: () => pick(item.value), children: item.label }, item.label))) })] })) : null] }));
}
