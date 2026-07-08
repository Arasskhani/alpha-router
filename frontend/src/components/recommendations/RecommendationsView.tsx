import { useMemo } from "react";
import OperationsMetricCard from "../operations/OperationsMetricCard";

export type RecommendationSegment = {
  key: string;
  label: string;
  color: string;
  value: number;
  model_id: string;
  reason: string;
  fit_score: number;
  value_index: number;
  savings_pct: number | null;
  blended_cost_per_1k: number;
};

export type RecommendationCard = {
  id: string;
  title: string;
  total: number;
  unit: string;
  total_format: string;
  segments: RecommendationSegment[];
  chart: Record<string, string | number>[];
};

export type RecommendationsPayload = {
  period_days: number;
  period?: {
    mode: "preset" | "custom";
    days: number;
    from: string | null;
    to: string | null;
  };
  message: string;
  profile: {
    primary_model: string | null;
    primary_model_label: string | null;
    dominant_kind: string;
    avg_prompt_tokens: number;
    avg_completion_tokens: number;
    total_requests: number;
    top_models: string[];
  };
  quality: RecommendationCard;
  value: RecommendationCard;
};

function formatMatch(v: number) {
  return `${v.toFixed(v % 1 === 0 ? 0 : 1)}%`;
}

function formatValueIndex(v: number) {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}K`;
  return v.toFixed(1);
}

function formatSpend(v: number) {
  if (v >= 10) return `$${v.toFixed(1)}`;
  if (v >= 1) return `$${v.toFixed(2)}`;
  return `$${v.toFixed(3)}`;
}

function formatTokens(v: number) {
  if (v >= 1_000) return `${(v / 1000).toFixed(1)}K`;
  return String(Math.round(v));
}

function formatSavingsPct(v: number) {
  if (v >= 100) return "100%";
  if (v >= 10) return `${Math.round(v)}%`;
  return `${v.toFixed(1)}%`;
}

type CardProps = {
  card: RecommendationCard;
  variant: "quality" | "value";
};

function RecommendationCardView({ card, variant }: CardProps) {
  const segments = useMemo(
    () =>
      card.segments.map((s) => ({
        key: s.key,
        label: s.label,
        color: s.color,
        value:
          variant === "quality"
            ? s.fit_score
            : s.savings_pct != null
              ? s.savings_pct
              : s.value_index,
      })),
    [card.segments, variant],
  );

  const total =
    variant === "quality"
      ? card.total
      : Math.max(...card.segments.map((s) => s.savings_pct ?? 0), 0);

  const totalDisplay =
    variant === "quality" ? formatMatch(total) : `${formatSavingsPct(total).replace("%", "")}% savings`;

  return (
    <div className="recommendations-card-wrap">
      <OperationsMetricCard
        title={card.title}
        total={total}
        unit={variant === "quality" ? "" : ""}
        segments={segments}
        chartRows={card.chart}
        formatValue={variant === "quality" ? (v) => formatMatch(v) : (v) => formatSavingsPct(v)}
        chartFormatValue={variant === "quality" ? formatTokens : formatSpend}
        chartHeight={160}
        totalLabel={totalDisplay}
        footer={
          card.segments[0]
            ? {
                label: "Top pick",
                value: card.segments[0].label,
                secondary: {
                  label: variant === "quality" ? "Why" : "Est. savings",
                  value:
                    variant === "quality"
                      ? card.segments[0].reason
                      : card.segments[0].savings_pct != null
                        ? `${Math.round(card.segments[0].savings_pct)}% vs main model`
                        : `${formatSpend(card.segments[0].blended_cost_per_1k)} / 1K`,
                },
              }
            : undefined
        }
      />
      <ul className="recommendations-reasons">
        {card.segments.map((s) => (
          <li key={s.model_id}>
            <span className="activity-legend-dot" style={{ background: s.color }} aria-hidden />
            <span className="recommendations-reasons__model">{s.label}</span>
            <span className="recommendations-reasons__text">{s.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Props = {
  data: RecommendationsPayload;
  loading?: boolean;
};

function periodSummary(data: RecommendationsPayload): string {
  if (data.period?.mode === "custom" && data.period.from && data.period.to) {
    return `${data.period.from} → ${data.period.to} (${data.period_days} days)`;
  }
  return `${data.period_days} days`;
}

export default function RecommendationsView({ data, loading = false }: Props) {
  return (
    <div className={`recommendations-view${loading ? " recommendations-view--loading" : ""}`}>
      <p className="muted-text recommendations-page__intro">{data.message}</p>

      {data.profile.total_requests > 0 ? (
        <p className="recommendations-profile muted-text">
          Profile ({periodSummary(data)}): {data.profile.dominant_kind} · ~
          {data.profile.avg_prompt_tokens.toLocaleString()} prompt /{" "}
          {data.profile.avg_completion_tokens.toLocaleString()} completion tokens ·{" "}
          {data.profile.total_requests.toLocaleString()} requests
          {data.profile.primary_model_label ? ` · main model: ${data.profile.primary_model_label}` : ""}
        </p>
      ) : (
        <p className="recommendations-profile muted-text">
          No usage in {periodSummary(data)} — picks are based on enabled catalog models.
        </p>
      )}

      <div className="recommendations-metrics-grid">
        <RecommendationCardView card={data.quality} variant="quality" />
        <RecommendationCardView card={data.value} variant="value" />
      </div>

      <p className="recommendations-disclaimer muted-text">
        Match scores use model tier, context length, and your usage pattern. They are guidance, not measured output
        quality. Value picks favor similar capability at lower estimated cost for your token mix.
      </p>
    </div>
  );
}

export { formatMatch, formatValueIndex, formatSpend };
