import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import ModelName from "../../../ModelName";
import { formatRequests, formatSpend, formatTokens } from "../../formatters";
function formatCell(metric, v) {
    if (metric === "total_usage")
        return formatSpend(v);
    if (metric === "request_count")
        return formatRequests(v);
    if (metric === "avg_latency" || metric === "p50_latency") {
        if (v >= 1000)
            return `${(v / 1000).toFixed(2)}s`;
        return `${Math.round(v)}ms`;
    }
    return formatTokens(v);
}
export default function ExploreTable({ explore }) {
    const [sortKey, setSortKey] = useState("value");
    const [asc, setAsc] = useState(false);
    const rows = useMemo(() => {
        const copy = [...explore.table];
        copy.sort((a, b) => {
            const av = a[sortKey];
            const bv = b[sortKey];
            if (typeof av === "string" && typeof bv === "string") {
                return asc ? av.localeCompare(bv) : bv.localeCompare(av);
            }
            return asc ? Number(av) - Number(bv) : Number(bv) - Number(av);
        });
        return copy;
    }, [explore.table, sortKey, asc]);
    function toggle(key) {
        if (sortKey === key)
            setAsc((v) => !v);
        else {
            setSortKey(key);
            setAsc(key === "label");
        }
    }
    const entityHeader = explore.group === "none" ? "Entity" : explore.group.charAt(0).toUpperCase() + explore.group.slice(1).replace("_", " ");
    return (_jsxs("div", { className: "explore-table card", children: [_jsx("div", { className: "explore-table__scroll", children: _jsxs("table", { children: [_jsx("thead", { children: _jsx("tr", { children: [
                                    ["label", entityHeader],
                                    ["min", "Min"],
                                    ["max", "Max"],
                                    ["avg", "Avg"],
                                    ["sum", "Sum"],
                                    ["value", "Value"],
                                    ["pct", "% of Total"],
                                ].map(([key, title]) => (_jsx("th", { children: _jsxs("button", { type: "button", className: "explore-table__sort", onClick: () => toggle(key), children: [title, _jsx("span", { className: "explore-table__arrows", "aria-hidden": true, children: sortKey === key ? (asc ? "↑" : "↓") : "↕" })] }) }, key))) }) }), _jsxs("tbody", { children: [rows.map((row) => (_jsxs("tr", { children: [_jsx("td", { children: _jsxs("span", { className: "explore-table__entity", children: [_jsx("span", { className: "overview-chart-card__dot", style: { background: row.color } }), _jsx(ModelName, { modelId: row.key.includes("›") ? row.key.split("›")[0] : row.key, label: row.label, showIcon: (explore.group === "model" || explore.group === "provider") &&
                                                            row.key !== "__others__" &&
                                                            !row.key.startsWith("__"), size: 15 })] }) }), _jsx("td", { children: formatCell(explore.metric, row.min) }), _jsx("td", { children: formatCell(explore.metric, row.max) }), _jsx("td", { children: formatCell(explore.metric, row.avg) }), _jsx("td", { children: formatCell(explore.metric, row.sum) }), _jsx("td", { children: formatCell(explore.metric, row.value) }), _jsx("td", { children: _jsxs("span", { className: "explore-table__pct", children: [_jsx("span", { className: "explore-table__bar-track", children: _jsx("span", { className: "explore-table__bar", style: { width: `${Math.min(100, Math.max(0, row.pct))}%`, background: row.color } }) }), _jsxs("span", { children: [row.pct.toFixed(1), "%"] })] }) })] }, row.key))), rows.length === 0 ? (_jsx("tr", { children: _jsx("td", { colSpan: 7, className: "muted-text", children: "No rows in this period" }) })) : null] })] }) }), _jsxs("p", { className: "explore-table__footer muted-text", children: [explore.meta.row_count, " rows \u00B7 ", explore.meta.entity_count, " shown"] })] }));
}
