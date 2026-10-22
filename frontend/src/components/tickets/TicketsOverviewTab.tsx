import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";

import ActivityPeriodMenu from "../activity/ActivityPeriodMenu";
import ActivityTimezoneChip from "../activity/ActivityTimezoneChip";
import { periodLabel } from "../activity/formatters";
import OverviewExploreLink from "../activity/overview/OverviewExploreLink";
import OverviewStackedCard from "../activity/overview/OverviewStackedCard";
import OperationsMetricCard from "../operations/OperationsMetricCard";
import TicketFilterMenu from "./TicketFilterMenu";
import { PRIORITY_LABELS, TICKETS_BASE, ticketsRequest, type OverviewKpi, type TicketsOverview } from "../../lib/tickets";
import {
  OVERVIEW_FILTER_KEYS,
  downloadCsv,
  formatDuration,
  formatDurationShort,
  initials,
  kpiTone,
  overviewFilterSummary,
  overviewQuery,
  parseOverviewPeriod,
  readOverviewFilters,
  type KpiDirection,
  type OverviewFilters,
} from "../../lib/ticketsAdmin";

type KpiKey = keyof TicketsOverview["kpis"];

const KPI_META: { key: KpiKey; title: string; better: KpiDirection; format: (v: number) => string }[] = [
  { key: "opened", title: "Tickets opened", better: null, format: String },
  { key: "resolved", title: "Resolved", better: "up", format: String },
  { key: "open_now", title: "Open now", better: "down", format: String },
  { key: "first_reply_minutes", title: "Median first reply", better: "down", format: (v) => formatDurationShort(v) },
  { key: "resolution_hours", title: "Median resolution", better: "down", format: (v) => formatDurationShort(v * 60) },
  { key: "auto_closed", title: "Auto-closed", better: null, format: String },
];

const TONE_COLOR = { good: "#22c55e", bad: "#ef4444", flat: "var(--muted)" } as const;

function kpiNote(key: KpiKey, kpis: TicketsOverview["kpis"]): string {
  if (key === "open_now") {
    const n = kpis.open_now.unanswered ?? 0;
    return `${n} ${n === 1 ? "waits" : "wait"} for a first answer`;
  }
  if (key === "first_reply_minutes") return "automatic reply not counted";
  if (key === "auto_closed" && kpis.auto_closed.share_pct != null) {
    return `${Math.round(kpis.auto_closed.share_pct)}% of closed tickets`;
  }
  return "";
}

function KpiCard({
  title,
  kpi,
  better,
  format,
  note,
}: {
  title: string;
  kpi: OverviewKpi;
  better: KpiDirection;
  format: (v: number) => string;
  note: string;
}) {
  const change = kpi.change_pct;
  const tone = kpiTone(change, better);
  const data = useMemo(() => (kpi.sparkline ?? []).map((v, i) => ({ i, v })), [kpi.sparkline]);
  return (
    <article className="overview-kpi-card card" data-tone={tone}>
      <p className="overview-kpi-card__title">{title}</p>
      <div className="overview-kpi-card__body">
        <div className="overview-kpi-card__main">
          <p className="overview-kpi-card__value">{kpi.value == null ? "—" : format(kpi.value)}</p>
          {change != null ? (
            <p
              className={`overview-kpi-card__change${tone === "good" ? " is-up" : tone === "bad" ? " is-down" : " tickets-kpi-flat"}`}
            >
              {change < 0 ? "↓" : change > 0 ? "↑" : "·"} {Math.abs(change).toFixed(1)}%
            </p>
          ) : (
            <p className="overview-kpi-card__change muted-text">—</p>
          )}
          <p className="overview-kpi-card__vs muted-text">vs prev period</p>
          {note ? <p className="overview-kpi-card__note muted-text">{note}</p> : null}
        </div>
        <div className="overview-kpi-card__spark">
          {data.length > 1 ? (
            <ResponsiveContainer width="100%" height={44}>
              <LineChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                <YAxis hide domain={["dataMin", "dataMax"]} />
                <Line type="monotone" dataKey="v" stroke={TONE_COLOR[tone]} strokeWidth={1.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : null}
        </div>
      </div>
    </article>
  );
}

type ListItem = {
  key: string;
  avatar: string;
  name: string;
  sub?: string;
  value: string;
  staff?: boolean;
  unassigned?: boolean;
  onOpen?: () => void;
};

function TopList({
  title,
  items,
  empty,
  onExplore,
}: {
  title: string;
  items: ListItem[];
  empty: string;
  onExplore: () => void;
}) {
  return (
    <article className="overview-top-list card">
      <header className="overview-card-head">
        <h3>{title}</h3>
        <OverviewExploreLink focus="users" onExplore={onExplore} />
      </header>
      <ul className="overview-top-list__items">
        {items.map((item, idx) => (
          <li key={item.key} className={item.unassigned ? "tickets-ov-unassigned" : undefined}>
            <span className="overview-top-list__rank">{item.unassigned ? "–" : idx + 1}</span>
            <span className={`overview-top-list__avatar${item.staff ? " tickets-ov-avatar--staff" : ""}`} aria-hidden>
              {item.avatar}
            </span>
            <span className="overview-top-list__meta">
              {item.onOpen ? (
                <button type="button" className="overview-top-list__name tickets-ov-name" onClick={item.onOpen}>
                  {item.name}
                </button>
              ) : (
                <span className="overview-top-list__name">{item.name}</span>
              )}
              {item.sub ? <span className="tickets-ov-sub">{item.sub}</span> : null}
            </span>
            <span className="overview-top-list__value">{item.value}</span>
          </li>
        ))}
        {items.length === 0 ? <li className="overview-top-list__empty muted-text">{empty}</li> : null}
      </ul>
    </article>
  );
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

/** Ticket flow and support workload for a period: aggregates only, never ticket text. */
export default function TicketsOverviewTab() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const period = parseOverviewPeriod(params.get("period"));
  const timezone = params.get("tz") === "utc" ? "utc" : "local";
  const filters = readOverviewFilters(params);
  const query = overviewQuery(period, timezone, filters);

  const [data, setData] = useState<{ query: string; overview: TicketsOverview } | null>(null);
  const [error, setError] = useState("");
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    ticketsRequest<TicketsOverview>(`${TICKETS_BASE}/overview?${query}`)
      .then((overview) => {
        if (cancelled) return;
        setData({ query, overview });
        setError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  useEffect(() => {
    if (!exportOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) setExportOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [exportOpen]);

  function patch(next: Record<string, string>) {
    const out = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value) out.set(key, value);
      else out.delete(key);
    }
    setParams(out, { replace: true });
  }

  /** The queue, with these filters (and any extra), in the view that fits. */
  function explore(view: string, extra: Partial<OverviewFilters> = {}) {
    const q = new URLSearchParams({ view });
    const merged = { ...filters, ...extra };
    for (const key of OVERVIEW_FILTER_KEYS) if (merged[key]) q.set(key, merged[key]);
    navigate(`/admin/tickets/list?${q.toString()}`);
  }

  async function exportCsv() {
    setExportOpen(false);
    try {
      await downloadCsv(`${TICKETS_BASE}/overview.csv?${query}`, "tickets-overview.csv");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const overview = data?.overview ?? null;
  const loading = !data || data.query !== query;
  const options = overview?.options ?? { departments: [], assignees: [], categories: [] };
  const summary = overviewFilterSummary(filters, options.assignees);
  const label = overview && !loading ? overview.period_label || periodLabel(period) : periodLabel(period);
  const k = overview?.kpis;
  const empty =
    overview != null &&
    (k?.opened.value ?? 0) === 0 &&
    (k?.open_now.value ?? 0) === 0 &&
    (k?.resolved.value ?? 0) === 0 &&
    (overview.ended.total ?? 0) === 0;

  return (
    <div className="tickets-overview" data-ready={loading ? undefined : "1"}>
      <div className="activity-page-header tickets-ov-head">
        <p className="activity-subtitle">
          Ticket flow and support workload · {label}
          {summary ? ` · ${summary}` : ""}
          {timezone === "utc" ? " · UTC" : " · Local time"}
        </p>
        <div className="activity-toolbar">
          <ActivityTimezoneChip value={timezone} onChange={(tz) => patch({ tz: tz === "utc" ? "utc" : "" })} />
          <TicketFilterMenu
            value={filters}
            departments={options.departments}
            assignees={options.assignees}
            categories={options.categories}
            onChange={(next) => patch(next as Record<string, string>)}
            onClear={() => patch(Object.fromEntries(OVERVIEW_FILTER_KEYS.map((key) => [key, ""])))}
          />
          <ActivityPeriodMenu value={period} onChange={(p) => patch({ period: p })} />
          <div className="activity-menu-wrap" ref={exportRef}>
            <button
              type="button"
              className={`activity-icon-btn${exportOpen ? " activity-icon-btn--active" : ""}`}
              onClick={() => setExportOpen((v) => !v)}
              aria-label="Export"
              aria-expanded={exportOpen}
              title="Export"
            >
              <svg
                viewBox="0 0 24 24"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
            {exportOpen ? (
              <div className="activity-menu-panel card">
                <p className="activity-menu-heading">Export to…</p>
                <button type="button" className="activity-menu-item" onClick={() => void exportCsv()}>
                  CSV of these numbers
                </button>
                <Link to="/admin/reports" className="activity-menu-item tickets-ov-report-link">
                  Ticket summary report
                </Link>
                <p className="tickets-hint tickets-ov-report-hint">Excel, PDF or a schedule, in Reports.</p>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {!overview ? (
        error ? null : <p className="muted-text">Loading the overview…</p>
      ) : (
        <div className={`tickets-ov-body${loading ? " is-loading" : ""}`} aria-busy={loading}>
          <div className="activity-overview">
            <div className="overview-kpi-row">
              {KPI_META.map((meta) => (
                <KpiCard
                  key={meta.key}
                  title={meta.title}
                  kpi={overview.kpis[meta.key]}
                  better={meta.better}
                  format={meta.format}
                  note={kpiNote(meta.key, overview.kpis)}
                />
              ))}
            </div>

            {empty ? (
              <div className="card tickets-ov-empty">
                <h3>No tickets in this period</h3>
                <p className="muted-text">
                  {summary ? "Nothing matches these filters. Clear them or choose a longer period." : "Choose a longer period to see earlier tickets."}
                </p>
              </div>
            ) : (
              <>
                <div className="overview-lists-row tickets-ov-lists">
                  <TopList
                    title="Top departments"
                    empty="No tickets in this period."
                    onExplore={() => explore("all")}
                    items={overview.top_departments.map((d) => ({
                      key: d.department,
                      avatar: initials(d.department),
                      name: d.department,
                      sub: `${d.still_open} still open${d.urgent_open ? ` · ${d.urgent_open} Urgent` : ""}`,
                      value: plural(d.opened, "ticket", "tickets"),
                      onOpen: () => explore("all", { department: d.department }),
                    }))}
                  />
                  <TopList
                    title="Workload by assignee"
                    empty="Nobody can work tickets yet."
                    onExplore={() => explore("active")}
                    items={[
                      ...overview.workload.filter((w) => w.user_id != null),
                      ...overview.workload.filter((w) => w.user_id == null),
                    ].map((w) => {
                      const unassigned = w.user_id == null;
                      return {
                        key: unassigned ? "none" : String(w.user_id),
                        avatar: unassigned ? "?" : initials(w.name),
                        name: unassigned ? "Unassigned" : w.name,
                        sub: unassigned
                          ? w.oldest_wait_minutes != null
                            ? `oldest waits ${formatDuration(w.oldest_wait_minutes)}`
                            : "nothing waiting"
                          : `${w.role_label} · ${w.resolved} resolved`,
                        value: `${w.open} open`,
                        staff: !unassigned && w.role_label === "Super Admin",
                        unassigned,
                        onOpen: () => explore("active", { assignee: unassigned ? "none" : String(w.user_id) }),
                      };
                    })}
                  />
                  <TopList
                    title="First reply by priority"
                    empty="No first replies in this period."
                    onExplore={() => explore("all")}
                    items={overview.first_reply_by_priority.map((p) => ({
                      key: p.priority,
                      avatar: PRIORITY_LABELS[p.priority]?.[0] ?? "?",
                      name: PRIORITY_LABELS[p.priority] ?? p.priority,
                      sub: plural(p.tickets, "ticket", "tickets"),
                      value: formatDuration(p.median_minutes),
                      onOpen: () => explore("all", { priority: p.priority }),
                    }))}
                  />
                </div>

                <OverviewStackedCard
                  title="Tickets opened by priority"
                  focus="users"
                  data={{ segments: overview.opened_by_priority.segments, chart: overview.opened_by_priority.chart }}
                  valueKind="raw"
                  onExplore={() => explore("all")}
                  chartHeight={230}
                />
              </>
            )}
          </div>

          {empty ? null : (
            <>
              <h3 className="operations-section-title">Flow and backlog</h3>
              <div className="activity-metrics-grid operations-metrics-grid">
                <OperationsMetricCard
                  title="How tickets ended"
                  total={overview.ended.total}
                  unit="closed"
                  segments={overview.ended.segments.map((s) => ({ ...s, value: s.value ?? 0 }))}
                  chartRows={overview.ended.chart}
                  emptyLabel="No ticket ended in this period."
                  footer={{
                    label: "Reopened after resolve",
                    value: `${overview.ended.reopened}${overview.ended.reopened_pct != null ? ` (${Math.round(overview.ended.reopened_pct)}%)` : ""}`,
                  }}
                />
                <OperationsMetricCard
                  title="Backlog by status"
                  total={overview.backlog.total}
                  unit="open now"
                  segments={overview.backlog.segments.map((s) => ({ ...s, value: s.value ?? 0 }))}
                  chartRows={overview.backlog.chart}
                  emptyLabel="Nothing open."
                  footer={{
                    label: "Oldest without a staff reply",
                    value: formatDuration(overview.backlog.oldest_unanswered_minutes),
                  }}
                />
                <OperationsMetricCard
                  title="Tickets by category"
                  total={overview.by_category.total}
                  unit="opened"
                  segments={overview.by_category.segments.map((s) => ({ ...s, value: s.value ?? 0 }))}
                  chartRows={overview.by_category.chart}
                  emptyLabel="No tickets opened in this period."
                  footer={{
                    label: "Most common",
                    value: overview.by_category.most_common
                      ? `${overview.by_category.most_common.label} · ${Math.round(overview.by_category.most_common.pct)}%`
                      : "—",
                  }}
                />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
