import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Link } from "react-router-dom";
import ModelName from "../ModelName";
function fmtMs(ms) {
    if (ms >= 60_000)
        return `${(ms / 60_000).toFixed(1)}m`;
    if (ms >= 1000)
        return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.round(ms)}ms`;
}
export default function OperationsSlowModelsTable({ rows, thresholdMs }) {
    return (_jsxs("div", { className: "card operations-slow-models", children: [_jsx("h3", { children: "Slowest models (by P95)" }), _jsxs("p", { className: "muted-text", style: { marginTop: 0 }, children: ["Models with at least 3 requests in the last 24h, sorted by P95 latency. Slow request threshold:", " ", _jsxs("strong", { children: [thresholdMs / 1000, "s"] }), ".", " ", _jsx(Link, { to: "/admin/logs", children: "Open API Logs" }), " to inspect individual calls."] }), rows.length === 0 ? (_jsx("p", { className: "muted-text", children: "Not enough request data yet." })) : (_jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Model" }), _jsx("th", { className: "col-num", children: "Requests" }), _jsx("th", { className: "col-num", children: "Avg" }), _jsx("th", { className: "col-num", children: "P95" }), _jsx("th", { className: "col-num", children: "Errors" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((r) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx(ModelName, { modelId: r.model_id, label: r.model_id, size: 15 }) }), _jsx("td", { className: "col-num", children: r.requests.toLocaleString() }), _jsx("td", { className: "col-num", children: fmtMs(r.avg_ms) }), _jsx("td", { className: "col-num", children: fmtMs(r.p95_ms) }), _jsxs("td", { className: "col-num", children: [r.error_pct, "%"] }), _jsx("td", { children: _jsx(Link, { to: `/admin/logs?model_id=${encodeURIComponent(r.model_id)}`, className: "btn btn-ghost btn-sm", children: "Logs" }) })] }, r.model_id))) })] }) }))] }));
}
