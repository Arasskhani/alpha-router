export type Period = "15m" | "30m" | "1h" | "3h" | "day" | "2d" | "week" | "month" | "year";
export type PromptsPeriod = "day" | "week" | "month";
export type GroupBy = "model" | "app" | "user";
export type TimezoneMode = "local" | "utc";
export type HeatmapMetric = "requests" | "tokens" | "spend";

type SegmentMeta = {
  key: string;
  label: string;
  color: string;
  spend: number;
  requests: number;
  tokens: number;
};

export type FilterOption = { key: string; label: string };

export type ApiKeyFilterOption = FilterOption & {
  name?: string;
  prefix?: string;
};

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

type PromptsCardData = {
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

export type ActivityTab = "overview" | "trends" | "explore";

export type OverviewFocus =
  | "users"
  | "apps"
  | "usage_by_model"
  | "request_volume"
  | "token_breakdown"
  | "prompt_caching"
  | "trends_models"
  | "trends_users"
  | "trends_api_keys"
  | "trends_apps";

export type TrendsMetric = "spend" | "requests" | "tokens";

export type TrendsListItem = {
  key: string;
  label: string;
  subtitle?: string;
  initials: string;
  color: string;
  provider?: string;
  value: number;
  change_pct: number | null;
  is_new: boolean;
  sparkline: number[];
};

export type TrendsDimension = {
  spend_over_time: OverviewStackedChart;
  trending: Record<TrendsMetric, TrendsListItem[]>;
};

export type ActivityTrends = {
  models: TrendsDimension;
  users: TrendsDimension;
  api_keys: TrendsDimension;
  apps: TrendsDimension;
};

export type ExploreMetric =
  | "request_count"
  | "total_usage"
  | "tokens_total"
  | "tokens_prompt"
  | "tokens_completion"
  | "cached_tokens"
  | "avg_latency"
  | "p50_latency";

export type ExploreGroup = "none" | "model" | "api_key" | "provider" | "app" | "user";
export type ExploreRollup = "total" | "hourly" | "daily" | "weekly" | "monthly";
export type ExploreTopMode = "top" | "bottom";
export type ExploreRankBy = "metric" | "requests";
export type ExploreChartType = "bar" | "line" | "area";

type ExploreSegment = {
  key: string;
  label: string;
  color: string;
};

type ExploreTableRow = {
  key: string;
  label: string;
  color: string;
  min: number;
  max: number;
  avg: number;
  sum: number;
  value: number;
  pct: number;
  requests: number;
};

export type ActivityExplore = {
  metric: ExploreMetric;
  group: ExploreGroup;
  subgroup: ExploreGroup | null;
  rollup: ExploreRollup;
  top_mode: ExploreTopMode;
  top_n: number;
  rank_by: ExploreRankBy;
  show_other: boolean;
  cumulative: boolean;
  chart_type: ExploreChartType;
  segments: ExploreSegment[];
  chart: Record<string, string | number>[];
  table: ExploreTableRow[];
  meta: { row_count: number; entity_count: number };
};

export type ExploreControls = {
  metric: ExploreMetric;
  group: ExploreGroup;
  subgroup: ExploreGroup | "";
  rollup: ExploreRollup;
  topMode: ExploreTopMode;
  topN: number;
  rankBy: ExploreRankBy;
  showOther: boolean;
  cumulative: boolean;
  chartType: ExploreChartType;
};

export type OverviewKpi = {
  value: number;
  change_pct: number | null;
  sparkline: number[];
};

export type OverviewListItem = {
  key: string;
  label: string;
  initials: string;
  tokens: number;
};

type OverviewChartSeries = {
  key: string;
  label: string;
  color: string;
  spend?: number;
  requests?: number;
  tokens?: number;
};

export type OverviewStackedChart = {
  segments: OverviewChartSeries[];
  chart: Record<string, string | number>[];
};

export type ActivityOverview = {
  kpis: {
    spend: OverviewKpi;
    requests: OverviewKpi;
    tokens: OverviewKpi;
    cache_hit_rate: OverviewKpi;
    blended_per_1m: OverviewKpi;
    /** Automatic memory extraction. Part of `spend`, not additional to it. */
    memory_spend: OverviewKpi;
  };
  top_users: OverviewListItem[];
  top_apps: OverviewListItem[];
  usage_by_model: OverviewStackedChart;
  request_volume_by_model: OverviewStackedChart;
  token_breakdown: OverviewStackedChart;
  prompt_caching: OverviewStackedChart;
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
  overview?: ActivityOverview;
  trends?: ActivityTrends;
  explore?: ActivityExplore;
  available_models: FilterOption[];
  available_users?: FilterOption[];
  available_apps?: FilterOption[];
  available_api_keys?: ApiKeyFilterOption[];
  filters?: {
    model_id?: string | null;
    username?: string | null;
    app?: string | null;
    response_status?: string | null;
    alpha_router_api_key_id?: number | null;
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
  agent?: {
    id: string;
    name: string;
    slug?: string;
    status?: string;
  };
  project?: {
    id: string;
    name: string;
    status?: string;
  };
};
