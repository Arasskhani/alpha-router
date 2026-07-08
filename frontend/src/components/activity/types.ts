export type Period = "15m" | "30m" | "1h" | "3h" | "day" | "2d" | "week" | "month" | "year";
export type PromptsPeriod = "day" | "week" | "month";
export type GroupBy = "model" | "app" | "user";
export type TimezoneMode = "local" | "utc";
export type MetricKind = "spend" | "requests" | "tokens";
export type HeatmapMetric = "requests" | "tokens" | "spend";

export type SegmentMeta = {
  key: string;
  label: string;
  color: string;
  spend: number;
  requests: number;
  tokens: number;
};

export type FilterOption = { key: string; label: string };

export type HeatmapDay = {
  date: string;
  requests: number;
  tokens: number;
  spend: number;
  level_requests: number;
  level_tokens: number;
  level_spend: number;
};

export type UsageMetricStats = {
  streak_days: number;
  avg_day: number;
  avg_week: number;
  total: number;
};

export type PromptsCardData = {
  period: PromptsPeriod;
  chart: Record<string, string | number>[];
  models: SegmentMeta[];
  total: number;
  change_pct: number | null;
  period_footer_label: string;
  period_prompts: number;
  streak_days: number;
};

export type ActivityInsights = {
  streak_days: number;
  change_pct: {
    prompts: number | null;
    tokens: number | null;
    spend: number | null;
  };
  period_footer_label: string;
  period_prompts: number;
  heatmap: { days: HeatmapDay[] };
  usage_stats: Record<HeatmapMetric, UsageMetricStats>;
};

export type ActivityPayload = {
  scope?: string;
  period: Period;
  group_by: GroupBy;
  timezone: TimezoneMode;
  totals: { spend: number; requests: number; tokens: number };
  models: SegmentMeta[];
  top_models: SegmentMeta[];
  chart: Record<string, string | number>[];
  prompts?: PromptsCardData;
  insights: ActivityInsights;
  guardrails: {
    blocked_requests: number;
    cached_prompts: number;
    redacted_flagged?: number;
  };
  available_models: FilterOption[];
  available_users?: FilterOption[];
  available_apps?: FilterOption[];
  filters?: {
    model_id?: string | null;
    username?: string | null;
    app?: string | null;
    response_status?: string | null;
  };
  model_id?: string | null;
  user?: { id: number; username: string; display_name?: string | null };
  group?: { id: number; name: string; member_count?: number };
  api_key?: { id: number; name: string; prefix?: string };
  connection?: {
    id: number;
    name: string;
    provider_type: string;
    base_url?: string | null;
    is_active: boolean;
  };
};
