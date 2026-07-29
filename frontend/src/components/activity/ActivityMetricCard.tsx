import { ReactNode, useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ModelName from "../ModelName";
import { formatBreakdownValue, formatMetricValue } from "./formatters";
import type { MetricKind, SegmentMeta } from "./types";

type Props = {
  title: string;
  total: number;
  kind: MetricKind;
  segments: SegmentMeta[];
  chartRows: Record<string, string | number>[];
  chartHeight?: number;
  onExpand?: () => void;
  changePct?: number | null;
  streakDays?: number;
  footerLeft?: { label: string; value: string };
  footerRight?: { label: string; value: string };
  hideLegend?: boolean;
  totalInHeader?: boolean;
  headerExtra?: ReactNode;
  className?: string;
};

export default function ActivityMetricCard({
  title,
  total,
  kind,
  segments,
  chartRows,
  chartHeight = 140,
  onExpand,
  changePct,
  streakDays,
  footerLeft,
  footerRight,
  hideLegend = false,
  totalInHeader = false,
  headerExtra,
  className = "",
}: Props) {
  const prefix = `${kind}_`;
  const data = useMemo(
    () =>
      chartRows.map((row) => {
        const point: Record<string, string | number> = { label: String(row.label ?? "") };
        for (const s of segments) {
          point[s.key] = Number(row[`${prefix}${s.key}`] ?? 0);
        }
        return point;
      }),
    [chartRows, segments, prefix],
  );

  const breakdown = useMemo(() => {
    const key = kind;
    return [...segments]
      .map((s) => ({ ...s, value: s[key] as number }))
      .filter((s) => s.value > 0)
      .sort((a, b) => b.value - a.value);
  }, [segments, kind]);

  const changeClass =
    changePct == null ? "" : changePct < 0 ? " activity-change-badge--down" : changePct > 0 ? " activity-change-badge--up" : "";

  return (
    <article className={`activity-metric-card card${className ? ` ${className}` : ""}`}>
      <header className="activity-metric-card__head">
        <div className="activity-metric-card__title-row">
          <h3>{title}</h3>
          {changePct != null ? (
            <span className={`activity-change-badge${changeClass}`}>
              {changePct > 0 ? "+" : ""}
              {changePct}%
            </span>
          ) : null}
        </div>
        <div className="activity-metric-card__head-actions">
          {streakDays != null && streakDays > 0 ? (
            <span className="activity-streak-pill" title="Active-day streak">
              <span aria-hidden>🔥</span> {streakDays} days
            </span>
          ) : null}
          {totalInHeader ? (
            <span className="activity-metric-card__total activity-metric-card__total--header">
              {formatMetricValue(kind, total)}
            </span>
          ) : null}
          {headerExtra}
          {onExpand ? (
          <button type="button" className="activity-expand-btn" onClick={onExpand} aria-label={`Expand ${title}`}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M8 3H3v5M16 3h5v5M16 21h5v-5M8 21H3v-5" />
            </svg>
          </button>
        ) : null}
        </div>
      </header>
      {!totalInHeader ? <p className="activity-metric-card__total">{formatMetricValue(kind, total)}</p> : null}
      <div className="activity-metric-card__chart" style={{ minHeight: chartHeight }}>
        <ResponsiveContainer width="100%" height={chartHeight}>
          <BarChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }} barCategoryGap="12%">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 9 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 9 }} width={36} tickFormatter={(v) => formatMetricValue(kind, Number(v))} />
            <Tooltip
              formatter={(value: number, name: string) => {
                const seg = segments.find((m) => m.key === name);
                return [formatBreakdownValue(kind, value), seg?.label ?? name];
              }}
              labelFormatter={(label) => String(label)}
            />
            {segments.map((s) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                stackId="stack"
                fill={s.color}
                maxBarSize={28}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      {!hideLegend ? (
        <ul className="activity-metric-card__legend">
          {breakdown.map((s) => (
            <li key={s.key}>
              <span className="activity-legend-dot" style={{ background: s.color }} aria-hidden />
              <span className="activity-legend-label">
                <ModelName
                  modelId={s.key}
                  label={s.label}
                  showIcon={s.key !== "__others__" && !s.key.startsWith("__")}
                  size={13}
                />
              </span>
              <span className="activity-legend-value">{formatBreakdownValue(kind, s.value)}</span>
            </li>
          ))}
          {breakdown.length === 0 ? <li className="activity-legend-empty">No usage in this period</li> : null}
        </ul>
      ) : null}
      {footerLeft || footerRight ? (
        <footer className="activity-metric-card__footer">
          {footerLeft ? (
            <div className="activity-metric-card__footer-stat">
              <span className="activity-metric-card__footer-label">{footerLeft.label}</span>
              <span className="activity-metric-card__footer-value">{footerLeft.value}</span>
            </div>
          ) : null}
          {footerRight ? (
            <div className="activity-metric-card__footer-stat activity-metric-card__footer-stat--end">
              <span className="activity-metric-card__footer-label">{footerRight.label}</span>
              <span className="activity-metric-card__footer-value">{footerRight.value}</span>
            </div>
          ) : null}
        </footer>
      ) : null}
    </article>
  );
}
