import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
export default function LogFilterCombobox({ value, onChange, options, placeholder, loading = false, disabled, id, onOpen, }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState(value);
    const ref = useRef(null);
    useEffect(() => {
        if (!open)
            setQuery(value);
    }, [value, open]);
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
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return options.slice(0, 80);
        return options.filter((o) => o.toLowerCase().includes(q)).slice(0, 80);
    }, [options, query]);
    function pick(option) {
        onChange(option);
        setQuery(option);
        setOpen(false);
    }
    return (_jsxs("div", { className: "log-filter-combobox", ref: ref, children: [_jsx("input", { id: id, type: "search", placeholder: placeholder, value: open ? query : value, disabled: disabled, autoComplete: "off", "aria-expanded": open, "aria-autocomplete": "list", onFocus: () => {
                    onOpen?.();
                    setOpen(true);
                }, onChange: (e) => {
                    setQuery(e.target.value);
                    onChange(e.target.value);
                    setOpen(true);
                } }), open ? (_jsxs("div", { className: "log-filter-combobox__panel card", role: "listbox", children: [loading ? _jsx("p", { className: "muted-text log-filter-combobox__hint", children: "Loading\u2026" }) : null, !loading && options.length === 0 ? (_jsx("p", { className: "muted-text log-filter-combobox__hint", children: "No values in current logs" })) : null, !loading && options.length > 0 && filtered.length === 0 ? (_jsx("p", { className: "muted-text log-filter-combobox__hint", children: "No matches" })) : null, _jsx("ul", { className: "log-filter-combobox__list", children: filtered.map((option) => (_jsx("li", { children: _jsx("button", { type: "button", className: `log-filter-combobox__item${option === value ? " log-filter-combobox__item--active" : ""}`, onClick: () => pick(option), children: option }) }, option))) })] })) : null] }));
}
