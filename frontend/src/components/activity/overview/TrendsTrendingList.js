import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import ModelName from "../../ModelName";
import ModelProviderIcon from "../../ModelProviderIcon";
import OverviewExploreLink from "./OverviewExploreLink";
const METRIC_OPTIONS = [
    { value: "spend", label: "Spend" },
    { value: "requests", label: "Requests" },
    { value: "tokens", label: "Tokens" },
];
function formatChange(item) {
    if (item.is_new)
        return "New";
    if (item.change_pct == null)
        return "—";
    const abs = Math.abs(item.change_pct);
    if (abs > 999)
        return ">999%";
    return `${abs.toFixed(0)}%`;
}
function Spark({ values, down }) {
    const data = useMemo(() => values.map((v, i) => ({ i, v })), [values]);
    const color = down ? "#ef4444" : "#16a34a";
    return (_jsx("div", { className: "trends-spark", children: _jsx(ResponsiveContainer, { width: "100%", height: 28, children: _jsxs(LineChart, { data: data, margin: { top: 2, right: 0, left: 0, bottom: 2 }, children: [_jsx(YAxis, { hide: true, domain: ["dataMin", "dataMax"] }), _jsx(Line, { type: "monotone", dataKey: "v", stroke: color, strokeWidth: 1.5, dot: false, isAnimationActive: false })] }) }) }));
}
export function TrendsMetricSelect({ metric, onMetricChange, }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const label = METRIC_OPTIONS.find((o) => o.value === metric)?.label ?? "Spend";
    useEffect(() => {
        if (!open)
            return;
        const onDoc = (e) => {
            if (ref.current && !ref.current.contains(e.target))
                setOpen(false);
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [open]);
    return (_jsxs("div", { className: "trends-metric-menu", ref: ref, children: [_jsxs("button", { type: "button", className: `trends-metric-trigger${open ? " is-open" : ""}`, onClick: () => setOpen((v) => !v), "aria-expanded": open, "aria-haspopup": "listbox", "aria-label": "Trending metric", children: [_jsx("span", { children: label }), _jsx("svg", { viewBox: "0 0 16 16", width: "12", height: "12", "aria-hidden": true, children: _jsx("path", { d: "M4 6l4 4 4-4", fill: "none", stroke: "currentColor", strokeWidth: "1.6", strokeLinecap: "round", strokeLinejoin: "round" }) })] }), open ? (_jsx("div", { className: "trends-metric-panel card", role: "listbox", children: METRIC_OPTIONS.map((opt) => (_jsx("button", { type: "button", role: "option", "aria-selected": metric === opt.value, className: `activity-menu-item${metric === opt.value ? " activity-menu-item--active" : ""}`, onClick: () => {
                        onMetricChange(opt.value);
                        setOpen(false);
                    }, children: opt.label }, opt.value))) })) : null] }));
}
export default function TrendsTrendingList({ itemsByMetric, focus, onExplore, metric, }) {
    const items = itemsByMetric[metric] ?? [];
    return (_jsxs("article", { className: "trends-trending card", children: [_jsxs("header", { className: "overview-card-head", children: [_jsx("h3", { children: "Trending" }), _jsx(OverviewExploreLink, { focus: focus, onExplore: onExplore })] }), _jsxs("ul", { className: "trends-trending__list", children: [items.map((item) => {
                        const down = !item.is_new && (item.change_pct ?? 0) < 0;
                        const up = item.is_new || (item.change_pct ?? 0) > 0;
                        return (_jsxs("li", { children: [focus === "trends_models" ? (_jsx("span", { className: "trends-trending__avatar trends-trending__avatar--provider", style: { color: item.color }, children: _jsx(ModelProviderIcon, { modelId: item.key, provider: item.provider, size: 18 }) })) : (_jsx("span", { className: "trends-trending__avatar", style: { background: `${item.color}22`, color: item.color }, children: item.initials })), _jsxs("span", { className: "trends-trending__meta", children: [_jsx("span", { className: "trends-trending__name", children: focus === "trends_models" ? (_jsx(ModelName, { modelId: item.key, label: item.label, provider: item.provider, showIcon: false, size: 14 })) : (item.label) }), item.subtitle || (focus === "trends_models" && item.provider) ? (_jsx("span", { className: "trends-trending__sub muted-text", children: focus === "trends_models" && item.provider
                                                ? `by ${item.provider}`
                                                : item.subtitle })) : null] }), _jsx(Spark, { values: item.sparkline, down: down }), _jsxs("span", { className: `trends-trending__change${down ? " is-down" : ""}${up ? " is-up" : ""}`, children: [down ? "↓" : up ? "↑" : "·", " ", formatChange(item)] })] }, item.key));
                    }), items.length === 0 ? (_jsx("li", { className: "trends-trending__empty muted-text", children: "No trending entities in this period" })) : null] })] }));
}
