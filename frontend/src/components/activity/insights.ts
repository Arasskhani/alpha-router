import type {
  ActivityInsights,
  ActivityPayload,
  HeatmapMetric,
  PromptsPeriod,
  UsageMetricStats,
} from "./types";

function periodFooterLabel(period: PromptsPeriod) {
  if (period === "day") return "Today";
  if (period === "week") return "This Week";
  return "This Month";
}

const emptyMetricStats = (): UsageMetricStats => ({
  streak_days: 0,
  avg_day: 0,
  avg_week: 0,
  total: 0,
});

function normalizeUsageStats(
  raw: ActivityPayload["insights"] extends { usage_stats: infer U } ? U : unknown,
): Record<HeatmapMetric, UsageMetricStats> {
  if (raw && typeof raw === "object" && "requests" in raw && "tokens" in raw && "spend" in raw) {
    return raw as Record<HeatmapMetric, UsageMetricStats>;
  }

  const legacy = raw as {
    streak_days?: number;
    avg_day_spend?: number;
    avg_week_spend?: number;
    total_spend?: number;
  } | undefined;

  return {
    requests: emptyMetricStats(),
    tokens: emptyMetricStats(),
    spend: {
      streak_days: legacy?.streak_days ?? 0,
      avg_day: legacy?.avg_day_spend ?? 0,
      avg_week: legacy?.avg_week_spend ?? 0,
      total: legacy?.total_spend ?? 0,
    },
  };
}
export function resolveInsights(data: ActivityPayload): ActivityInsights {
  const base: ActivityInsights = {
    streak_days: 0,
    change_pct: { prompts: null, tokens: null, spend: null },
    period_footer_label:
      data.period === "day" || data.period === "week" || data.period === "month"
        ? periodFooterLabel(data.period)
        : "This Period",
    period_prompts: data.totals.requests,
    heatmap: { days: [] },
    usage_stats: {
      requests: { ...emptyMetricStats(), total: data.totals.requests },
      tokens: { ...emptyMetricStats(), total: data.totals.tokens },
      spend: { ...emptyMetricStats(), total: data.totals.spend },
    },
  };

  const i = data.insights;
  if (!i) return base;

  return {
    streak_days: i.streak_days ?? base.streak_days,
    change_pct: {
      prompts: i.change_pct?.prompts ?? null,
      tokens: i.change_pct?.tokens ?? null,
      spend: i.change_pct?.spend ?? null,
    },
    period_footer_label: i.period_footer_label ?? base.period_footer_label,
    period_prompts: i.period_prompts ?? base.period_prompts,
    heatmap: i.heatmap?.days ? i.heatmap : base.heatmap,
    usage_stats: normalizeUsageStats(i.usage_stats),
  };
}
