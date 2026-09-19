import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, authFetch } from "../../api";
import { MY_USAGE_AND_ACTIVITY_LABEL, USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
import ActivityGroupByMenu from "./ActivityGroupByMenu";
import ActivityFilterMenu from "./ActivityFilterMenu";
import { activityScopeConfig, type ActivityScope } from "./activityScope";
import ActivityPeriodMenu, { parseActivityPeriod } from "./ActivityPeriodMenu";
import ActivityTimezoneChip from "./ActivityTimezoneChip";
import ActivityExplorePanel from "./overview/explore/ActivityExplorePanel";
import { DEFAULT_EXPLORE_CONTROLS, explorePresetFromFocus } from "./overview/explore/explorePresets";
import ActivityOverviewPanel from "./overview/ActivityOverviewPanel";
import ActivityTabs from "./overview/ActivityTabs";
import ActivityTrendsPanel from "./overview/ActivityTrendsPanel";
import { groupByLabel, periodLabel } from "./formatters";
import { resolveInsights } from "./insights";
import type {
  ActivityPayload,
  ActivityTab,
  ExploreChartType,
  ExploreControls,
  ExploreGroup,
  ExploreMetric,
  ExploreRankBy,
  ExploreRollup,
  ExploreTopMode,
  GroupBy,
  HeatmapMetric,
  OverviewFocus,
  PromptsPeriod,
  TimezoneMode,
} from "./types";

const OVERVIEW_FOCUSES = new Set<OverviewFocus>([
  "users",
  "apps",
  "usage_by_model",
  "request_volume",
  "token_breakdown",
  "prompt_caching",
  "trends_models",
  "trends_users",
  "trends_api_keys",
  "trends_apps",
]);

function parseActivityTab(raw: string | null): ActivityTab {
  if (raw === "trends" || raw === "explore") return raw;
  return "overview";
}

function parseOverviewFocus(raw: string | null): OverviewFocus | null {
  if (raw && OVERVIEW_FOCUSES.has(raw as OverviewFocus)) return raw as OverviewFocus;
  return null;
}

const EXPLORE_METRICS = new Set<ExploreMetric>([
  "request_count",
  "total_usage",
  "tokens_total",
  "tokens_prompt",
  "tokens_completion",
  "cached_tokens",
  "avg_latency",
  "p50_latency",
]);
const EXPLORE_GROUPS = new Set<ExploreGroup>(["none", "model", "api_key", "provider", "app", "user"]);
const EXPLORE_ROLLUPS = new Set<ExploreRollup>(["total", "hourly", "daily", "weekly", "monthly"]);
const EXPLORE_TOP_NS = new Set([5, 10, 15, 30]);

function parseExploreControls(params: URLSearchParams): ExploreControls {
  const metricRaw = params.get("exploreMetric") as ExploreMetric | null;
  const groupRaw = params.get("exploreGroup") as ExploreGroup | null;
  const subgroupRaw = params.get("exploreSubgroup") as ExploreGroup | null;
  const rollupRaw = params.get("exploreRollup") as ExploreRollup | null;
  const topModeRaw = params.get("exploreTopMode") as ExploreTopMode | null;
  const topNRaw = Number(params.get("exploreTopN") || DEFAULT_EXPLORE_CONTROLS.topN);
  const rankByRaw = params.get("exploreRankBy") as ExploreRankBy | null;
  const chartTypeRaw = params.get("exploreChartType") as ExploreChartType | null;
  const showOtherRaw = params.get("exploreShowOther");
  const cumulativeRaw = params.get("exploreCumulative");
  return {
    metric: metricRaw && EXPLORE_METRICS.has(metricRaw) ? metricRaw : DEFAULT_EXPLORE_CONTROLS.metric,
    group: groupRaw && EXPLORE_GROUPS.has(groupRaw) ? groupRaw : DEFAULT_EXPLORE_CONTROLS.group,
    subgroup: subgroupRaw && EXPLORE_GROUPS.has(subgroupRaw) && subgroupRaw !== "none" ? subgroupRaw : "",
    rollup: rollupRaw && EXPLORE_ROLLUPS.has(rollupRaw) ? rollupRaw : DEFAULT_EXPLORE_CONTROLS.rollup,
    topMode: topModeRaw === "bottom" ? "bottom" : "top",
    topN: EXPLORE_TOP_NS.has(topNRaw) ? topNRaw : DEFAULT_EXPLORE_CONTROLS.topN,
    rankBy: rankByRaw === "requests" ? "requests" : "metric",
    showOther: showOtherRaw === null ? true : showOtherRaw !== "0",
    cumulative: cumulativeRaw === "1",
    chartType:
      chartTypeRaw === "line" || chartTypeRaw === "area" || chartTypeRaw === "bar"
        ? chartTypeRaw
        : DEFAULT_EXPLORE_CONTROLS.chartType,
  };
}

type Props = {
  scope: ActivityScope;
  userId?: number;
  groupId?: number;
  apiKeyId?: number;
  connectionId?: number;
  agentId?: string;
  projectId?: string;
  title?: string;
  backLink?: { to: string; label: string };
  /** Rendered below all activity cards (e.g. API key change log). */
  footer?: ReactNode;
  toolbarExtra?: ReactNode;
  onDataLoaded?: (data: ActivityPayload) => void;
};

export default function ActivityView({
  scope,
  userId,
  groupId,
  apiKeyId,
  connectionId,
  agentId,
  projectId,
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
  const [settingsOpen, setSettingsOpen] = useState(false);
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
  const apiKeyFilter = searchParams.get("apiKey") || "";
  const activityTab = parseActivityTab(searchParams.get("tab"));
  const exploreFocus = parseOverviewFocus(searchParams.get("focus"));
  const exploreControls = parseExploreControls(searchParams);
  const cfg = activityScopeConfig(scope);
  const allowUserFilter = cfg.filterKeys.includes("user");
  const allowAppFilter = cfg.filterKeys.includes("app");
  const allowStatusFilter = cfg.filterKeys.includes("status");
  const allowApiKeyFilter = cfg.filterKeys.includes("apiKey");

  function buildQuery() {
    const q = new URLSearchParams({
      period: validPeriod,
      prompts_period: validPromptsPeriod,
      timezone: validTz,
    });
    if (cfg.showGroupBy) q.set("group_by", validGroupBy);
    if (modelFilter) q.set("model_id", modelFilter);
    if (allowUserFilter && userFilter) q.set("username", userFilter);
    if (allowAppFilter && appFilter) q.set("app", appFilter);
    if (allowStatusFilter && (statusFilter === "success" || statusFilter === "fail")) {
      q.set("response_status", statusFilter);
    }
    if (allowApiKeyFilter && apiKeyFilter) q.set("api_key_id", apiKeyFilter);
    q.set("explore_metric", exploreControls.metric);
    q.set("explore_group", exploreControls.group);
    if (exploreControls.subgroup) q.set("explore_subgroup", exploreControls.subgroup);
    q.set("explore_rollup", exploreControls.rollup);
    q.set("explore_top_mode", exploreControls.topMode);
    q.set("explore_top_n", String(exploreControls.topN));
    q.set("explore_rank_by", exploreControls.rankBy);
    q.set("explore_show_other", exploreControls.showOther ? "true" : "false");
    q.set("explore_cumulative", exploreControls.cumulative ? "true" : "false");
    q.set("explore_chart_type", exploreControls.chartType);
    return q.toString();
  }

  function writeExploreToParams(next: Record<string, string>, controls: ExploreControls) {
    next.exploreMetric = controls.metric;
    next.exploreGroup = controls.group;
    if (controls.subgroup) next.exploreSubgroup = controls.subgroup;
    next.exploreRollup = controls.rollup;
    next.exploreTopMode = controls.topMode;
    next.exploreTopN = String(controls.topN);
    next.exploreRankBy = controls.rankBy;
    next.exploreShowOther = controls.showOther ? "1" : "0";
    next.exploreCumulative = controls.cumulative ? "1" : "0";
    next.exploreChartType = controls.chartType;
  }

  function patchParams(patch: Record<string, string | undefined>) {
    const next: Record<string, string> = { period: validPeriod, promptsPeriod: validPromptsPeriod, tz: validTz };
    if (cfg.showGroupBy) next.groupBy = validGroupBy;
    const model = patch.model !== undefined ? patch.model : modelFilter;
    const user = patch.user !== undefined ? patch.user : userFilter;
    const app = patch.app !== undefined ? patch.app : appFilter;
    const status = patch.status !== undefined ? patch.status : statusFilter;
    const apiKey = patch.apiKey !== undefined ? patch.apiKey : apiKeyFilter;
    const periodVal = patch.period ?? validPeriod;
    const promptsPeriodVal = patch.promptsPeriod ?? validPromptsPeriod;
    const groupVal = patch.groupBy ?? validGroupBy;
    const tzVal = patch.tz ?? validTz;
    const tabVal = patch.tab !== undefined ? patch.tab : activityTab;
    const focusVal = patch.focus !== undefined ? patch.focus : exploreFocus ?? "";
    next.period = periodVal;
    next.promptsPeriod = promptsPeriodVal;
    next.tz = tzVal;
    if (cfg.showGroupBy) next.groupBy = groupVal;
    if (model) next.model = model;
    if (allowUserFilter && user) next.user = user;
    if (allowAppFilter && app) next.app = app;
    if (allowStatusFilter && status) next.status = status;
    if (allowApiKeyFilter && apiKey) next.apiKey = apiKey;
    writeExploreToParams(next, {
      metric: (patch.exploreMetric as ExploreMetric | undefined) ?? exploreControls.metric,
      group: (patch.exploreGroup as ExploreGroup | undefined) ?? exploreControls.group,
      subgroup: (patch.exploreSubgroup as ExploreGroup | "" | undefined) ?? exploreControls.subgroup,
      rollup: (patch.exploreRollup as ExploreRollup | undefined) ?? exploreControls.rollup,
      topMode: (patch.exploreTopMode as ExploreTopMode | undefined) ?? exploreControls.topMode,
      topN: patch.exploreTopN !== undefined ? Number(patch.exploreTopN) : exploreControls.topN,
      rankBy: (patch.exploreRankBy as ExploreRankBy | undefined) ?? exploreControls.rankBy,
      showOther:
        patch.exploreShowOther !== undefined ? patch.exploreShowOther !== "0" : exploreControls.showOther,
      cumulative:
        patch.exploreCumulative !== undefined
          ? patch.exploreCumulative === "1"
          : exploreControls.cumulative,
      chartType: (patch.exploreChartType as ExploreChartType | undefined) ?? exploreControls.chartType,
    });
    if (patch.exploreSubgroup === "") delete next.exploreSubgroup;
    if (tabVal) next.tab = tabVal;
    if (focusVal) next.focus = focusVal;
    if (patch.tab === "overview") delete next.focus;
    if (patch.tab && patch.tab !== "explore" && patch.focus === undefined) {
      delete next.focus;
    }
    setSearchParams(next, { replace: true });
  }

  function goExplore(focus: OverviewFocus) {
    const preset = explorePresetFromFocus(focus) ?? {};
    patchParams({
      tab: "explore",
      focus,
      exploreMetric: preset.metric ?? DEFAULT_EXPLORE_CONTROLS.metric,
      exploreGroup: preset.group ?? DEFAULT_EXPLORE_CONTROLS.group,
      exploreSubgroup: "",
    });
  }

  function patchExploreControls(patch: Partial<ExploreControls>, clearFocus = false) {
    const next: Record<string, string | undefined> = {};
    if (patch.metric !== undefined) next.exploreMetric = patch.metric;
    if (patch.group !== undefined) next.exploreGroup = patch.group;
    if (patch.subgroup !== undefined) next.exploreSubgroup = patch.subgroup || "";
    if (patch.rollup !== undefined) next.exploreRollup = patch.rollup;
    if (patch.topMode !== undefined) next.exploreTopMode = patch.topMode;
    if (patch.topN !== undefined) next.exploreTopN = String(patch.topN);
    if (patch.rankBy !== undefined) next.exploreRankBy = patch.rankBy;
    if (patch.showOther !== undefined) next.exploreShowOther = patch.showOther ? "1" : "0";
    if (patch.cumulative !== undefined) next.exploreCumulative = patch.cumulative ? "1" : "0";
    if (patch.chartType !== undefined) next.exploreChartType = patch.chartType;
    if (clearFocus) next.focus = "";
    patchParams(next);
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
              : scope === "agent"
                ? `/api/admin/agents/${encodeURIComponent(agentId || "")}/activity?${buildQuery()}`
                : scope === "project"
                  ? `/api/projects/${encodeURIComponent(projectId || "")}/activity?${buildQuery()}`
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
    if (scope === "agent" && !agentId) {
      setErr("Invalid Agent");
      setLoading(false);
      return;
    }
    if (scope === "project" && !projectId) {
      setErr("Invalid project");
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
  }, [fetchPath, scope, userId, groupId, apiKeyId, connectionId, agentId, projectId, onDataLoaded]);

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
      return <>Your personal usage on Alpharouter</>;
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
    if (scope === "agent" && data?.agent) {
      return (
        <>
          Usage for Agent <strong>{data.agent.name}</strong>
        </>
      );
    }
    if (scope === "project" && data?.project) {
      return (
        <>
          Usage for project <strong>{data.project.name}</strong>
        </>
      );
    }
    return <>Service usage across models on Alpharouter</>;
  }, [scope, data]);

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
                : scope === "agent"
                  ? `/api/admin/agents/${encodeURIComponent(agentId || "")}/activity/export?${q}&format=${fmt}`
                  : scope === "project"
                    ? `/api/projects/${encodeURIComponent(projectId || "")}/activity/export?${q}&format=${fmt}`
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

    const res = await authFetch(path);

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
    a.download = match?.[1] ?? (fmt === "csv" ? "alpha-router-activity-logs.xlsx" : "alpha-router-activity.pdf");
    a.click();
    URL.revokeObjectURL(a.href);
    setSettingsOpen(false);
  }

  const insights = data ? resolveInsights(data) : null;

  return (
    <div className="activity-page" data-activity-ready={!loading && data ? "1" : undefined}>
      <header className="activity-page-header">
        <div>
          <h1>
            {title ??
              (scope === "mine"
                ? MY_USAGE_AND_ACTIVITY_LABEL
                : scope === "user" ||
                    scope === "group" ||
                    scope === "connection" ||
                    scope === "api_key" ||
                    scope === "agent" ||
                    scope === "project"
                  ? USAGE_AND_ACTIVITY_LABEL
                  : "Activity")}
          </h1>
          <p className="activity-subtitle">
            {subtitle}
            {data ? ` · ${periodLabel(data.period)}` : ""}
            {cfg.showGroupBy && data ? ` · ${groupByLabel(data.group_by)}` : ""}
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
          <ActivityTimezoneChip value={validTz} onChange={(tz) => patchParams({ tz })} />
          {cfg.filterKeys.length ? (
            <ActivityFilterMenu
              model={modelFilter}
              user={userFilter}
              app={appFilter}
              status={statusFilter}
              apiKey={apiKeyFilter}
              models={data?.available_models ?? []}
              users={data?.available_users ?? []}
              apps={data?.available_apps ?? []}
              apiKeys={data?.available_api_keys ?? []}
              visibleKeys={cfg.filterKeys}
              onChange={(patch) => patchParams(patch)}
              onClear={() =>
                patchParams({
                  model: "",
                  user: allowUserFilter ? "" : undefined,
                  app: allowAppFilter ? "" : undefined,
                  status: allowStatusFilter ? "" : undefined,
                  apiKey: allowApiKeyFilter ? "" : undefined,
                })
              }
            />
          ) : null}
          <ActivityPeriodMenu value={validPeriod} onChange={(p) => patchParams({ period: p })} />
          {cfg.showGroupBy ? (
            <ActivityGroupByMenu value={validGroupBy} onChange={(g) => patchParams({ groupBy: g })} />
          ) : null}
          <div className="activity-menu-wrap" ref={settingsRef}>
            <button
              type="button"
              className={`activity-icon-btn${settingsOpen ? " activity-icon-btn--active" : ""}`}
              onClick={() => setSettingsOpen((v) => !v)}
              aria-label="Export"
              title="Export"
            >
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
            {settingsOpen ? (
              <div className="activity-menu-panel card">
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

      {exportingPdf ? <p className="muted activity-export-status">Generating PDF from dashboard…</p> : null}
      {err ? <p className="error" role="alert">{err}</p> : null}
      {loading ? <p className="muted">Loading activity…</p> : null}

      {!exportMode ? (
        <ActivityTabs
          value={activityTab}
          onChange={(tab) => patchParams({ tab, focus: tab === "explore" ? exploreFocus ?? undefined : "" })}
        />
      ) : null}
      {!loading && data && (exportMode || activityTab === "overview") ? (
        data.overview ? (
          <ActivityOverviewPanel
            overview={data.overview}
            insights={insights}
            timezone={validTz}
            heatmapMetric={heatmapMetric}
            onHeatmapMetricChange={setHeatmapMetric}
            hideUsers={cfg.hideOverviewUsers}
            onExplore={goExplore}
          />
        ) : (
          <p className="muted">Overview data is unavailable for this period.</p>
        )
      ) : null}
      {!loading && data && (exportMode || activityTab === "trends") ? (
        data.trends ? (
          <ActivityTrendsPanel
            trends={data.trends}
            hideUsers={cfg.hideTrendsUsers}
            hideApiKeys={cfg.hideTrendsApiKeys}
            onExplore={goExplore}
          />
        ) : (
          <p className="muted">Trends data is unavailable for this period.</p>
        )
      ) : null}
      {!loading && data && (exportMode || activityTab === "explore") ? (
        data.explore ? (
          <ActivityExplorePanel
            explore={data.explore}
            controls={exploreControls}
            hiddenGroups={cfg.hiddenExploreGroups}
            onControlsChange={patchExploreControls}
            onDownloadPdf={() => void exportActivity("pdf")}
          />
        ) : (
          <p className="muted">Explore data is unavailable for this period.</p>
        )
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
    </div>
  );
}
