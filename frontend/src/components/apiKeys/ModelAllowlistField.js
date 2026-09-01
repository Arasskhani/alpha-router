import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
function modelLabel(m) {
    const base = m.display_name || m.external_id;
    return m.connection_name ? `${base} · ${m.connection_name}` : base;
}
export default function ModelAllowlistField({ ownerUserId, connectionIds, restrictConnections, selectedIds, onChange, disabled, }) {
    const [items, setItems] = useState([]);
    const [err, setErr] = useState("");
    const [query, setQuery] = useState("");
    useEffect(() => {
        if (!ownerUserId) {
            setItems([]);
            return;
        }
        let cancelled = false;
        const qs = new URLSearchParams();
        qs.set("owner_user_id", String(ownerUserId));
        if (restrictConnections) {
            for (const id of connectionIds)
                qs.append("connection_id", String(id));
        }
        api(`/api/admin/api-keys/model-options?${qs}`)
            .then((res) => {
            if (cancelled)
                return;
            const next = res.items || [];
            setItems(next);
            const allowed = new Set(next.map((m) => m.id));
            const pruned = selectedIds.filter((id) => allowed.has(id));
            if (pruned.length !== selectedIds.length)
                onChange(pruned);
        })
            .catch((e) => {
            if (!cancelled)
                setErr(String(e));
        });
        return () => {
            cancelled = true;
        };
    }, [ownerUserId, restrictConnections, connectionIds.join(",")]);
    const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q)
            return items;
        return items.filter((m) => {
            const hay = `${m.display_name} ${m.external_id} ${m.connection_name || ""} ${m.provider_type}`.toLowerCase();
            return hay.includes(q);
        });
    }, [items, query]);
    function toggle(id) {
        if (selected.has(id))
            onChange(selectedIds.filter((x) => x !== id));
        else
            onChange([...selectedIds, id]);
    }
    if (!ownerUserId) {
        return (_jsx("span", { className: "muted-text api-key-form__hint", children: "Select an owner first to pick allowed models." }));
    }
    if (err) {
        return _jsx("p", { className: "alert alert-error", children: err });
    }
    return (_jsxs("div", { className: "api-key-conn-picker", children: [items.length > 8 ? (_jsx("input", { type: "search", className: "input-block", placeholder: "Search models\u2026", value: query, onChange: (e) => setQuery(e.target.value), disabled: disabled })) : null, _jsx("div", { className: "api-key-conn-picker__list", role: "group", "aria-label": "Allowed models", children: filtered.length === 0 ? (_jsx("p", { className: "muted-text api-key-form__hint", children: items.length === 0
                        ? restrictConnections && connectionIds.length === 0
                            ? "Select at least one connection or disable connection restriction."
                            : "No enabled models available for this owner."
                        : "No models match this search." })) : (filtered.map((m) => (_jsxs("label", { className: "api-key-conn-picker__option", children: [_jsx("input", { type: "checkbox", checked: selected.has(m.id), onChange: () => toggle(m.id), disabled: disabled }), _jsxs("span", { children: [modelLabel(m), _jsxs("span", { className: "muted-text", children: [" \u00B7 ", m.provider_type] })] })] }, m.id)))) }), selectedIds.length === 0 ? (_jsx("span", { className: "muted-text api-key-form__hint", children: "No models selected \u2014 this key cannot call any model until you add at least one." })) : null] }));
}
