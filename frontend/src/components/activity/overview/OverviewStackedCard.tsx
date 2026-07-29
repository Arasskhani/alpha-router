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
import ModelName from "../../ModelName";
import { formatRequests, formatSpend, formatTokens } from "../formatters";
import type { OverviewFocus, OverviewStackedChart } from "../types";
import OverviewExploreLink from "./OverviewExploreLink";

type ValueKind = "spend" | "requests" | "tokens" | "raw";

type Props = {
  title: string;
  focus: OverviewFocus;
  data: OverviewStackedChart;
  /** Prefix on chart keys, e.g. spend_ / requests_. Empty when keys are bare (prompt, cached). */
  valuePrefix?: string;
  valueKind?: ValueKind;
  onExplore: (focus: OverviewFocus) => void;
  chartHeight?: number;
};

function formatAxis(kind: ValueKind, v: number) {
  if (kind === "spend") return formatSpend(v);
  if (kind === "requests") return formatRequests(v);
  if (kind === "tokens") return formatTokens(v);
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(0)}M`;
  if (v >= 1000) return `${(v / 1000).toFixed(0)}K`;
  return String(Math.round(v));
}

export default function OverviewStackedCard({
  title,
  focus,
  data,
  valuePrefix = "",
  valueKind = "raw",
  onExplore,
  chartHeight = 220,
}: Props) {
  const rows = useMemo(() => {
    return data.chart.map((row) => {
      const point: Record<string, string | number> = { label: String(row.label ?? "") };
      for (const s of data.segments) {
        const key = valuePrefix ? `${valuePrefix}${s.key}` : s.key;
        point[s.key] = Number(row[key] ?? 0);
      }
      return point;
    });
  }, [data.chart, data.segments, valuePrefix]);

  return (
    <article className="overview-chart-card card">
      <header className="overview-card-head">
        <h3>{title}</h3>
        <OverviewExploreLink focus={focus} onExplore={onExplore} />
      </header>
      <div className="overview-chart-card__chart">
        <ResponsiveContainer width="100%" height={chartHeight}>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical horizontal />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--muted)" }}
              axisLine={false}
              tickLine={false}
              width={44}
              tickFormatter={(v) => formatAxis(valueKind, Number(v))}
            />
            <Tooltip
              formatter={(value: number, name: string) => {
                const seg = data.segments.find((s) => s.key === name);
                return [formatAxis(valueKind, value), seg?.label ?? name];
              }}
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            {data.segments.map((s) => (
              <Bar key={s.key} dataKey={s.key} stackId="a" fill={s.color} maxBarSize={18} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="overview-chart-card__legend">
        {data.segments.map((s) => (
          <li key={s.key}>
            <span className="overview-chart-card__dot" style={{ background: s.color }} />
            <ModelName
              modelId={s.key}
              label={s.label}
              showIcon={
                (focus === "usage_by_model" ||
                  focus === "request_volume" ||
                  focus === "trends_models") &&
                s.key !== "__others__" &&
                !s.key.startsWith("__")
              }
              size={14}
            />
          </li>
        ))}
      </ul>
    </article>
  );
}
