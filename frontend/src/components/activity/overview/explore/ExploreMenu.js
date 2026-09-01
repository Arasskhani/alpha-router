import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
function Chevron() {
    return (_jsxs("svg", { viewBox: "0 0 12 16", width: "10", height: "12", "aria-hidden": true, className: "explore-menu__chevron", children: [_jsx("path", { d: "M3 5.5 L6 2.5 L9 5.5", fill: "none", stroke: "currentColor", strokeWidth: "1.4", strokeLinecap: "round" }), _jsx("path", { d: "M3 10.5 L6 13.5 L9 10.5", fill: "none", stroke: "currentColor", strokeWidth: "1.4", strokeLinecap: "round" })] }));
}
export default function ExploreMenu({ value, options, onChange, triggerLabel, triggerPrefix, searchable = false, searchPlaceholder = "Search", className = "", ariaLabel, align = "left", }) {
    const [open, setOpen] = useState(false);
    const [q, setQ] = useState("");
    const ref = useRef(null);
    const selected = options.find((o) => o.value === value);
    const label = triggerLabel ?? selected?.label ?? value;
    const filtered = useMemo(() => {
        const needle = q.trim().toLowerCase();
        if (!needle)
            return options;
        return options.filter((o) => o.label.toLowerCase().includes(needle) || o.value.toLowerCase().includes(needle));
    }, [options, q]);
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
    useEffect(() => {
        if (!open)
            setQ("");
    }, [open]);
    return (_jsxs("div", { className: `explore-menu ${className}`.trim(), ref: ref, children: [_jsxs("button", { type: "button", className: `explore-menu__trigger${open ? " is-open" : ""}`, onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "listbox", "aria-label": ariaLabel, children: [_jsxs("span", { children: [triggerPrefix ? _jsx("span", { className: "explore-menu__prefix", children: triggerPrefix }) : null, label] }), _jsx(Chevron, {})] }), open ? (_jsxs("div", { className: `explore-menu__panel card${align === "right" ? " explore-menu__panel--right" : ""}`, role: "listbox", children: [searchable ? (_jsxs("div", { className: "explore-menu__search", children: [_jsx("input", { type: "text", value: q, onChange: (e) => setQ(e.target.value), placeholder: searchPlaceholder, autoFocus: true }), _jsxs("svg", { viewBox: "0 0 24 24", width: "14", height: "14", "aria-hidden": true, children: [_jsx("circle", { cx: "11", cy: "11", r: "7", fill: "none", stroke: "currentColor", strokeWidth: "2" }), _jsx("path", { d: "M20 20l-3.5-3.5", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round" })] })] })) : null, _jsxs("div", { className: "explore-menu__list", children: [filtered.map((opt) => {
                                const active = opt.value === value;
                                return (_jsxs("button", { type: "button", role: "option", "aria-selected": active, className: `explore-menu__item${active ? " is-active" : ""}`, onClick: () => {
                                        onChange(opt.value);
                                        setOpen(false);
                                    }, children: [_jsx("span", { children: opt.label }), active ? _jsx("span", { className: "explore-menu__dot", "aria-hidden": true }) : null] }, opt.value));
                            }), filtered.length === 0 ? _jsx("p", { className: "explore-menu__empty muted-text", children: "No matches" }) : null] })] })) : null] }));
}
