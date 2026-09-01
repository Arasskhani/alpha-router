import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { browserTimezoneName, formatTimezoneOffsetLabel } from "../../lib/activityTimezone";
/** Toolbar chip: browser offset by default; opens Local / UTC picker. */
export default function ActivityTimezoneChip({ value, onChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const localLabel = formatTimezoneOffsetLabel();
    const tzName = browserTimezoneName();
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
    const chipLabel = value === "utc" ? "UTC" : localLabel;
    return (_jsxs("div", { className: "activity-timezone-chip", ref: ref, children: [_jsx("button", { type: "button", className: `activity-timezone-chip__trigger${open ? " activity-timezone-chip__trigger--open" : ""}`, onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "listbox", "aria-label": `Timezone: ${chipLabel}`, title: value === "local" ? tzName : "Coordinated Universal Time", children: _jsx("span", { children: chipLabel }) }), open ? (_jsxs("div", { className: "activity-timezone-chip__panel card", role: "listbox", children: [_jsxs("button", { type: "button", role: "option", "aria-selected": value === "local", className: `activity-menu-item${value === "local" ? " activity-menu-item--active" : ""}`, onClick: () => {
                            onChange("local");
                            setOpen(false);
                        }, children: ["Browser local (", localLabel, ")", value === "local" ? " ✓" : ""] }), _jsxs("button", { type: "button", role: "option", "aria-selected": value === "utc", className: `activity-menu-item${value === "utc" ? " activity-menu-item--active" : ""}`, onClick: () => {
                            onChange("utc");
                            setOpen(false);
                        }, children: ["UTC", value === "utc" ? " ✓" : ""] })] })) : null] }));
}
