import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo } from "react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { formatRequests, formatSpend, formatTokens } from "../formatters";
const KPI_META = [
    { key: "spend", title: "Total spend", format: formatSpend },
    { key: "requests", title: "Requests", format: formatRequests },
    { key: "tokens", title: "Token volume", format: formatTokens },
    {
        key: "cache_hit_rate",
        title: "Cache hit rate",
        format: (v) => `${v.toFixed(1)}%`,
    },
    {
        key: "blended_per_1m",
        title: "Blended $/1M",
        format: (v) => `$${v.toFixed(2)}`,
    },
];
function OverviewKpiCard({ title, format, kpi, }) {
    const change = kpi.change_pct;
    const down = change != null && change < 0;
    const up = change != null && change > 0;
    const sparkColor = down ? "#ef4444" : up ? "#22c55e" : "var(--muted)";
    const chartData = useMemo(() => kpi.sparkline.map((v, i) => ({ i, v })), [kpi.sparkline]);
    return (_jsxs("article", { className: "overview-kpi-card card", children: [_jsx("p", { className: "overview-kpi-card__title", children: title }), _jsxs("div", { className: "overview-kpi-card__body", children: [_jsxs("div", { className: "overview-kpi-card__main", children: [_jsx("p", { className: "overview-kpi-card__value", children: format(kpi.value) }), change != null ? (_jsxs("p", { className: `overview-kpi-card__change${down ? " is-down" : up ? " is-up" : ""}`, children: [down ? "↓" : up ? "↑" : "·", " ", Math.abs(change).toFixed(1), "%"] })) : (_jsx("p", { className: "overview-kpi-card__change muted-text", children: "\u2014" })), _jsx("p", { className: "overview-kpi-card__vs muted-text", children: "vs prev period" })] }), _jsx("div", { className: "overview-kpi-card__spark", children: _jsx(ResponsiveContainer, { width: "100%", height: 44, children: _jsxs(LineChart, { data: chartData, margin: { top: 4, right: 0, left: 0, bottom: 0 }, children: [_jsx(YAxis, { hide: true, domain: ["dataMin", "dataMax"] }), _jsx(Line, { type: "monotone", dataKey: "v", stroke: sparkColor, strokeWidth: 1.5, dot: false, isAnimationActive: false })] }) }) })] })] }));
}
export default function OverviewKpiRow({ kpis }) {
    return (_jsx("div", { className: "overview-kpi-row", children: KPI_META.map((meta) => (_jsx(OverviewKpiCard, { title: meta.title, format: meta.format, kpi: kpis[meta.key] }, meta.key))) }));
}
