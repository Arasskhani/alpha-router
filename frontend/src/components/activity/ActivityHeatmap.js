import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo } from "react";
import { dateKeyForTimezone, formatHeatmapTooltip, formatHeatmapValue } from "./formatters";
function metricValue(day, metric) {
    if (metric === "tokens")
        return day.tokens;
    if (metric === "spend")
        return day.spend;
    return day.requests;
}
function metricLevel(day, metric) {
    if (metric === "tokens")
        return day.level_tokens;
    if (metric === "spend")
        return day.level_spend;
    return day.level_requests;
}
function monthLabel(date) {
    return date.toLocaleString("en-US", { month: "short" });
}
export default function ActivityHeatmap({ insights, metric, timezone, onMetricChange }) {
    const days = insights.heatmap.days;
    const weeks = useMemo(() => {
        if (!days.length)
            return [];
        const first = new Date(`${days[0].date}T12:00:00`);
        const last = new Date(`${days[days.length - 1].date}T12:00:00`);
        const start = new Date(first);
        start.setDate(start.getDate() - start.getDay());
        const byDate = new Map(days.map((d) => [d.date, d]));
        const grid = [];
        const cursor = new Date(start);
        let lastMonth = "";
        while (cursor <= last || cursor.getDay() !== 0) {
            const weekCells = [];
            let month;
            for (let i = 0; i < 7; i += 1) {
                const key = dateKeyForTimezone(cursor, timezone);
                weekCells.push(byDate.get(key) ?? null);
                const m = monthLabel(cursor);
                if (m !== lastMonth) {
                    month = m;
                    lastMonth = m;
                }
                cursor.setDate(cursor.getDate() + 1);
            }
            grid.push({ month, cells: weekCells });
            if (cursor > last && cursor.getDay() === 0)
                break;
        }
        return grid;
    }, [days, timezone]);
    const sideStats = useMemo(() => {
        const s = insights.usage_stats[metric];
        return {
            streak: s.streak_days,
            avgDay: formatHeatmapValue(metric, s.avg_day),
            avgWeek: formatHeatmapValue(metric, s.avg_week),
            total: formatHeatmapValue(metric, s.total),
        };
    }, [insights.usage_stats, metric]);
    return (_jsxs("article", { className: `activity-heatmap card activity-heatmap--${metric}`, children: [_jsxs("header", { className: "activity-heatmap__head", children: [_jsx("h3", { children: "Usage" }), _jsx("div", { className: "activity-segmented", role: "tablist", "aria-label": "Heatmap metric", children: ["requests", "tokens", "spend"].map((m) => (_jsx("button", { type: "button", role: "tab", "aria-selected": metric === m, className: metric === m ? "activity-segmented__btn activity-segmented__btn--active" : "activity-segmented__btn", onClick: () => onMetricChange(m), children: m === "requests" ? "Requests" : m === "tokens" ? "Tokens" : "Spend" }, m))) })] }), _jsxs("div", { className: "activity-heatmap__body", children: [_jsxs("div", { className: "activity-heatmap__grid-wrap", children: [_jsxs("div", { className: "activity-heatmap__chart-row", children: [_jsxs("div", { className: "activity-heatmap__dow", "aria-hidden": true, children: [_jsx("span", { children: "M" }), _jsx("span", {}), _jsx("span", { children: "W" }), _jsx("span", {}), _jsx("span", { children: "F" }), _jsx("span", {}), _jsx("span", {})] }), weeks.length > 0 ? (_jsx("div", { className: "activity-heatmap__grid", children: weeks.map((week, wi) => (_jsxs("div", { className: "activity-heatmap__week", children: [week.month ? (_jsx("span", { className: "activity-heatmap__month", children: week.month })) : (_jsx("span", { className: "activity-heatmap__month" })), _jsx("div", { className: "activity-heatmap__cells", children: week.cells.map((cell, di) => (_jsx("span", { className: `activity-heatmap__cell activity-heatmap__cell--l${cell ? metricLevel(cell, metric) : 0}`, title: cell
                                                            ? formatHeatmapTooltip(metric, metricValue(cell, metric), cell.date)
                                                            : undefined }, `${wi}-${di}`))) })] }, wi))) })) : (_jsx("p", { className: "activity-heatmap__empty muted", children: "No usage history for this range yet." }))] }), _jsxs("div", { className: "activity-heatmap__legend-scale", children: [_jsx("span", { children: "Less" }), _jsx("span", { className: "activity-heatmap__cell activity-heatmap__cell--l0" }), _jsx("span", { className: "activity-heatmap__cell activity-heatmap__cell--l1" }), _jsx("span", { className: "activity-heatmap__cell activity-heatmap__cell--l2" }), _jsx("span", { className: "activity-heatmap__cell activity-heatmap__cell--l3" }), _jsx("span", { className: "activity-heatmap__cell activity-heatmap__cell--l4" }), _jsx("span", { children: "More" })] })] }), _jsxs("aside", { className: "activity-heatmap__stats", children: [_jsxs("div", { children: [_jsx("p", { className: "activity-heatmap__stat-value", children: sideStats.streak }), _jsx("p", { className: "activity-heatmap__stat-label", children: "Streak" })] }), _jsxs("div", { children: [_jsx("p", { className: "activity-heatmap__stat-value", children: sideStats.avgDay }), _jsx("p", { className: "activity-heatmap__stat-label", children: "Avg Day" })] }), _jsxs("div", { children: [_jsx("p", { className: "activity-heatmap__stat-value", children: sideStats.avgWeek }), _jsx("p", { className: "activity-heatmap__stat-label", children: "Avg Week" })] }), _jsxs("div", { children: [_jsx("p", { className: "activity-heatmap__stat-value", children: sideStats.total }), _jsx("p", { className: "activity-heatmap__stat-label", children: "Total" })] })] })] })] }));
}
