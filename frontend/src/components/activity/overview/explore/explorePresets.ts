import type { ExploreControls, ExploreGroup, ExploreMetric, OverviewFocus } from "../../types";

export const EXPLORE_METRIC_OPTIONS: { value: ExploreMetric; label: string }[] = [
  { value: "request_count", label: "Request Count" },
  { value: "total_usage", label: "Total Usage ($)" },
  { value: "tokens_total", label: "Tokens (Total)" },
  { value: "tokens_prompt", label: "Tokens (Prompt)" },
  { value: "tokens_completion", label: "Tokens (Completion)" },
  { value: "cached_tokens", label: "Cached Tokens" },
  { value: "avg_latency", label: "Avg Latency" },
  { value: "p50_latency", label: "P50 Latency" },
];

export const EXPLORE_GROUP_OPTIONS: { value: ExploreGroup; label: string }[] = [
  { value: "none", label: "None" },
  { value: "model", label: "Model" },
  { value: "api_key", label: "API Key" },
  { value: "provider", label: "Provider" },
  { value: "app", label: "App" },
  { value: "user", label: "User" },
];

export const EXPLORE_ROLLUP_OPTIONS = [
  { value: "total" as const, label: "Total" },
  { value: "hourly" as const, label: "Hourly" },
  { value: "daily" as const, label: "Daily" },
  { value: "weekly" as const, label: "Weekly" },
  { value: "monthly" as const, label: "Monthly" },
];

export const EXPLORE_TOP_N_OPTIONS = [5, 10, 15, 30];

export const DEFAULT_EXPLORE_CONTROLS: ExploreControls = {
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

export function explorePresetFromFocus(focus: OverviewFocus | null): Partial<ExploreControls> | null {
  if (!focus) return null;
  const map: Partial<Record<OverviewFocus, Partial<ExploreControls>>> = {
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
export function groupLabel(group: ExploreGroup): string {
  return EXPLORE_GROUP_OPTIONS.find((o) => o.value === group)?.label ?? group;
}
