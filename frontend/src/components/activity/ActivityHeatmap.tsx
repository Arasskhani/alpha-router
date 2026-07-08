import { useMemo } from "react";
import { dateKeyForTimezone, formatHeatmapTooltip, formatHeatmapValue } from "./formatters";
import type { ActivityInsights, HeatmapDay, HeatmapMetric, TimezoneMode } from "./types";

type Props = {
  insights: ActivityInsights;
  metric: HeatmapMetric;
  timezone: TimezoneMode;
  onMetricChange: (m: HeatmapMetric) => void;
};

function metricValue(day: HeatmapDay, metric: HeatmapMetric) {
  if (metric === "tokens") return day.tokens;
  if (metric === "spend") return day.spend;
  return day.requests;
}

function metricLevel(day: HeatmapDay, metric: HeatmapMetric) {
  if (metric === "tokens") return day.level_tokens;
  if (metric === "spend") return day.level_spend;
  return day.level_requests;
}

function monthLabel(date: Date) {
  return date.toLocaleString("en-US", { month: "short" });
}

export default function ActivityHeatmap({ insights, metric, timezone, onMetricChange }: Props) {
  const days = insights.heatmap.days;

  const weeks = useMemo(() => {
    if (!days.length) return [] as { month?: string; cells: (HeatmapDay | null)[] }[];

    const first = new Date(`${days[0].date}T12:00:00`);
    const last = new Date(`${days[days.length - 1].date}T12:00:00`);
    const start = new Date(first);
    start.setDate(start.getDate() - start.getDay());

    const byDate = new Map(days.map((d) => [d.date, d]));
    const grid: { month?: string; cells: (HeatmapDay | null)[] }[] = [];
    const cursor = new Date(start);
    let lastMonth = "";

    while (cursor <= last || cursor.getDay() !== 0) {
      const weekCells: (HeatmapDay | null)[] = [];
      let month: string | undefined;
      for (let i = 0; i < 7; i += 1) {
        const key = dateKeyForTimezone(cursor, timezone);
        weekCells.push(byDate.get(key) ?? null);
        const m = monthLabel(cursor);
        if (m !== lastMonth) {
          month = m;
          lastMonth = m;
        }
        cursor.setDate(cursor.getDate() + 1);
      }
      grid.push({ month, cells: weekCells });
      if (cursor > last && cursor.getDay() === 0) break;
    }
    return grid;
  }, [days, timezone]);

  const sideStats = useMemo(() => {
    const s = insights.usage_stats[metric];
    return {
      streak: s.streak_days,
      avgDay: formatHeatmapValue(metric, s.avg_day),
      avgWeek: formatHeatmapValue(metric, s.avg_week),
      total: formatHeatmapValue(metric, s.total),
    };
  }, [insights.usage_stats, metric]);

  return (
    <article className={`activity-heatmap card activity-heatmap--${metric}`}>
      <header className="activity-heatmap__head">
        <h3>Usage</h3>
        <div className="activity-segmented" role="tablist" aria-label="Heatmap metric">
          {(["requests", "tokens", "spend"] as HeatmapMetric[]).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={metric === m}
              className={metric === m ? "activity-segmented__btn activity-segmented__btn--active" : "activity-segmented__btn"}
              onClick={() => onMetricChange(m)}
            >
              {m === "requests" ? "Requests" : m === "tokens" ? "Tokens" : "Spend"}
            </button>
          ))}
        </div>
      </header>
      <div className="activity-heatmap__body">
        <div className="activity-heatmap__grid-wrap">
          <div className="activity-heatmap__chart-row">
            <div className="activity-heatmap__dow" aria-hidden>
              <span>M</span>
              <span />
              <span>W</span>
              <span />
              <span>F</span>
              <span />
              <span />
            </div>
            {weeks.length > 0 ? (
              <div className="activity-heatmap__grid">
                {weeks.map((week, wi) => (
                <div key={wi} className="activity-heatmap__week">
                  {week.month ? (
                    <span className="activity-heatmap__month">{week.month}</span>
                  ) : (
                    <span className="activity-heatmap__month" />
                  )}
                  <div className="activity-heatmap__cells">
                    {week.cells.map((cell, di) => (
                      <span
                        key={`${wi}-${di}`}
                        className={`activity-heatmap__cell activity-heatmap__cell--l${cell ? metricLevel(cell, metric) : 0}`}
                        title={
                          cell
                            ? formatHeatmapTooltip(metric, metricValue(cell, metric), cell.date)
                            : undefined
                        }
                      />
                    ))}
                  </div>
                </div>
                ))}
              </div>
            ) : (
              <p className="activity-heatmap__empty muted">No usage history for this range yet.</p>
            )}
          </div>
          <div className="activity-heatmap__legend-scale">
            <span>Less</span>
            <span className="activity-heatmap__cell activity-heatmap__cell--l0" />
            <span className="activity-heatmap__cell activity-heatmap__cell--l1" />
            <span className="activity-heatmap__cell activity-heatmap__cell--l2" />
            <span className="activity-heatmap__cell activity-heatmap__cell--l3" />
            <span className="activity-heatmap__cell activity-heatmap__cell--l4" />
            <span>More</span>
          </div>
        </div>
        <aside className="activity-heatmap__stats">
          <div>
            <p className="activity-heatmap__stat-value">{sideStats.streak}</p>
            <p className="activity-heatmap__stat-label">Streak</p>
          </div>
          <div>
            <p className="activity-heatmap__stat-value">{sideStats.avgDay}</p>
            <p className="activity-heatmap__stat-label">Avg Day</p>
          </div>
          <div>
            <p className="activity-heatmap__stat-value">{sideStats.avgWeek}</p>
            <p className="activity-heatmap__stat-label">Avg Week</p>
          </div>
          <div>
            <p className="activity-heatmap__stat-value">{sideStats.total}</p>
            <p className="activity-heatmap__stat-label">Total</p>
          </div>
        </aside>
      </div>
    </article>
  );
}
