import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { MODEL_NEW_WINDOWS } from "../../lib/modelCatalog";
function windowLabel(days) {
    return days === 1 ? "Last 1 day" : `Last ${days} days`;
}
export default function ModelsNewFilterMenu({ value, counts, onChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (e) => {
            if (ref.current && !ref.current.contains(e.target))
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
    function pick(days) {
        onChange(value === days ? null : days);
        setOpen(false);
    }
    return (_jsxs("div", { className: "models-new-filter", ref: ref, children: [_jsxs("button", { type: "button", className: `models-filter-chip${value || open ? " models-filter-chip--active" : ""}`, onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "listbox", "aria-label": "Filter by newly listed", title: value ? windowLabel(value) : "Filter models first listed in Alpha Router", children: [_jsx("span", { children: value ? `New ${value}d` : "New" }), value ? _jsx("span", { className: "models-filter-chip__count", children: counts[value] }) : null, _jsx("svg", { className: "models-new-filter__chevron", viewBox: "0 0 24 24", width: 14, height: 14, fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("path", { d: "m6 9 6 6 6-6" }) })] }), open ? (_jsx("div", { className: "models-new-filter__menu card", role: "listbox", "aria-label": "New model windows", children: MODEL_NEW_WINDOWS.map((days) => {
                    const selected = value === days;
                    return (_jsxs("button", { type: "button", role: "option", "aria-selected": selected, className: `models-new-filter__item${selected ? " models-new-filter__item--active" : ""}`, onClick: () => pick(days), children: [_jsx("span", { children: windowLabel(days) }), _jsx("span", { className: "models-filter-chip__count", children: counts[days] })] }, days));
                }) })) : null] }));
}
