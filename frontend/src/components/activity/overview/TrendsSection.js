import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import OverviewStackedCard from "./OverviewStackedCard";
import TrendsTrendingList, { TrendsMetricSelect } from "./TrendsTrendingList";
export default function TrendsSection({ title, focus, dimension, onExplore }) {
    const [metric, setMetric] = useState("spend");
    return (_jsxs("section", { className: "trends-section", children: [_jsx("h2", { className: "trends-section__title", children: title }), _jsxs("div", { className: "trends-section__grid", children: [_jsx("div", { className: "trends-section__metric", children: _jsx(TrendsMetricSelect, { metric: metric, onMetricChange: setMetric }) }), _jsx(OverviewStackedCard, { title: "Spend over time", focus: focus, data: dimension.spend_over_time, valuePrefix: "spend_", valueKind: "spend", onExplore: onExplore, chartHeight: 240 }), _jsx(TrendsTrendingList, { itemsByMetric: dimension.trending, focus: focus, onExplore: onExplore, metric: metric })] })] }));
}
