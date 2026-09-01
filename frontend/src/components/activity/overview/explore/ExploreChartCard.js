import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";
import ModelName from "../../../ModelName";
import { formatRequests, formatSpend, formatTokens } from "../../formatters";
function formatAxis(metric, v) {
    if (metric === "total_usage")
        return formatSpend(v);
    if (metric === "request_count")
        return formatRequests(v);
    if (metric === "avg_latency" || metric === "p50_latency") {
        if (v >= 1000)
            return `${(v / 1000).toFixed(1)}s`;
        return `${Math.round(v)}`;
    }
    if (v >= 1_000_000)
        return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1000)
        return `${(v / 1000).toFixed(0)}K`;
    return formatTokens(v);
}
function IconAxes({ children }) {
    return (_jsxs("svg", { viewBox: "0 0 20 20", width: "18", height: "18", "aria-hidden": true, children: [_jsx("path", { d: "M3 3v14h14", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round" }), children] }));
}
function IconChartBar() {
    return (_jsxs(IconAxes, { children: [_jsx("rect", { x: "6", y: "7", width: "2.8", height: "8", rx: "0.4", fill: "currentColor" }), _jsx("rect", { x: "11", y: "10", width: "2.8", height: "5", rx: "0.4", fill: "currentColor" })] }));
}
function IconChartLine() {
    return (_jsx(IconAxes, { children: _jsx("path", { d: "M5.5 13.5 L9 7.5 L12 11 L16 6.5", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round" }) }));
}
function IconChartPoints() {
    return (_jsxs(IconAxes, { children: [_jsx("circle", { cx: "7", cy: "13", r: "1.6", fill: "currentColor" }), _jsx("circle", { cx: "11", cy: "9.5", r: "1.6", fill: "currentColor" }), _jsx("circle", { cx: "15", cy: "6.5", r: "1.6", fill: "currentColor" })] }));
}
function IconDownload() {
    return (_jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.7", "aria-hidden": true, children: [_jsx("path", { d: "M12 4v10", strokeLinecap: "round" }), _jsx("path", { d: "M8 11l4 4 4-4", strokeLinecap: "round", strokeLinejoin: "round" }), _jsx("path", { d: "M5 19h14", strokeLinecap: "round" })] }));
}
function IconDoc() {
    return (_jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.7", "aria-hidden": true, children: [_jsx("path", { d: "M7 3.5h7l4 4V20.5H7z", strokeLinejoin: "round" }), _jsx("path", { d: "M14 3.5V8h4.5", strokeLinejoin: "round" }), _jsx("path", { d: "M10 12h6M10 15.5h6", strokeLinecap: "round" })] }));
}
function IconBookmarkPlus() {
    return (_jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "none", stroke: "currentColor", strokeWidth: "1.7", "aria-hidden": true, children: [_jsx("path", { d: "M7 4.5h10v15l-5-3.2-5 3.2z", strokeLinejoin: "round" }), _jsx("path", { d: "M12 8v5M9.5 10.5h5", strokeLinecap: "round" })] }));
}
function IconChevronRight() {
    return (_jsx("svg", { viewBox: "0 0 16 16", width: "12", height: "12", fill: "none", stroke: "currentColor", strokeWidth: "1.6", "aria-hidden": true, children: _jsx("path", { d: "M6 3.5 L11 8 L6 12.5", strokeLinecap: "round", strokeLinejoin: "round" }) }));
}
const CHART_TYPES = [
    { type: "bar", label: "Bar", Icon: IconChartBar },
    { type: "line", label: "Line", Icon: IconChartLine },
    { type: "area", label: "Points", Icon: IconChartPoints },
];
export default function ExploreChartCard({ explore, controls, onChange, onDownloadPdf }) {
    const [menuOpen, setMenuOpen] = useState(false);
    const [pdfOpen, setPdfOpen] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const menuRef = useRef(null);
    const rows = useMemo(() => {
        return explore.chart.map((row) => {
            const point = { label: String(row.label ?? "") };
            for (const s of explore.segments) {
                point[s.key] = Number(row[`v_${s.key}`] ?? 0);
            }
            return point;
        });
    }, [explore.chart, explore.segments]);
    useEffect(() => {
        if (!menuOpen) {
            setPdfOpen(false);
            return;
        }
        const onDoc = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target))
                setMenuOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [menuOpen]);
    function downloadCsv() {
        const headers = ["entity", "min", "max", "avg", "sum", "value", "pct", "requests"];
        const lines = [headers.join(",")];
        for (const row of explore.table) {
            lines.push([
                JSON.stringify(row.label),
                row.min,
                row.max,
                row.avg,
                row.sum,
                row.value,
                row.pct,
                row.requests,
            ].join(","));
        }
        const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `alpha-router-explore-${explore.metric}-${explore.group}.csv`;
        a.click();
        URL.revokeObjectURL(url);
        setMenuOpen(false);
    }
    const chartHeight = expanded ? 420 : 280;
    const Chart = controls.chartType === "line" ? LineChart : controls.chartType === "area" ? AreaChart : BarChart;
    return (_jsxs("div", { className: "explore-chart-wrap", children: [_jsxs("div", { className: "explore-chart-wrap__toolbar", ref: menuRef, children: [_jsxs("div", { className: "explore-chart__btn-group", children: [_jsx("button", { type: "button", className: `explore-chart__icon-btn${menuOpen ? " is-open" : ""}`, "aria-label": "Chart options", "aria-expanded": menuOpen, onClick: () => setMenuOpen((v) => !v), children: _jsxs("svg", { viewBox: "0 0 24 24", width: "16", height: "16", fill: "currentColor", "aria-hidden": true, children: [_jsx("circle", { cx: "12", cy: "5", r: "1.6" }), _jsx("circle", { cx: "12", cy: "12", r: "1.6" }), _jsx("circle", { cx: "12", cy: "19", r: "1.6" })] }) }), _jsx("button", { type: "button", className: "explore-chart__expand-btn", onClick: () => setExpanded((v) => !v), children: expanded ? (_jsxs(_Fragment, { children: [_jsx("svg", { viewBox: "0 0 24 24", width: "14", height: "14", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("path", { d: "M9 9L4 4M4 4h5M4 4v5M15 15l5 5M20 20h-5M20 20v-5", strokeLinecap: "round" }) }), "Collapse"] })) : (_jsxs(_Fragment, { children: [_jsx("svg", { viewBox: "0 0 24 24", width: "14", height: "14", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: _jsx("path", { d: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7", strokeLinecap: "round" }) }), "Expand"] })) })] }), menuOpen ? (_jsxs("div", { className: "explore-chart__menu card", children: [_jsxs("div", { className: "explore-chart__menu-section", children: [_jsxs("label", { className: "explore-chart__toggle", children: [_jsx("span", { children: "Show \"Other\"" }), _jsx("button", { type: "button", role: "switch", "aria-checked": controls.showOther, className: `explore-switch${controls.showOther ? " is-on" : ""}`, onClick: () => onChange({ showOther: !controls.showOther }, true), children: _jsx("span", { className: "explore-switch__thumb" }) })] }), _jsxs("label", { className: "explore-chart__toggle", children: [_jsx("span", { children: "Cumulative sum" }), _jsx("button", { type: "button", role: "switch", "aria-checked": controls.cumulative, className: `explore-switch${controls.cumulative ? " is-on" : ""}`, onClick: () => onChange({ cumulative: !controls.cumulative }, true), children: _jsx("span", { className: "explore-switch__thumb" }) })] }), _jsxs("div", { className: "explore-chart__type-row", children: [_jsx("span", { children: "Chart type" }), _jsx("div", { className: "explore-chart__type-group", role: "group", "aria-label": "Chart type", children: CHART_TYPES.map(({ type, label, Icon }) => (_jsx("button", { type: "button", title: label, "aria-label": label, "aria-pressed": controls.chartType === type, className: controls.chartType === type ? "is-active" : "", onClick: () => onChange({ chartType: type }, true), children: _jsx(Icon, {}) }, type))) })] })] }), _jsxs("div", { className: "explore-chart__menu-section", children: [_jsxs("button", { type: "button", className: "explore-chart__menu-item", onClick: downloadCsv, children: [_jsx(IconDownload, {}), _jsx("span", { children: "Download CSV" })] }), _jsxs("div", { className: "explore-chart__pdf-wrap", children: [_jsxs("button", { type: "button", className: `explore-chart__menu-item${pdfOpen ? " is-open" : ""}`, onClick: () => setPdfOpen((v) => !v), "aria-expanded": pdfOpen, children: [_jsx(IconDoc, {}), _jsx("span", { children: "Download PDF" }), _jsx("span", { className: "explore-chart__menu-chevron", children: _jsx(IconChevronRight, {}) })] }), pdfOpen ? (_jsxs("div", { className: "explore-chart__submenu card", children: [_jsx("button", { type: "button", className: "explore-chart__menu-item", onClick: () => {
                                                            onDownloadPdf?.("current");
                                                            setMenuOpen(false);
                                                        }, disabled: !onDownloadPdf, children: "Download current view" }), _jsx("button", { type: "button", className: "explore-chart__menu-item", onClick: () => {
                                                            onDownloadPdf?.("summary");
                                                            setMenuOpen(false);
                                                        }, disabled: !onDownloadPdf, children: "Download usage summary" })] })) : null] })] }), _jsx("div", { className: "explore-chart__menu-section", children: _jsxs("button", { type: "button", className: "explore-chart__menu-item is-disabled", disabled: true, title: "Coming soon", children: [_jsx(IconBookmarkPlus, {}), _jsx("span", { children: "Save current chart" })] }) })] })) : null] }), _jsxs("article", { className: `explore-chart card${expanded ? " is-expanded" : ""}`, children: [_jsx("div", { className: "explore-chart__plot", children: _jsx(ResponsiveContainer, { width: "100%", height: chartHeight, children: _jsxs(Chart, { data: rows, margin: { top: 8, right: 8, left: 0, bottom: 0 }, children: [_jsx(CartesianGrid, { strokeDasharray: "3 3", stroke: "var(--border)", vertical: true, horizontal: true }), _jsx(XAxis, { dataKey: "label", tick: { fontSize: 11, fill: "var(--muted)" }, axisLine: false, tickLine: false }), _jsx(YAxis, { tick: { fontSize: 11, fill: "var(--muted)" }, axisLine: false, tickLine: false, width: 48, tickFormatter: (v) => formatAxis(explore.metric, Number(v)) }), _jsx(Tooltip, { formatter: (value, name) => {
                                            const seg = explore.segments.find((s) => s.key === name);
                                            return [formatAxis(explore.metric, value), seg?.label ?? name];
                                        }, contentStyle: {
                                            background: "var(--surface)",
                                            border: "1px solid var(--border)",
                                            borderRadius: 8,
                                            fontSize: 12,
                                        } }), controls.chartType === "bar"
                                        ? explore.segments.map((s) => (_jsx(Bar, { dataKey: s.key, stackId: "a", fill: s.color, maxBarSize: 18 }, s.key)))
                                        : null, controls.chartType === "line"
                                        ? explore.segments.map((s) => (_jsx(Line, { type: "monotone", dataKey: s.key, stroke: s.color, strokeWidth: 2, dot: false, isAnimationActive: false }, s.key)))
                                        : null, controls.chartType === "area"
                                        ? explore.segments.map((s) => (_jsx(Area, { type: "monotone", dataKey: s.key, stackId: "a", stroke: s.color, fill: s.color, fillOpacity: 0.35, isAnimationActive: false }, s.key)))
                                        : null] }) }) }), _jsx("ul", { className: "overview-chart-card__legend explore-chart__legend", children: explore.segments.map((s) => (_jsxs("li", { children: [_jsx("span", { className: "overview-chart-card__dot", style: { background: s.color } }), _jsx(ModelName, { modelId: s.key.includes("›") ? s.key.split("›")[0] : s.key, label: s.label, showIcon: (explore.group === "model" || explore.group === "provider") &&
                                        s.key !== "__others__" &&
                                        !s.key.startsWith("__"), size: 14 })] }, s.key))) })] })] }));
}
