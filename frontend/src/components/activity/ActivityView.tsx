import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { MY_USAGE_AND_ACTIVITY_LABEL, USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
import Modal from "../Modal";
import ActivityGroupByMenu from "./ActivityGroupByMenu";
import ActivityGuardrails from "./ActivityGuardrails";
import ActivityHeatmap from "./ActivityHeatmap";
import ActivityMetricCard from "./ActivityMetricCard";
import ActivityPeriodMenu, { parseActivityPeriod } from "./ActivityPeriodMenu";
import ActivityTopModels from "./ActivityTopModels";
import { formatRequests, groupByLabel, periodLabel, promptsCardPeriodLabel } from "./formatters";
import { resolveInsights, resolvePrompts } from "./insights";
import type {
  ActivityPayload,
  GroupBy,
  HeatmapMetric,
  MetricKind,
  PromptsPeriod,
  TimezoneMode,
} from "./types";

type Scope = "service" | "user" | "mine" | "api_key" | "connection" | "group";

type Props = {
  scope: Scope;
  userId?: number;
  groupId?: number;
  apiKeyId?: number;
  connectionId?: number;
  title?: string;
  backLink?: { to: string; label: string };
  /** Rendered below all activity cards (e.g. API key change log). */
  footer?: ReactNode;
  toolbarExtra?: ReactNode;
  onDataLoaded?: (data: ActivityPayload) => void;
};

type ExpandedCard = { kind: MetricKind; title: string } | null;

function token() {
  return localStorage.getItem("nitro_token");
}

export default function ActivityView({
  scope,
  userId,
  groupId,
  apiKeyId,
  connectionId,
  title,
  backLink,
  footer,
  toolbarExtra,
  onDataLoaded,
}: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<ActivityPayload | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expanded, setExpanded] = useState<ExpandedCard>(null);
  const [heatmapMetric, setHeatmapMetric] = useState<HeatmapMetric>("spend");
  const [exportingPdf, setExportingPdf] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  const exportMode = searchParams.get("exportMode") === "pdf";

  const validPeriod = parseActivityPeriod(searchParams.get("period"));
  const promptsPeriod = (searchParams.get("promptsPeriod") as PromptsPeriod) || "week";
  const validPromptsPeriod: PromptsPeriod =
    promptsPeriod === "day" || promptsPeriod === "month" ? promptsPeriod : "week";
  const groupBy = (searchParams.get("groupBy") as GroupBy) || "model";
  const validGroupBy: GroupBy = groupBy === "app" || groupBy === "user" ? groupBy : "model";
  const timezone = (searchParams.get("tz") as TimezoneMode) || "local";
  const validTz: TimezoneMode = timezone === "utc" ? "utc" : "local";
  const modelFilter = searchParams.get("model") || "";
  const userFilter = searchParams.get("user") || "";
  const appFilter = searchParams.get("app") || "";
  const statusFilter = searchParams.get("status") || "";

  const isPersonalScope = scope === "user" || scope === "mine" || scope === "group";

  function buildQuery() {
    const q = new URLSearchParams({
      period: validPeriod,
      prompts_period: validPromptsPeriod,
      timezone: validTz,
    });
    if (scope === "service") {
      q.set("group_by", validGroupBy);
      if (modelFilter) q.set("model_id", modelFilter);
      if (userFilter) q.set("username", userFilter);
      if (appFilter) q.set("app", appFilter);
      if (statusFilter === "success" || statusFilter === "fail") q.set("response_status", statusFilter);
    } else if (modelFilter) {
      q.set("model_id", modelFilter);
    }
    return q.toString();
  }

  function patchParams(patch: Record<string, string | undefined>) {
    const next: Record<string, string> = { period: validPeriod, promptsPeriod: validPromptsPeriod, tz: validTz };
    if (scope === "service") next.groupBy = validGroupBy;
    const model = patch.model !== undefined ? patch.model : modelFilter;
    const user = patch.user !== undefined ? patch.user : userFilter;
    const app = patch.app !== undefined ? patch.app : appFilter;
    const status = patch.status !== undefined ? patch.status : statusFilter;
    const periodVal = patch.period ?? validPeriod;
    const promptsPeriodVal = patch.promptsPeriod ?? validPromptsPeriod;
    const groupVal = patch.groupBy ?? validGroupBy;
    const tzVal = patch.tz ?? validTz;
    next.period = periodVal;
    next.promptsPeriod = promptsPeriodVal;
    next.tz = tzVal;
    if (scope === "service") next.groupBy = groupVal;
    if (model) next.model = model;
    if (scope === "service") {
      if (user) next.user = user;
      if (app) next.app = app;
      if (status) next.status = status;
    }
    setSearchParams(next, { replace: true });
  }

  const fetchPath =
    scope === "service"
      ? `/api/admin/dashboard/activity?${buildQuery()}`
      : scope === "mine"
        ? `/api/user/activity?${buildQuery()}`
        : scope === "api_key"
          ? `/api/admin/api-keys/${apiKeyId}/activity?${buildQuery()}`
          : scope === "connection"
            ? `/api/admin/connections/${connectionId}/activity?${buildQuery()}`
            : scope === "group"
              ? `/api/admin/groups/${groupId}/activity?${buildQuery()}`
              : `/api/admin/users/${userId}/activity?${buildQuery()}`;

  useEffect(() => {
    if (!exportMode) return;
    document.body.classList.add("activity-pdf-export");
    return () => document.body.classList.remove("activity-pdf-export");
  }, [exportMode]);

  useEffect(() => {
    if (scope === "user" && !Number.isFinite(userId)) {
      setErr("Invalid user");
      setLoading(false);
      return;
    }
    if (scope === "api_key" && !Number.isFinite(apiKeyId)) {
      setErr("Invalid API key");
      setLoading(false);
      return;
    }
    if (scope === "connection" && !Number.isFinite(connectionId)) {
      setErr("Invalid connection");
      setLoading(false);
      return;
    }
    if (scope === "group" && !Number.isFinite(groupId)) {
      setErr("Invalid group");
      setLoading(false);
      return;
    }
    setLoading(true);
    setErr("");
    api<ActivityPayload>(fetchPath)
      .then((payload) => {
        setData(payload);
        onDataLoaded?.(payload);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [fetchPath, scope, userId, groupId, apiKeyId, connectionId, onDataLoaded]);

  useEffect(() => {
    if (!settingsOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [settingsOpen]);

  const subtitle = useMemo(() => {
    if (scope === "mine") {
      return <>Your personal usage on NITRO</>;
    }
    if (scope === "user" && data?.user) {
      const name = data.user.display_name?.trim() || data.user.username;
      return (
        <>
          Usage for <strong>{name}</strong>
        </>
      );
    }
    if (scope === "api_key" && data?.api_key) {
      return (
        <>
          Gateway key <strong>{data.api_key.name}</strong>
        </>
      );
    }
    if (scope === "connection" && data?.connection) {
      const c = data.connection;
      return (
        <>
          Provider connection <strong>{c.name}</strong>
          <span className="muted-text">
            {" "}
            · {c.provider_type}
            {c.base_url ? ` · ${c.base_url}` : ""}
            {!c.is_active ? " · disabled" : ""}
          </span>
        </>
      );
    }
    if (scope === "group" && data?.group) {
      const g = data.group;
      return (
        <>
          Combined usage for group <strong>{g.name}</strong>
          {typeof g.member_count === "number" && (
            <span className="muted-text"> · {g.member_count} member(s)</span>
          )}
        </>
      );
    }
    return <>Service usage across models on NITRO</>;
  }, [scope, data]);

  const activeFilterCount = [modelFilter, userFilter, appFilter, statusFilter].filter(Boolean).length;

  async function exportActivity(fmt: "csv" | "pdf") {
    const q = buildQuery();
    const path =
      scope === "service"
        ? `/api/admin/dashboard/activity/export?${q}&format=${fmt}`
        : scope === "mine"
          ? `/api/user/activity/export?${q}&format=${fmt}`
          : scope === "group"
            ? `/api/admin/groups/${groupId}/activity/export?${q}&format=${fmt}`
            : scope === "connection"
              ? `/api/admin/connections/${connectionId}/activity/export?${q}&format=${fmt}`
              : scope === "api_key"
                ? `/api/admin/api-keys/${apiKeyId}/activity/export?${q}&format=${fmt}`
                : `/api/admin/users/${userId}/activity/export?${q}&format=${fmt}`;

    if (fmt === "pdf") {
      if (!data) {
        setErr("Nothing to export yet. Wait for activity data to load.");
        return;
      }
      setSettingsOpen(false);
      setExportingPdf(true);
      setErr("");
    }

    const res = await fetch(path, {
      headers: { Authorization: `Bearer ${token()}` },
    });

    if (fmt === "pdf") setExportingPdf(false);

    if (!res.ok) {
      let msg = `Export failed (${res.status})`;
      try {
        const body = await res.json();
        if (body?.detail) msg = String(body.detail);
      } catch {
        /* ignore */
      }
      setErr(msg);
      return;
    }

    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition");
    const match = cd?.match(/filename="([^"]+)"/);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = match?.[1] ?? (fmt === "csv" ? "nitro-activity-logs.xlsx" : "nitro-activity.pdf");
    a.click();
    URL.revokeObjectURL(a.href);
    setSettingsOpen(false);
  }

  const modelOptions = data?.available_models?.length
    ? data.available_models
    : modelFilter
      ? [{ key: modelFilter, label: modelFilter }]
      : [];

  const flagged = data?.guardrails?.redacted_flagged ?? data?.guardrails?.cached_prompts ?? 0;
  const insights = data ? resolveInsights(data) : null;
  const prompts = data ? resolvePrompts(data, validPromptsPeriod) : null;

  return (
    <div className="activity-page">
      <header className="activity-page-header">
        <div>
          <h1>
            {title ??
              (scope === "mine"
                ? MY_USAGE_AND_ACTIVITY_LABEL
                : scope === "user" ||
                    scope === "group" ||
                    scope === "connection" ||
                    scope === "api_key"
                  ? USAGE_AND_ACTIVITY_LABEL
                  : "Activity")}
          </h1>
          <p className="activity-subtitle">
            {subtitle}
            {data ? ` · ${periodLabel(data.period)}` : ""}
            {scope === "service" && data ? ` · ${groupByLabel(data.group_by)}` : ""}
            {validTz === "utc" ? " · UTC" : " · Local time"}
          </p>
        </div>
        <div className="activity-toolbar">
          {backLink ? (
            <Link to={backLink.to} className="btn btn-ghost activity-back">
              {backLink.label}
            </Link>
          ) : null}
          {toolbarExtra}
          {scope === "service" ? (
            <button
              type="button"
              className={`activity-icon-btn${filtersOpen ? " activity-icon-btn--active" : ""}${activeFilterCount ? " activity-icon-btn--badge" : ""}`}
              onClick={() => setFiltersOpen((v) => !v)}
              aria-label="Filters"
              title="Filters"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 6h16M7 12h10M10 18h4" />
              </svg>
            </button>
          ) : null}
          <ActivityPeriodMenu value={validPeriod} onChange={(p) => patchParams({ period: p })} />
          {scope === "service" ? (
            <ActivityGroupByMenu value={validGroupBy} onChange={(g) => patchParams({ groupBy: g })} />
          ) : isPersonalScope ? (
            <select
              className="activity-select"
              value={modelFilter}
              onChange={(e) => patchParams({ model: e.target.value })}
              aria-label="Filter by model"
            >
              <option value="">All models</option>
              {modelOptions.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          ) : null}
          <div className="activity-menu-wrap" ref={settingsRef}>
            <button
              type="button"
              className={`activity-icon-btn${settingsOpen ? " activity-icon-btn--active" : ""}`}
              onClick={() => setSettingsOpen((v) => !v)}
              aria-label="Export and timezone"
              title="Export"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
            {settingsOpen ? (
              <div className="activity-menu-panel card">
                <p className="activity-menu-heading">Timezone</p>
                <button
                  type="button"
                  className={`activity-menu-item${validTz === "local" ? " activity-menu-item--active" : ""}`}
                  onClick={() => {
                    patchParams({ tz: "local" });
                    setSettingsOpen(false);
                  }}
                >
                  Local {validTz === "local" ? "✓" : ""}
                </button>
                <button
                  type="button"
                  className={`activity-menu-item${validTz === "utc" ? " activity-menu-item--active" : ""}`}
                  onClick={() => {
                    patchParams({ tz: "utc" });
                    setSettingsOpen(false);
                  }}
                >
                  UTC {validTz === "utc" ? "✓" : ""}
                </button>
                <p className="activity-menu-heading">Export to…</p>
                <button type="button" className="activity-menu-item" onClick={() => void exportActivity("csv")}>
                  CSV
                </button>
                <button type="button" className="activity-menu-item" onClick={() => void exportActivity("pdf")} disabled={exportingPdf || loading || !data}>
                  {exportingPdf ? "Generating PDF…" : "PDF"}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      {scope === "service" && filtersOpen ? (
        <div className="activity-filters card">
          <label>
            Model
            <select value={modelFilter} onChange={(e) => patchParams({ model: e.target.value })}>
              <option value="">All models</option>
              {(data?.available_models || []).map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            User
            <select value={userFilter} onChange={(e) => patchParams({ user: e.target.value })}>
              <option value="">All users</option>
              {(data?.available_users || []).map((u) => (
                <option key={u.key} value={u.key}>
                  {u.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            App
            <select value={appFilter} onChange={(e) => patchParams({ app: e.target.value })}>
              <option value="">All apps</option>
              {(data?.available_apps || []).map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Response status
            <select value={statusFilter} onChange={(e) => patchParams({ status: e.target.value })}>
              <option value="">All</option>
              <option value="success">Success</option>
              <option value="fail">Fail</option>
            </select>
          </label>
          <button type="button" className="btn btn-ghost" onClick={() => patchParams({ model: "", user: "", app: "", status: "" })}>
            Clear filters
          </button>
        </div>
      ) : null}

      {exportingPdf ? <p className="muted activity-export-status">Generating PDF from dashboard…</p> : null}
      {err ? <p className="error">{err}</p> : null}
      {loading ? <p className="muted">Loading activity…</p> : null}

      {!loading && data && insights && prompts && (
        <>
          <div className="activity-metrics-grid">
            <ActivityMetricCard
              title="Spend"
              total={data.totals.spend}
              kind="spend"
              segments={data.models}
              chartRows={data.chart}
              onExpand={() => setExpanded({ kind: "spend", title: "Spend" })}
            />
            <ActivityMetricCard
              title="Requests"
              total={data.totals.requests}
              kind="requests"
              segments={data.models}
              chartRows={data.chart}
              onExpand={() => setExpanded({ kind: "requests", title: "Requests" })}
            />
            <ActivityMetricCard
              title="Tokens"
              total={data.totals.tokens}
              kind="tokens"
              segments={data.models}
              chartRows={data.chart}
              onExpand={() => setExpanded({ kind: "tokens", title: "Tokens" })}
            />
          </div>

          <ActivityGuardrails blocked={data.guardrails?.blocked_requests ?? 0} flagged={flagged} />

          <hr className="activity-section-divider" />

          <ActivityMetricCard
            className="activity-metric-card--hero"
            title="Prompts"
            total={prompts.total}
            kind="requests"
            segments={prompts.models}
            chartRows={prompts.chart}
            chartHeight={160}
            changePct={prompts.change_pct}
            streakDays={prompts.streak_days}
            hideLegend
            headerExtra={
              <select
                className="activity-select activity-select--sm"
                value={validPromptsPeriod}
                onChange={(e) => patchParams({ promptsPeriod: e.target.value })}
                aria-label="Prompts time range"
              >
                <option value="day">{promptsCardPeriodLabel("day")}</option>
                <option value="week">{promptsCardPeriodLabel("week")}</option>
                <option value="month">{promptsCardPeriodLabel("month")}</option>
              </select>
            }
            footerLeft={{ label: "Longest Streak", value: `${prompts.streak_days} days` }}
            footerRight={{
              label: prompts.period_footer_label,
              value: `${formatRequests(prompts.period_prompts)} prompts`,
            }}
            onExpand={() => setExpanded({ kind: "requests", title: "Prompts" })}
          />

          <div className="activity-row-split">
            <ActivityMetricCard
              title="Tokens"
              total={data.totals.tokens}
              kind="tokens"
              segments={data.models}
              chartRows={data.chart}
              chartHeight={160}
              changePct={insights.change_pct.tokens}
              totalInHeader
              hideLegend
              onExpand={() => setExpanded({ kind: "tokens", title: "Tokens" })}
            />
            <ActivityTopModels
              models={data.top_models?.length ? data.top_models : data.models}
              showExplore={scope === "service"}
            />
          </div>

          <ActivityHeatmap
            insights={insights}
            metric={heatmapMetric}
            timezone={validTz}
            onMetricChange={setHeatmapMetric}
          />
        </>
      )}

      {!loading && !err && data && (!insights || !prompts) ? (
        <p className="muted">Usage data loaded but charts could not be rendered. Try refreshing the page.</p>
      ) : null}

      {!loading && !err && !data ? (
        <p className="muted">No usage data for this period.</p>
      ) : null}

      {footer ? (
        <>
          <hr className="activity-section-divider" />
          {footer}
        </>
      ) : null}

      <Modal open={!!expanded} title={expanded?.title ?? ""} onClose={() => setExpanded(null)}>
        {expanded && data ? (
          <ActivityMetricCard
            title={expanded.title}
            total={expanded.title === "Prompts" && prompts ? prompts.total : data.totals[expanded.kind]}
            kind={expanded.kind}
            segments={expanded.title === "Prompts" && prompts ? prompts.models : data.models}
            chartRows={expanded.title === "Prompts" && prompts ? prompts.chart : data.chart}
            chartHeight={280}
          />
        ) : null}
      </Modal>
    </div>
  );
}
