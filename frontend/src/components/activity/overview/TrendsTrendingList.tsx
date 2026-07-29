import { useEffect, useMemo, useRef, useState } from "react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import ModelName from "../../ModelName";
import ModelProviderIcon from "../../ModelProviderIcon";
import type { OverviewFocus, TrendsListItem, TrendsMetric } from "../types";
import OverviewExploreLink from "./OverviewExploreLink";

const METRIC_OPTIONS: { value: TrendsMetric; label: string }[] = [
  { value: "spend", label: "Spend" },
  { value: "requests", label: "Requests" },
  { value: "tokens", label: "Tokens" },
];

type Props = {
  itemsByMetric: Record<TrendsMetric, TrendsListItem[]>;
  focus: OverviewFocus;
  onExplore: (focus: OverviewFocus) => void;
  metric: TrendsMetric;
};

function formatChange(item: TrendsListItem): string {
  if (item.is_new) return "New";
  if (item.change_pct == null) return "—";
  const abs = Math.abs(item.change_pct);
  if (abs > 999) return ">999%";
  return `${abs.toFixed(0)}%`;
}

function Spark({ values, down }: { values: number[]; down: boolean }) {
  const data = useMemo(() => values.map((v, i) => ({ i, v })), [values]);
  const color = down ? "#ef4444" : "#16a34a";
  return (
    <div className="trends-spark">
      <ResponsiveContainer width="100%" height={28}>
        <LineChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TrendsMetricSelect({
  metric,
  onMetricChange,
}: {
  metric: TrendsMetric;
  onMetricChange: (metric: TrendsMetric) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const label = METRIC_OPTIONS.find((o) => o.value === metric)?.label ?? "Spend";

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="trends-metric-menu" ref={ref}>
      <button
        type="button"
        className={`trends-metric-trigger${open ? " is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Trending metric"
      >
        <span>{label}</span>
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden>
          <path
            d="M4 6l4 4 4-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open ? (
        <div className="trends-metric-panel card" role="listbox">
          {METRIC_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="option"
              aria-selected={metric === opt.value}
              className={`activity-menu-item${metric === opt.value ? " activity-menu-item--active" : ""}`}
              onClick={() => {
                onMetricChange(opt.value);
                setOpen(false);
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function TrendsTrendingList({
  itemsByMetric,
  focus,
  onExplore,
  metric,
}: Props) {
  const items = itemsByMetric[metric] ?? [];

  return (
    <article className="trends-trending card">
      <header className="overview-card-head">
        <h3>Trending</h3>
        <OverviewExploreLink focus={focus} onExplore={onExplore} />
      </header>
      <ul className="trends-trending__list">
        {items.map((item) => {
          const down = !item.is_new && (item.change_pct ?? 0) < 0;
          const up = item.is_new || (item.change_pct ?? 0) > 0;
          return (
            <li key={item.key}>
              {focus === "trends_models" ? (
                <span className="trends-trending__avatar trends-trending__avatar--provider" style={{ color: item.color }}>
                  <ModelProviderIcon modelId={item.key} provider={item.provider} size={18} />
                </span>
              ) : (
                <span className="trends-trending__avatar" style={{ background: `${item.color}22`, color: item.color }}>
                  {item.initials}
                </span>
              )}
              <span className="trends-trending__meta">
                <span className="trends-trending__name">
                  {focus === "trends_models" ? (
                    <ModelName
                      modelId={item.key}
                      label={item.label}
                      provider={item.provider}
                      showIcon={false}
                      size={14}
                    />
                  ) : (
                    item.label
                  )}
                </span>
                {item.subtitle || (focus === "trends_models" && item.provider) ? (
                  <span className="trends-trending__sub muted-text">
                    {focus === "trends_models" && item.provider
                      ? `by ${item.provider}`
                      : item.subtitle}
                  </span>
                ) : null}
              </span>
              <Spark values={item.sparkline} down={down} />
              <span
                className={`trends-trending__change${down ? " is-down" : ""}${up ? " is-up" : ""}`}
              >
                {down ? "↓" : up ? "↑" : "·"} {formatChange(item)}
              </span>
            </li>
          );
        })}
        {items.length === 0 ? (
          <li className="trends-trending__empty muted-text">No trending entities in this period</li>
        ) : null}
      </ul>
    </article>
  );
}
