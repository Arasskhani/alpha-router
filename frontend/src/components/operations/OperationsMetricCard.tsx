import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type OpsSegment = {
  key: string;
  label: string;
  color: string;
  value: number;
};

type Props = {
  title: string;
  total: number;
  unit?: string;
  segments: OpsSegment[];
  chartRows: Record<string, string | number>[];
  formatValue?: (v: number) => string;
  chartFormatValue?: (v: number) => string;
  totalLabel?: string;
  chartHeight?: number;
  changePct?: number | null;
  footer?: { label: string; value: string; secondary?: { label: string; value: string } };
};

function defaultFormat(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

export default function OperationsMetricCard({
  title,
  total,
  unit = "",
  segments,
  chartRows,
  formatValue = defaultFormat,
  chartFormatValue,
  totalLabel: totalLabelOverride,
  chartHeight = 140,
  changePct = null,
  footer,
}: Props) {
  const data = useMemo(
    () =>
      chartRows.map((row) => {
        const point: Record<string, string | number> = { label: String(row.label ?? "") };
        for (const s of segments) {
          point[s.key] = Number(row[s.key] ?? 0);
        }
        return point;
      }),
    [chartRows, segments],
  );

  const breakdown = useMemo(
    () => [...segments].filter((s) => s.value > 0).sort((a, b) => b.value - a.value),
    [segments],
  );

  const totalLabel = totalLabelOverride ?? `${formatValue(total)}${unit}`;
  const axisFormat = chartFormatValue ?? formatValue;
  const changeClass =
    changePct == null ? "" : changePct < 0 ? " activity-change-badge--down" : changePct > 0 ? " activity-change-badge--up" : "";

  return (
    <article className="activity-metric-card card">
      <header className="activity-metric-card__head">
        <div className="activity-metric-card__title-row">
          <h3>{title}</h3>
          {changePct != null ? (
            <span className={`activity-change-badge${changeClass}`} title="vs previous 24h">
              {changePct > 0 ? "+" : ""}
              {changePct}%
            </span>
          ) : null}
        </div>
        <span className="activity-metric-card__total activity-metric-card__total--header">{totalLabel}</span>
      </header>
      <div className="activity-metric-card__chart" style={{ minHeight: chartHeight }}>
        <ResponsiveContainer width="100%" height={chartHeight}>
          <BarChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }} barCategoryGap="12%">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 9 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 9 }} width={40} tickFormatter={(v) => axisFormat(Number(v))} />
            <Tooltip
              formatter={(value: number, name: string) => {
                const seg = segments.find((m) => m.key === name);
                return [axisFormat(value), seg?.label ?? name];
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
      <ul className="activity-metric-card__legend">
        {breakdown.map((s) => (
          <li key={s.key}>
            <span className="activity-legend-dot" style={{ background: s.color }} aria-hidden />
            <span className="activity-legend-label">{s.label}</span>
            <span className="activity-legend-value">{formatValue(s.value)}</span>
          </li>
        ))}
        {breakdown.length === 0 ? <li className="activity-legend-empty">No samples yet — use Check Now</li> : null}
      </ul>
      {footer ? (
        <footer className="activity-metric-card__footer">
          <div className="activity-metric-card__footer-stat">
            <span className="activity-metric-card__footer-label">{footer.label}</span>
            <span className="activity-metric-card__footer-value">{footer.value}</span>
          </div>
          {footer.secondary ? (
            <div className="activity-metric-card__footer-stat activity-metric-card__footer-stat--end">
              <span className="activity-metric-card__footer-label">{footer.secondary.label}</span>
              <span className="activity-metric-card__footer-value">{footer.secondary.value}</span>
            </div>
          ) : null}
        </footer>
      ) : null}
    </article>
  );
}
