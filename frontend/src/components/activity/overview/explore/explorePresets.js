export const EXPLORE_METRIC_OPTIONS = [
    { value: "request_count", label: "Request Count" },
    { value: "total_usage", label: "Total Usage ($)" },
    { value: "tokens_total", label: "Tokens (Total)" },
    { value: "tokens_prompt", label: "Tokens (Prompt)" },
    { value: "tokens_completion", label: "Tokens (Completion)" },
    { value: "cached_tokens", label: "Cached Tokens" },
    { value: "avg_latency", label: "Avg Latency" },
    { value: "p50_latency", label: "P50 Latency" },
];
export const EXPLORE_GROUP_OPTIONS = [
    { value: "none", label: "None" },
    { value: "model", label: "Model" },
    { value: "api_key", label: "API Key" },
    { value: "provider", label: "Provider" },
    { value: "app", label: "App" },
    { value: "user", label: "User" },
];
export const EXPLORE_ROLLUP_OPTIONS = [
    { value: "total", label: "Total" },
    { value: "hourly", label: "Hourly" },
    { value: "daily", label: "Daily" },
    { value: "weekly", label: "Weekly" },
    { value: "monthly", label: "Monthly" },
];
export const EXPLORE_TOP_N_OPTIONS = [5, 10, 15, 30];
export const DEFAULT_EXPLORE_CONTROLS = {
    metric: "total_usage",
    group: "model",
    subgroup: "",
    rollup: "daily",
    topMode: "top",
    topN: 10,
    rankBy: "metric",
    showOther: true,
    cumulative: false,
    chartType: "bar",
};
export function explorePresetFromFocus(focus) {
    if (!focus)
        return null;
    const map = {
        users: { group: "user", metric: "total_usage" },
        trends_users: { group: "user", metric: "total_usage" },
        apps: { group: "app", metric: "total_usage" },
        trends_apps: { group: "app", metric: "total_usage" },
        usage_by_model: { group: "model", metric: "total_usage" },
        trends_models: { group: "model", metric: "total_usage" },
        trends_api_keys: { group: "api_key", metric: "total_usage" },
        request_volume: { group: "model", metric: "request_count" },
        token_breakdown: { group: "model", metric: "tokens_total" },
        prompt_caching: { group: "model", metric: "cached_tokens" },
    };
    return map[focus] ?? null;
}
export function metricLabel(metric) {
    return EXPLORE_METRIC_OPTIONS.find((o) => o.value === metric)?.label ?? metric;
}
export function groupLabel(group) {
    return EXPLORE_GROUP_OPTIONS.find((o) => o.value === group)?.label ?? group;
}
