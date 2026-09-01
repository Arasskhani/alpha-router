import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";
function defaultFormat(v) {
    return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
export default function OperationsMetricCard({ title, total, unit = "", segments, chartRows, formatValue = defaultFormat, chartFormatValue, totalLabel: totalLabelOverride, chartHeight = 140, changePct = null, footer, }) {
    const data = useMemo(() => chartRows.map((row) => {
        const point = { label: String(row.label ?? "") };
        for (const s of segments) {
            point[s.key] = Number(row[s.key] ?? 0);
        }
        return point;
    }), [chartRows, segments]);
    const breakdown = useMemo(() => [...segments].filter((s) => s.value > 0).sort((a, b) => b.value - a.value), [segments]);
    const totalLabel = totalLabelOverride ?? `${formatValue(total)}${unit}`;
    const axisFormat = chartFormatValue ?? formatValue;
    const changeClass = changePct == null ? "" : changePct < 0 ? " activity-change-badge--down" : changePct > 0 ? " activity-change-badge--up" : "";
    return (_jsxs("article", { className: "activity-metric-card card", children: [_jsxs("header", { className: "activity-metric-card__head", children: [_jsxs("div", { className: "activity-metric-card__title-row", children: [_jsx("h3", { children: title }), changePct != null ? (_jsxs("span", { className: `activity-change-badge${changeClass}`, title: "vs previous 24h", children: [changePct > 0 ? "+" : "", changePct, "%"] })) : null] }), _jsx("span", { className: "activity-metric-card__total activity-metric-card__total--header", children: totalLabel })] }), _jsx("div", { className: "activity-metric-card__chart", style: { minHeight: chartHeight }, children: _jsx(ResponsiveContainer, { width: "100%", height: chartHeight, children: _jsxs(BarChart, { data: data, margin: { top: 4, right: 4, left: -18, bottom: 0 }, barCategoryGap: "12%", children: [_jsx(CartesianGrid, { strokeDasharray: "3 3", stroke: "var(--border)", vertical: false }), _jsx(XAxis, { dataKey: "label", tick: { fontSize: 9 }, interval: "preserveStartEnd" }), _jsx(YAxis, { tick: { fontSize: 9 }, width: 40, tickFormatter: (v) => axisFormat(Number(v)) }), _jsx(Tooltip, { formatter: (value, name) => {
                                    const seg = segments.find((m) => m.key === name);
                                    return [axisFormat(value), seg?.label ?? name];
                                }, labelFormatter: (label) => String(label) }), segments.map((s) => (_jsx(Bar, { dataKey: s.key, stackId: "stack", fill: s.color, maxBarSize: 28, isAnimationActive: false }, s.key)))] }) }) }), _jsxs("ul", { className: "activity-metric-card__legend", children: [breakdown.map((s) => (_jsxs("li", { children: [_jsx("span", { className: "activity-legend-dot", style: { background: s.color }, "aria-hidden": true }), _jsx("span", { className: "activity-legend-label", children: s.label }), _jsx("span", { className: "activity-legend-value", children: formatValue(s.value) })] }, s.key))), breakdown.length === 0 ? _jsx("li", { className: "activity-legend-empty", children: "No samples yet \u2014 use Check Now" }) : null] }), footer ? (_jsxs("footer", { className: "activity-metric-card__footer", children: [_jsxs("div", { className: "activity-metric-card__footer-stat", children: [_jsx("span", { className: "activity-metric-card__footer-label", children: footer.label }), _jsx("span", { className: "activity-metric-card__footer-value", children: footer.value })] }), footer.secondary ? (_jsxs("div", { className: "activity-metric-card__footer-stat activity-metric-card__footer-stat--end", children: [_jsx("span", { className: "activity-metric-card__footer-label", children: footer.secondary.label }), _jsx("span", { className: "activity-metric-card__footer-value", children: footer.secondary.value })] })) : null] })) : null] }));
}
