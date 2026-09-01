import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";
import ModelName from "../../ModelName";
import { formatRequests, formatSpend, formatTokens } from "../formatters";
import OverviewExploreLink from "./OverviewExploreLink";
function formatAxis(kind, v) {
    if (kind === "spend")
        return formatSpend(v);
    if (kind === "requests")
        return formatRequests(v);
    if (kind === "tokens")
        return formatTokens(v);
    if (v >= 1_000_000)
        return `${(v / 1_000_000).toFixed(0)}M`;
    if (v >= 1000)
        return `${(v / 1000).toFixed(0)}K`;
    return String(Math.round(v));
}
export default function OverviewStackedCard({ title, focus, data, valuePrefix = "", valueKind = "raw", onExplore, chartHeight = 220, }) {
    const rows = useMemo(() => {
        return data.chart.map((row) => {
            const point = { label: String(row.label ?? "") };
            for (const s of data.segments) {
                const key = valuePrefix ? `${valuePrefix}${s.key}` : s.key;
                point[s.key] = Number(row[key] ?? 0);
            }
            return point;
        });
    }, [data.chart, data.segments, valuePrefix]);
    return (_jsxs("article", { className: "overview-chart-card card", children: [_jsxs("header", { className: "overview-card-head", children: [_jsx("h3", { children: title }), _jsx(OverviewExploreLink, { focus: focus, onExplore: onExplore })] }), _jsx("div", { className: "overview-chart-card__chart", children: _jsx(ResponsiveContainer, { width: "100%", height: chartHeight, children: _jsxs(BarChart, { data: rows, margin: { top: 8, right: 8, left: 0, bottom: 0 }, children: [_jsx(CartesianGrid, { strokeDasharray: "3 3", stroke: "var(--border)", vertical: true, horizontal: true }), _jsx(XAxis, { dataKey: "label", tick: { fontSize: 11, fill: "var(--muted)" }, axisLine: false, tickLine: false }), _jsx(YAxis, { tick: { fontSize: 11, fill: "var(--muted)" }, axisLine: false, tickLine: false, width: 44, tickFormatter: (v) => formatAxis(valueKind, Number(v)) }), _jsx(Tooltip, { formatter: (value, name) => {
                                    const seg = data.segments.find((s) => s.key === name);
                                    return [formatAxis(valueKind, value), seg?.label ?? name];
                                }, contentStyle: {
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    borderRadius: 8,
                                    fontSize: 12,
                                } }), data.segments.map((s) => (_jsx(Bar, { dataKey: s.key, stackId: "a", fill: s.color, maxBarSize: 18 }, s.key)))] }) }) }), _jsx("ul", { className: "overview-chart-card__legend", children: data.segments.map((s) => (_jsxs("li", { children: [_jsx("span", { className: "overview-chart-card__dot", style: { background: s.color } }), _jsx(ModelName, { modelId: s.key, label: s.label, showIcon: (focus === "usage_by_model" ||
                                focus === "request_volume" ||
                                focus === "trends_models") &&
                                s.key !== "__others__" &&
                                !s.key.startsWith("__"), size: 14 })] }, s.key))) })] }));
}
