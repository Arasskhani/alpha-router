export function formatSpend(v) {
    if (v >= 10_000)
        return `$${Math.round(v / 1000)}K`;
    if (v >= 1000)
        return `$${(v / 1000).toFixed(1)}K`;
    if (v >= 100)
        return `$${v.toFixed(0)}`;
    if (v >= 10)
        return `$${v.toFixed(1)}`;
    return `$${v.toFixed(2)}`;
}
export function formatTokens(v) {
    if (v >= 1_000_000_000)
        return `${(v / 1_000_000_000).toFixed(2)}B`;
    if (v >= 1_000_000)
        return `${Math.round(v / 1_000_000)}M`;
    if (v >= 1_000)
        return `${(v / 1_000).toFixed(1)}K`;
    return String(Math.round(v));
}
export function formatRequests(v) {
    if (v >= 1_000_000)
        return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1000)
        return `${Math.round(v / 1000)}K`;
    return new Intl.NumberFormat("en-US").format(Math.round(v));
}
export function formatHeatmapValue(metric, v) {
    if (metric === "spend")
        return formatSpend(v);
    if (metric === "tokens")
        return formatTokens(v);
    return formatRequests(v);
}
export function formatMetricValue(kind, v) {
    if (kind === "spend")
        return formatSpend(v);
    if (kind === "tokens")
        return formatTokens(v);
    return formatRequests(v);
}
export function formatBreakdownValue(kind, v) {
    if (kind === "spend")
        return formatSpend(v);
    if (kind === "tokens")
        return formatTokens(v);
    return String(v);
}
export function periodLabel(period) {
    const labels = {
        "15m": "Past 15 Minutes",
        "30m": "Past 30 Minutes",
        "1h": "Past 1 Hour",
        "3h": "Past 3 Hours",
        day: "Past 1 Day",
        "2d": "Past 2 Days",
        week: "Past 1 Week",
        month: "Past 1 Month",
        year: "Past 1 Year",
    };
    return labels[period] ?? "Past 1 Day";
}
export function periodShortBadge(period) {
    const badges = {
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "3h": "3h",
        day: "1d",
        "2d": "2d",
        week: "7d",
        month: "30d",
        year: "1y",
    };
    return badges[period] ?? "1d";
}
export function promptsCardPeriodLabel(period) {
    if (period === "day")
        return "Today";
    if (period === "week")
        return "Last 7 Days";
    return "Last 30 Days";
}
export function groupByLabel(groupBy) {
    if (groupBy === "app")
        return "By API Key";
    if (groupBy === "user")
        return "By Creator";
    return "By Model";
}
export function localDateKey(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}
export function dateKeyForTimezone(d, timezone) {
    if (timezone === "utc")
        return d.toISOString().slice(0, 10);
    return localDateKey(d);
}
export function formatHeatmapTooltip(metric, value, dateIso) {
    const d = new Date(`${dateIso}T12:00:00`);
    const when = d.toLocaleDateString("en-US", {
        weekday: "short",
        month: "short",
        day: "numeric",
        year: "numeric",
    });
    const formatted = formatHeatmapValue(metric, value);
    if (metric === "spend")
        return `${formatted} on ${when}`;
    if (metric === "tokens")
        return `${formatted} tokens on ${when}`;
    return `${formatted} requests on ${when}`;
}
