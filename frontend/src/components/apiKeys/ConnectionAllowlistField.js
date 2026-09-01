import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
export default function ConnectionAllowlistField({ selectedIds, onChange, disabled }) {
    const [items, setItems] = useState([]);
    const [err, setErr] = useState("");
    const [query, setQuery] = useState("");
    useEffect(() => {
        let cancelled = false;
        api("/api/admin/api-keys/connection-options")
            .then((res) => {
            if (!cancelled)
                setItems(res.items || []);
        })
            .catch((e) => {
            if (!cancelled)
                setErr(String(e));
        });
        return () => {
            cancelled = true;
        };
    }, []);
    const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return items;
        return items.filter((c) => c.name.toLowerCase().includes(q) ||
            (c.provider_type || "").toLowerCase().includes(q));
    }, [items, query]);
    function toggle(id) {
        if (selected.has(id))
            onChange(selectedIds.filter((x) => x !== id));
        else
            onChange([...selectedIds, id]);
    }
    if (err) {
        return _jsx("p", { className: "alert alert-error", children: err });
    }
    return (_jsxs("div", { className: "api-key-conn-picker", children: [items.length > 6 ? (_jsx("input", { type: "search", className: "input-block", placeholder: "Search connections\u2026", value: query, onChange: (e) => setQuery(e.target.value), disabled: disabled })) : null, _jsx("div", { className: "api-key-conn-picker__list", role: "group", "aria-label": "Allowed connections", children: filtered.length === 0 ? (_jsx("p", { className: "muted-text api-key-form__hint", children: items.length === 0 ? "No connections configured yet." : "No connections match this search." })) : (filtered.map((c) => (_jsxs("label", { className: `api-key-conn-picker__option${c.is_active ? "" : " is-inactive"}`, children: [_jsx("input", { type: "checkbox", checked: selected.has(c.id), onChange: () => toggle(c.id), disabled: disabled }), _jsxs("span", { children: [c.name, _jsxs("span", { className: "muted-text", children: [" \u00B7 ", c.provider_type] }), !c.is_active ? _jsx("span", { className: "muted-text", children: " \u00B7 inactive" }) : null] })] }, c.id)))) }), selectedIds.length === 0 ? (_jsx("span", { className: "muted-text api-key-form__hint", children: "No connections selected \u2014 this key cannot call any model until you add at least one." })) : null] }));
}
