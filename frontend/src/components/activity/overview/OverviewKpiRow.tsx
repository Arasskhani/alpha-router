import { useMemo } from "react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { formatRequests, formatSpend, formatTokens } from "../formatters";
import type { ActivityOverview, OverviewKpi } from "../types";

type KpiKey = keyof ActivityOverview["kpis"];

const KPI_META: { key: KpiKey; title: string; format: (v: number) => string; note?: string }[] = [
  { key: "spend", title: "Total spend", format: formatSpend },
  { key: "requests", title: "Requests", format: formatRequests },
  { key: "tokens", title: "Token volume", format: formatTokens },
  {
    key: "cache_hit_rate",
    title: "Cache hit rate",
    format: (v) => `${v.toFixed(1)}%`,
  },
  {
    key: "blended_per_1m",
    title: "Blended $/1M",
    format: (v) => `$${v.toFixed(2)}`,
  },
  {
    key: "memory_spend",
    title: "Memory",
    format: formatSpend,
    // The only card here for money nobody asked to spend. Without the note it
    // reads as a charge, and the budget bar below will not agree with it.
    note: "Not charged to your plan",
  },
];

type Props = {
  kpis: ActivityOverview["kpis"];
};

function OverviewKpiCard({
  title,
  format,
  kpi,
  note,
}: {
  title: string;
  format: (v: number) => string;
  kpi: OverviewKpi;
  note?: string;
}) {
  const change = kpi.change_pct;
  const down = change != null && change < 0;
  const up = change != null && change > 0;
  const sparkColor = down ? "#ef4444" : up ? "#22c55e" : "var(--muted)";
  const chartData = useMemo(
    () => kpi.sparkline.map((v, i) => ({ i, v })),
    [kpi.sparkline],
  );

  return (
    <article className="overview-kpi-card card">
      <p className="overview-kpi-card__title">{title}</p>
      <div className="overview-kpi-card__body">
        <div className="overview-kpi-card__main">
          <p className="overview-kpi-card__value">{format(kpi.value)}</p>
          {change != null ? (
            <p className={`overview-kpi-card__change${down ? " is-down" : up ? " is-up" : ""}`}>
              {down ? "↓" : up ? "↑" : "·"} {Math.abs(change).toFixed(1)}%
            </p>
          ) : (
            <p className="overview-kpi-card__change muted-text">—</p>
          )}
          <p className="overview-kpi-card__vs muted-text">vs prev period</p>
          {note ? <p className="overview-kpi-card__note muted-text">{note}</p> : null}
        </div>
        <div className="overview-kpi-card__spark">
          <ResponsiveContainer width="100%" height={44}>
            <LineChart data={chartData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Line
                type="monotone"
                dataKey="v"
                stroke={sparkColor}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </article>
  );
}

export default function OverviewKpiRow({ kpis }: Props) {
  return (
    <div className="overview-kpi-row">
      {KPI_META.map((meta) => (
        <OverviewKpiCard
          key={meta.key}
          title={meta.title}
          format={meta.format}
          kpi={kpis[meta.key]}
          note={meta.note}
        />
      ))}
    </div>
  );
}
