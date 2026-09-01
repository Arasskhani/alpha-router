import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { formatLocalDateTime } from "../../lib/dateTime";
function formatWhen(iso) {
    return formatLocalDateTime(iso);
}
function actorLabel(actor) {
    if (!actor)
        return "System";
    return actor.display_name || actor.username || actor.email || `User #${actor.id}`;
}
function actionLabel(action) {
    const map = {
        created: "Created",
        updated: "Updated",
        enabled: "Enabled",
        disabled: "Disabled",
    };
    return map[action] || action;
}
function formatValue(v) {
    if (v === null || v === undefined)
        return "—";
    if (typeof v === "boolean")
        return v ? "Yes" : "No";
    const s = String(v);
    if (/^\d{4}-\d{2}-\d{2}T/.test(s)) {
        return formatLocalDateTime(s);
    }
    return s;
}
export default function ConnectionChangelog({ connectionId }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [dateFrom, setDateFrom] = useState("");
    const [dateTo, setDateTo] = useState("");
    useEffect(() => {
        if (!Number.isFinite(connectionId))
            return;
        setLoading(true);
        const qs = new URLSearchParams();
        if (dateFrom)
            qs.set("from", dateFrom);
        if (dateTo)
            qs.set("to", dateTo);
        const suffix = qs.toString() ? `?${qs}` : "";
        api(`/api/admin/connections/${connectionId}/changelog${suffix}`)
            .then((d) => setItems(d.items || []))
            .catch(() => setItems([]))
            .finally(() => setLoading(false));
    }, [connectionId, dateFrom, dateTo]);
    return (_jsxs("section", { className: "card api-key-changelog", children: [_jsx("h2", { className: "api-key-changelog__title", children: "Change log" }), _jsx("p", { className: "muted-text api-key-changelog__lead", children: "Creation and edits to this provider connection (who changed what)." }), _jsxs("div", { className: "api-key-changelog__filters", children: [_jsxs("label", { className: "api-key-changelog__filter", children: [_jsx("span", { className: "api-key-changelog__filter-label", children: "From date" }), _jsx("input", { type: "date", className: "input-block", value: dateFrom, onChange: (e) => setDateFrom(e.target.value) })] }), _jsxs("label", { className: "api-key-changelog__filter", children: [_jsx("span", { className: "api-key-changelog__filter-label", children: "To date" }), _jsx("input", { type: "date", className: "input-block", value: dateTo, min: dateFrom || undefined, onChange: (e) => setDateTo(e.target.value) })] }), _jsxs("div", { className: "api-key-changelog__filter api-key-changelog__filter--action", children: [_jsx("span", { className: "api-key-changelog__filter-label api-key-changelog__filter-label--spacer", "aria-hidden": "true", children: "\u00A0" }), _jsx("button", { type: "button", className: "btn btn-ghost api-key-changelog__clear", disabled: !dateFrom && !dateTo, onClick: () => {
                                    setDateFrom("");
                                    setDateTo("");
                                }, children: "Clear dates" })] })] }), loading && _jsx("p", { className: "muted-text", children: "Loading change log\u2026" }), !loading && items.length === 0 && (_jsx("p", { className: "muted-text", children: dateFrom || dateTo ? "No changes in this date range." : "No changes recorded yet." })), !loading && items.length > 0 && (_jsxs("p", { className: "muted-text api-key-changelog__count", children: [items.length, " entr", items.length === 1 ? "y" : "ies"] })), _jsx("ul", { className: "api-key-changelog__list", children: items.map((entry) => (_jsxs("li", { className: "api-key-changelog__entry", children: [_jsxs("div", { className: "api-key-changelog__head", children: [_jsx("strong", { children: actionLabel(entry.action) }), _jsx("span", { className: "muted-text", children: formatWhen(entry.created_at) })] }), _jsxs("p", { className: "api-key-changelog__actor muted-text", children: ["By ", actorLabel(entry.actor)] }), entry.changes.length > 0 ? (_jsx("ul", { className: "api-key-changelog__changes", children: entry.changes.map((c) => (_jsxs("li", { children: [_jsx("span", { className: "api-key-changelog__field", children: c.label || c.field }), entry.action === "created" ? (_jsxs("span", { children: [" \u2192 ", formatValue(c.new)] })) : (_jsxs("span", { children: [": ", formatValue(c.old), " \u2192 ", formatValue(c.new)] }))] }, `${entry.id}-${c.field}`))) })) : null] }, entry.id))) })] }));
}
