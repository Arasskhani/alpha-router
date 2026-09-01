import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
export function filterModelOptions(options, query, limit = 80) {
    const q = query.trim().toLowerCase();
    const matched = q
        ? options.filter((option) => {
            const hay = `${option.label} ${option.value}`.toLowerCase();
            return hay.includes(q);
        })
        : options;
    return matched.slice(0, limit);
}
export default function SearchableModelSelect({ value, options, onChange, disabled, placeholder = "Search models…", emptyLabel = "Not configured", allowEmpty = true, ariaLabel, id, }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const [active, setActive] = useState(0);
    const rootRef = useRef(null);
    const inputRef = useRef(null);
    const selected = options.find((option) => option.value === value);
    const closedLabel = selected?.label || (value ? value : emptyLabel);
    const filtered = useMemo(() => {
        const rows = filterModelOptions(options, query);
        if (allowEmpty && !query.trim()) {
            return [{ value: "", label: emptyLabel }, ...rows];
        }
        if (allowEmpty && emptyLabel.toLowerCase().includes(query.trim().toLowerCase())) {
            return [{ value: "", label: emptyLabel }, ...rows];
        }
        return rows;
    }, [allowEmpty, emptyLabel, options, query]);
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (event) => {
            if (rootRef.current && !rootRef.current.contains(event.target)) {
                setOpen(false);
                setQuery("");
            }
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [open]);
    useEffect(() => {
        setActive(0);
    }, [query, open]);
    function pick(next) {
        onChange(next);
        setOpen(false);
        setQuery("");
    }
    function onKeyDown(event) {
        if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
            setQuery("");
            inputRef.current?.blur();
            return;
        }
        if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActive((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
            return;
        }
        if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
            return;
        }
        if (event.key === "Enter") {
            event.preventDefault();
            const row = filtered[active] || filtered[0];
            if (row)
                pick(row.value);
        }
    }
    return (_jsxs("div", { className: "admin-model-combobox", ref: rootRef, children: [_jsx("input", { ref: inputRef, id: id, type: "search", className: "admin-model-combobox__input", value: open ? query : closedLabel, placeholder: placeholder, disabled: disabled, autoComplete: "off", role: "combobox", "aria-label": ariaLabel, "aria-expanded": open, "aria-autocomplete": "list", onFocus: () => {
                    if (disabled)
                        return;
                    setOpen(true);
                    setQuery("");
                }, onChange: (event) => {
                    setQuery(event.target.value);
                    setOpen(true);
                }, onKeyDown: onKeyDown }), open && !disabled ? (_jsx("div", { className: "admin-model-combobox__panel card", role: "listbox", children: filtered.length === 0 ? (_jsx("p", { className: "muted-text admin-model-combobox__hint", children: "No matches" })) : (_jsx("ul", { className: "admin-model-combobox__list", children: filtered.map((option, index) => (_jsx("li", { children: _jsx("button", { type: "button", role: "option", "aria-selected": option.value === value, className: `admin-model-combobox__item${index === active ? " admin-model-combobox__item--active" : ""}${option.value === value ? " admin-model-combobox__item--selected" : ""}`, onMouseDown: (event) => event.preventDefault(), onMouseEnter: () => setActive(index), onClick: () => pick(option.value), children: option.label }) }, `${option.value || "empty"}:${option.label}`))) })) })) : null] }));
}
