import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ModelName from "../../../ModelName";
import { formatRequests, formatSpend, formatTokens } from "../../formatters";
import type { ActivityExplore, ExploreChartType, ExploreControls, ExploreMetric } from "../../types";

type Props = {
  explore: ActivityExplore;
  controls: ExploreControls;
  onChange: (patch: Partial<ExploreControls>, clearFocus?: boolean) => void;
  onDownloadPdf?: (mode: "current" | "summary") => void;
};

function formatAxis(metric: ExploreMetric, v: number) {
  if (metric === "total_usage") return formatSpend(v);
  if (metric === "request_count") return formatRequests(v);
  if (metric === "avg_latency" || metric === "p50_latency") {
    if (v >= 1000) return `${(v / 1000).toFixed(1)}s`;
    return `${Math.round(v)}`;
  }
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `${(v / 1000).toFixed(0)}K`;
  return formatTokens(v);
}

function IconAxes({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden>
      <path d="M3 3v14h14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {children}
    </svg>
  );
}

function IconChartBar() {
  return (
    <IconAxes>
      <rect x="6" y="7" width="2.8" height="8" rx="0.4" fill="currentColor" />
      <rect x="11" y="10" width="2.8" height="5" rx="0.4" fill="currentColor" />
    </IconAxes>
  );
}

function IconChartLine() {
  return (
    <IconAxes>
      <path
        d="M5.5 13.5 L9 7.5 L12 11 L16 6.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </IconAxes>
  );
}

function IconChartPoints() {
  return (
    <IconAxes>
      <circle cx="7" cy="13" r="1.6" fill="currentColor" />
      <circle cx="11" cy="9.5" r="1.6" fill="currentColor" />
      <circle cx="15" cy="6.5" r="1.6" fill="currentColor" />
    </IconAxes>
  );
}

function IconDownload() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M12 4v10" strokeLinecap="round" />
      <path d="M8 11l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 19h14" strokeLinecap="round" />
    </svg>
  );
}

function IconDoc() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M7 3.5h7l4 4V20.5H7z" strokeLinejoin="round" />
      <path d="M14 3.5V8h4.5" strokeLinejoin="round" />
      <path d="M10 12h6M10 15.5h6" strokeLinecap="round" />
    </svg>
  );
}

function IconBookmarkPlus() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
      <path d="M7 4.5h10v15l-5-3.2-5 3.2z" strokeLinejoin="round" />
      <path d="M12 8v5M9.5 10.5h5" strokeLinecap="round" />
    </svg>
  );
}

function IconChevronRight() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M6 3.5 L11 8 L6 12.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const CHART_TYPES: { type: ExploreChartType; label: string; Icon: () => ReactNode }[] = [
  { type: "bar", label: "Bar", Icon: IconChartBar },
  { type: "line", label: "Line", Icon: IconChartLine },
  { type: "area", label: "Points", Icon: IconChartPoints },
];

export default function ExploreChartCard({ explore, controls, onChange, onDownloadPdf }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [pdfOpen, setPdfOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const rows = useMemo(() => {
    return explore.chart.map((row) => {
      const point: Record<string, string | number> = { label: String(row.label ?? "") };
      for (const s of explore.segments) {
        point[s.key] = Number(row[`v_${s.key}`] ?? 0);
      }
      return point;
    });
  }, [explore.chart, explore.segments]);

  useEffect(() => {
    if (!menuOpen) {
      setPdfOpen(false);
      return;
    }
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  function downloadCsv() {
    const headers = ["entity", "min", "max", "avg", "sum", "value", "pct", "requests"];
    const lines = [headers.join(",")];
    for (const row of explore.table) {
      lines.push(
        [
          JSON.stringify(row.label),
          row.min,
          row.max,
          row.avg,
          row.sum,
          row.value,
          row.pct,
          row.requests,
        ].join(",")
      );
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `alpha-router-explore-${explore.metric}-${explore.group}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    setMenuOpen(false);
  }

  const chartHeight = expanded ? 420 : 280;
  const Chart = controls.chartType === "line" ? LineChart : controls.chartType === "area" ? AreaChart : BarChart;

  return (
    <div className="explore-chart-wrap">
      <div className="explore-chart-wrap__toolbar" ref={menuRef}>
        <div className="explore-chart__btn-group">
          <button
            type="button"
            className={`explore-chart__icon-btn${menuOpen ? " is-open" : ""}`}
            aria-label="Chart options"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden>
              <circle cx="12" cy="5" r="1.6" />
              <circle cx="12" cy="12" r="1.6" />
              <circle cx="12" cy="19" r="1.6" />
            </svg>
          </button>
          <button
            type="button"
            className="explore-chart__expand-btn"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? (
              <>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <path d="M9 9L4 4M4 4h5M4 4v5M15 15l5 5M20 20h-5M20 20v-5" strokeLinecap="round" />
                </svg>
                Collapse
              </>
            ) : (
              <>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                  <path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" strokeLinecap="round" />
                </svg>
                Expand
              </>
            )}
          </button>
        </div>

        {menuOpen ? (
          <div className="explore-chart__menu card">
            <div className="explore-chart__menu-section">
              <div className="explore-chart__toggle">
                <span>Show &quot;Other&quot;</span>
                <button
                  aria-label={'Show "Other"'}
                  type="button"
                  role="switch"
                  aria-checked={controls.showOther}
                  className={`explore-switch${controls.showOther ? " is-on" : ""}`}
                  onClick={() => onChange({ showOther: !controls.showOther }, true)}
                >
                  <span className="explore-switch__thumb" />
                </button>
              </div>
              <div className="explore-chart__toggle">
                <span>Cumulative sum</span>
                <button
                  aria-label="Cumulative sum"
                  type="button"
                  role="switch"
                  aria-checked={controls.cumulative}
                  className={`explore-switch${controls.cumulative ? " is-on" : ""}`}
                  onClick={() => onChange({ cumulative: !controls.cumulative }, true)}
                >
                  <span className="explore-switch__thumb" />
                </button>
              </div>
              <div className="explore-chart__type-row">
                <span>Chart type</span>
                <div className="explore-chart__type-group" role="group" aria-label="Chart type">
                  {CHART_TYPES.map(({ type, label, Icon }) => (
                    <button
                      key={type}
                      type="button"
                      title={label}
                      aria-label={label}
                      aria-pressed={controls.chartType === type}
                      className={controls.chartType === type ? "is-active" : ""}
                      onClick={() => onChange({ chartType: type }, true)}
                    >
                      <Icon />
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="explore-chart__menu-section">
              <button type="button" className="explore-chart__menu-item" onClick={downloadCsv}>
                <IconDownload />
                <span>Download CSV</span>
              </button>
              <div className="explore-chart__pdf-wrap">
                <button
                  type="button"
                  className={`explore-chart__menu-item${pdfOpen ? " is-open" : ""}`}
                  onClick={() => setPdfOpen((v) => !v)}
                  aria-expanded={pdfOpen}
                >
                  <IconDoc />
                  <span>Download PDF</span>
                  <span className="explore-chart__menu-chevron">
                    <IconChevronRight />
                  </span>
                </button>
                {pdfOpen ? (
                  <div className="explore-chart__submenu card">
                    <button
                      type="button"
                      className="explore-chart__menu-item"
                      onClick={() => {
                        onDownloadPdf?.("current");
                        setMenuOpen(false);
                      }}
                      disabled={!onDownloadPdf}
                    >
                      Download current view
                    </button>
                    <button
                      type="button"
                      className="explore-chart__menu-item"
                      onClick={() => {
                        onDownloadPdf?.("summary");
                        setMenuOpen(false);
                      }}
                      disabled={!onDownloadPdf}
                    >
                      Download usage summary
                    </button>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="explore-chart__menu-section">
              <button
                type="button"
                className="explore-chart__menu-item is-disabled"
                disabled
                title="Coming soon"
              >
                <IconBookmarkPlus />
                <span>Save current chart</span>
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <article className={`explore-chart card${expanded ? " is-expanded" : ""}`}>
        <div className="explore-chart__plot">
          <ResponsiveContainer width="100%" height={chartHeight}>
            <Chart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical horizontal />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
              <YAxis
                tick={{ fontSize: 11, fill: "var(--muted)" }}
                axisLine={false}
                tickLine={false}
                width={48}
                tickFormatter={(v) => formatAxis(explore.metric, Number(v))}
              />
              <Tooltip
                formatter={(value: number, name: string) => {
                  const seg = explore.segments.find((s) => s.key === name);
                  return [formatAxis(explore.metric, value), seg?.label ?? name];
                }}
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              {controls.chartType === "bar"
                ? explore.segments.map((s) => (
                    <Bar key={s.key} dataKey={s.key} stackId="a" fill={s.color} maxBarSize={18} />
                  ))
                : null}
              {controls.chartType === "line"
                ? explore.segments.map((s) => (
                    <Line
                      key={s.key}
                      type="monotone"
                      dataKey={s.key}
                      stroke={s.color}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  ))
                : null}
              {controls.chartType === "area"
                ? explore.segments.map((s) => (
                    <Area
                      key={s.key}
                      type="monotone"
                      dataKey={s.key}
                      stackId="a"
                      stroke={s.color}
                      fill={s.color}
                      fillOpacity={0.35}
                      isAnimationActive={false}
                    />
                  ))
                : null}
            </Chart>
          </ResponsiveContainer>
        </div>

        <ul className="overview-chart-card__legend explore-chart__legend">
          {explore.segments.map((s) => (
            <li key={s.key}>
              <span className="overview-chart-card__dot" style={{ background: s.color }} />
              <ModelName
                modelId={s.key.includes("›") ? s.key.split("›")[0] : s.key}
                label={s.label}
                showIcon={
                  (explore.group === "model" || explore.group === "provider") &&
                  s.key !== "__others__" &&
                  !s.key.startsWith("__")
                }
                size={14}
              />
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}
