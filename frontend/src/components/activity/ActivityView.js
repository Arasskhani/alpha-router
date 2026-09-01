import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, authFetch } from "../../api";
import { MY_USAGE_AND_ACTIVITY_LABEL, USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
import ActivityGroupByMenu from "./ActivityGroupByMenu";
import ActivityFilterMenu from "./ActivityFilterMenu";
import { activityScopeConfig } from "./activityScope";
import ActivityPeriodMenu, { parseActivityPeriod } from "./ActivityPeriodMenu";
import ActivityTimezoneChip from "./ActivityTimezoneChip";
import ActivityExplorePanel from "./overview/explore/ActivityExplorePanel";
import { DEFAULT_EXPLORE_CONTROLS, explorePresetFromFocus } from "./overview/explore/explorePresets";
import ActivityOverviewPanel from "./overview/ActivityOverviewPanel";
import ActivityTabs from "./overview/ActivityTabs";
import ActivityTrendsPanel from "./overview/ActivityTrendsPanel";
import { groupByLabel, periodLabel } from "./formatters";
import { resolveInsights } from "./insights";
const OVERVIEW_FOCUSES = new Set([
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
function parseActivityTab(raw) {
    if (raw === "trends" || raw === "explore")
        return raw;
    return "overview";
}
function parseOverviewFocus(raw) {
    if (raw && OVERVIEW_FOCUSES.has(raw))
        return raw;
    return null;
}
const EXPLORE_METRICS = new Set([
    "request_count",
    "total_usage",
    "tokens_total",
    "tokens_prompt",
    "tokens_completion",
    "cached_tokens",
    "avg_latency",
    "p50_latency",
]);
const EXPLORE_GROUPS = new Set(["none", "model", "api_key", "provider", "app", "user"]);
const EXPLORE_ROLLUPS = new Set(["total", "hourly", "daily", "weekly", "monthly"]);
const EXPLORE_TOP_NS = new Set([5, 10, 15, 30]);
function parseExploreControls(params) {
    const metricRaw = params.get("exploreMetric");
    const groupRaw = params.get("exploreGroup");
    const subgroupRaw = params.get("exploreSubgroup");
    const rollupRaw = params.get("exploreRollup");
    const topModeRaw = params.get("exploreTopMode");
    const topNRaw = Number(params.get("exploreTopN") || DEFAULT_EXPLORE_CONTROLS.topN);
    const rankByRaw = params.get("exploreRankBy");
    const chartTypeRaw = params.get("exploreChartType");
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
        chartType: chartTypeRaw === "line" || chartTypeRaw === "area" || chartTypeRaw === "bar"
            ? chartTypeRaw
            : DEFAULT_EXPLORE_CONTROLS.chartType,
    };
}
export default function ActivityView({ scope, userId, groupId, apiKeyId, connectionId, agentId, projectId, title, backLink, footer, toolbarExtra, onDataLoaded, }) {
    const [searchParams, setSearchParams] = useSearchParams();
    const [data, setData] = useState(null);
    const [err, setErr] = useState("");
    const [loading, setLoading] = useState(true);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [heatmapMetric, setHeatmapMetric] = useState("spend");
    const [exportingPdf, setExportingPdf] = useState(false);
    const settingsRef = useRef(null);
    const exportMode = searchParams.get("exportMode") === "pdf";
    const validPeriod = parseActivityPeriod(searchParams.get("period"));
    const promptsPeriod = searchParams.get("promptsPeriod") || "week";
    const validPromptsPeriod = promptsPeriod === "day" || promptsPeriod === "month" ? promptsPeriod : "week";
    const groupBy = searchParams.get("groupBy") || "model";
    const validGroupBy = groupBy === "app" || groupBy === "user" ? groupBy : "model";
    const timezone = searchParams.get("tz") || "local";
    const validTz = timezone === "utc" ? "utc" : "local";
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
        if (cfg.showGroupBy)
            q.set("group_by", validGroupBy);
        if (modelFilter)
            q.set("model_id", modelFilter);
        if (allowUserFilter && userFilter)
            q.set("username", userFilter);
        if (allowAppFilter && appFilter)
            q.set("app", appFilter);
        if (allowStatusFilter && (statusFilter === "success" || statusFilter === "fail")) {
            q.set("response_status", statusFilter);
        }
        if (allowApiKeyFilter && apiKeyFilter)
            q.set("api_key_id", apiKeyFilter);
        q.set("explore_metric", exploreControls.metric);
        q.set("explore_group", exploreControls.group);
        if (exploreControls.subgroup)
            q.set("explore_subgroup", exploreControls.subgroup);
        q.set("explore_rollup", exploreControls.rollup);
        q.set("explore_top_mode", exploreControls.topMode);
        q.set("explore_top_n", String(exploreControls.topN));
        q.set("explore_rank_by", exploreControls.rankBy);
        q.set("explore_show_other", exploreControls.showOther ? "true" : "false");
        q.set("explore_cumulative", exploreControls.cumulative ? "true" : "false");
        q.set("explore_chart_type", exploreControls.chartType);
        return q.toString();
    }
    function writeExploreToParams(next, controls) {
        next.exploreMetric = controls.metric;
        next.exploreGroup = controls.group;
        if (controls.subgroup)
            next.exploreSubgroup = controls.subgroup;
        next.exploreRollup = controls.rollup;
        next.exploreTopMode = controls.topMode;
        next.exploreTopN = String(controls.topN);
        next.exploreRankBy = controls.rankBy;
        next.exploreShowOther = controls.showOther ? "1" : "0";
        next.exploreCumulative = controls.cumulative ? "1" : "0";
        next.exploreChartType = controls.chartType;
    }
    function patchParams(patch) {
        const next = { period: validPeriod, promptsPeriod: validPromptsPeriod, tz: validTz };
        if (cfg.showGroupBy)
            next.groupBy = validGroupBy;
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
        if (cfg.showGroupBy)
            next.groupBy = groupVal;
        if (model)
            next.model = model;
        if (allowUserFilter && user)
            next.user = user;
        if (allowAppFilter && app)
            next.app = app;
        if (allowStatusFilter && status)
            next.status = status;
        if (allowApiKeyFilter && apiKey)
            next.apiKey = apiKey;
        writeExploreToParams(next, {
            metric: patch.exploreMetric ?? exploreControls.metric,
            group: patch.exploreGroup ?? exploreControls.group,
            subgroup: patch.exploreSubgroup ?? exploreControls.subgroup,
            rollup: patch.exploreRollup ?? exploreControls.rollup,
            topMode: patch.exploreTopMode ?? exploreControls.topMode,
            topN: patch.exploreTopN !== undefined ? Number(patch.exploreTopN) : exploreControls.topN,
            rankBy: patch.exploreRankBy ?? exploreControls.rankBy,
            showOther: patch.exploreShowOther !== undefined ? patch.exploreShowOther !== "0" : exploreControls.showOther,
            cumulative: patch.exploreCumulative !== undefined
                ? patch.exploreCumulative === "1"
                : exploreControls.cumulative,
            chartType: patch.exploreChartType ?? exploreControls.chartType,
        });
        if (patch.exploreSubgroup === "")
            delete next.exploreSubgroup;
        if (tabVal)
            next.tab = tabVal;
        if (focusVal)
            next.focus = focusVal;
        if (patch.tab === "overview")
            delete next.focus;
        if (patch.tab && patch.tab !== "explore" && patch.focus === undefined) {
            delete next.focus;
        }
        setSearchParams(next, { replace: true });
    }
    function goExplore(focus) {
        const preset = explorePresetFromFocus(focus) ?? {};
        patchParams({
            tab: "explore",
            focus,
            exploreMetric: preset.metric ?? DEFAULT_EXPLORE_CONTROLS.metric,
            exploreGroup: preset.group ?? DEFAULT_EXPLORE_CONTROLS.group,
            exploreSubgroup: "",
        });
    }
    function patchExploreControls(patch, clearFocus = false) {
        const next = {};
        if (patch.metric !== undefined)
            next.exploreMetric = patch.metric;
        if (patch.group !== undefined)
            next.exploreGroup = patch.group;
        if (patch.subgroup !== undefined)
            next.exploreSubgroup = patch.subgroup || "";
        if (patch.rollup !== undefined)
            next.exploreRollup = patch.rollup;
        if (patch.topMode !== undefined)
            next.exploreTopMode = patch.topMode;
        if (patch.topN !== undefined)
            next.exploreTopN = String(patch.topN);
        if (patch.rankBy !== undefined)
            next.exploreRankBy = patch.rankBy;
        if (patch.showOther !== undefined)
            next.exploreShowOther = patch.showOther ? "1" : "0";
        if (patch.cumulative !== undefined)
            next.exploreCumulative = patch.cumulative ? "1" : "0";
        if (patch.chartType !== undefined)
            next.exploreChartType = patch.chartType;
        if (clearFocus)
            next.focus = "";
        patchParams(next);
    }
    const fetchPath = scope === "service"
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
        if (!exportMode)
            return;
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
        api(fetchPath)
            .then((payload) => {
            setData(payload);
            onDataLoaded?.(payload);
        })
            .catch((e) => setErr(String(e)))
            .finally(() => setLoading(false));
    }, [fetchPath, scope, userId, groupId, apiKeyId, connectionId, agentId, projectId, onDataLoaded]);
    useEffect(() => {
        if (!settingsOpen)
            return;
        const onDoc = (e) => {
            if (settingsRef.current && !settingsRef.current.contains(e.target)) {
                setSettingsOpen(false);
            }
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [settingsOpen]);
    const subtitle = useMemo(() => {
        if (scope === "mine") {
            return _jsx(_Fragment, { children: "Your personal usage on Alpharouter" });
        }
        if (scope === "user" && data?.user) {
            const name = data.user.display_name?.trim() || data.user.username;
            return (_jsxs(_Fragment, { children: ["Usage for ", _jsx("strong", { children: name })] }));
        }
        if (scope === "api_key" && data?.api_key) {
            return (_jsxs(_Fragment, { children: ["Gateway key ", _jsx("strong", { children: data.api_key.name })] }));
        }
        if (scope === "connection" && data?.connection) {
            const c = data.connection;
            return (_jsxs(_Fragment, { children: ["Provider connection ", _jsx("strong", { children: c.name }), _jsxs("span", { className: "muted-text", children: [" ", "\u00B7 ", c.provider_type, c.base_url ? ` · ${c.base_url}` : "", !c.is_active ? " · disabled" : ""] })] }));
        }
        if (scope === "group" && data?.group) {
            const g = data.group;
            return (_jsxs(_Fragment, { children: ["Combined usage for group ", _jsx("strong", { children: g.name }), typeof g.member_count === "number" && (_jsxs("span", { className: "muted-text", children: [" \u00B7 ", g.member_count, " member(s)"] }))] }));
        }
        if (scope === "agent" && data?.agent) {
            return (_jsxs(_Fragment, { children: ["Usage for Agent ", _jsx("strong", { children: data.agent.name })] }));
        }
        if (scope === "project" && data?.project) {
            return (_jsxs(_Fragment, { children: ["Usage for project ", _jsx("strong", { children: data.project.name })] }));
        }
        return _jsx(_Fragment, { children: "Service usage across models on Alpharouter" });
    }, [scope, data]);
    async function exportActivity(fmt) {
        const q = buildQuery();
        const path = scope === "service"
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
        if (fmt === "pdf")
            setExportingPdf(false);
        if (!res.ok) {
            let msg = `Export failed (${res.status})`;
            try {
                const body = await res.json();
                if (body?.detail)
                    msg = String(body.detail);
            }
            catch {
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
    return (_jsxs("div", { className: "activity-page", "data-activity-ready": !loading && data ? "1" : undefined, children: [_jsxs("header", { className: "activity-page-header", children: [_jsxs("div", { children: [_jsx("h1", { children: title ??
                                    (scope === "mine"
                                        ? MY_USAGE_AND_ACTIVITY_LABEL
                                        : scope === "user" ||
                                            scope === "group" ||
                                            scope === "connection" ||
                                            scope === "api_key" ||
                                            scope === "agent" ||
                                            scope === "project"
                                            ? USAGE_AND_ACTIVITY_LABEL
                                            : "Activity") }), _jsxs("p", { className: "activity-subtitle", children: [subtitle, data ? ` · ${periodLabel(data.period)}` : "", cfg.showGroupBy && data ? ` · ${groupByLabel(data.group_by)}` : "", validTz === "utc" ? " · UTC" : " · Local time"] })] }), _jsxs("div", { className: "activity-toolbar", children: [backLink ? (_jsx(Link, { to: backLink.to, className: "btn btn-ghost activity-back", children: backLink.label })) : null, toolbarExtra, _jsx(ActivityTimezoneChip, { value: validTz, onChange: (tz) => patchParams({ tz }) }), cfg.filterKeys.length ? (_jsx(ActivityFilterMenu, { model: modelFilter, user: userFilter, app: appFilter, status: statusFilter, apiKey: apiKeyFilter, models: data?.available_models ?? [], users: data?.available_users ?? [], apps: data?.available_apps ?? [], apiKeys: data?.available_api_keys ?? [], visibleKeys: cfg.filterKeys, onChange: (patch) => patchParams(patch), onClear: () => patchParams({
                                    model: "",
                                    user: allowUserFilter ? "" : undefined,
                                    app: allowAppFilter ? "" : undefined,
                                    status: allowStatusFilter ? "" : undefined,
                                    apiKey: allowApiKeyFilter ? "" : undefined,
                                }) })) : null, _jsx(ActivityPeriodMenu, { value: validPeriod, onChange: (p) => patchParams({ period: p }) }), cfg.showGroupBy ? (_jsx(ActivityGroupByMenu, { value: validGroupBy, onChange: (g) => patchParams({ groupBy: g }) })) : null, _jsxs("div", { className: "activity-menu-wrap", ref: settingsRef, children: [_jsx("button", { type: "button", className: `activity-icon-btn${settingsOpen ? " activity-icon-btn--active" : ""}`, onClick: () => setSettingsOpen((v) => !v), "aria-label": "Export", title: "Export", children: _jsxs("svg", { viewBox: "0 0 24 24", width: "15", height: "15", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [_jsx("path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }), _jsx("polyline", { points: "7 10 12 15 17 10" }), _jsx("line", { x1: "12", y1: "15", x2: "12", y2: "3" })] }) }), settingsOpen ? (_jsxs("div", { className: "activity-menu-panel card", children: [_jsx("p", { className: "activity-menu-heading", children: "Export to\u2026" }), _jsx("button", { type: "button", className: "activity-menu-item", onClick: () => void exportActivity("csv"), children: "CSV" }), _jsx("button", { type: "button", className: "activity-menu-item", onClick: () => void exportActivity("pdf"), disabled: exportingPdf || loading || !data, children: exportingPdf ? "Generating PDF…" : "PDF" })] })) : null] })] })] }), exportingPdf ? _jsx("p", { className: "muted activity-export-status", children: "Generating PDF from dashboard\u2026" }) : null, err ? _jsx("p", { className: "error", children: err }) : null, loading ? _jsx("p", { className: "muted", children: "Loading activity\u2026" }) : null, !exportMode ? (_jsx(ActivityTabs, { value: activityTab, onChange: (tab) => patchParams({ tab, focus: tab === "explore" ? exploreFocus ?? undefined : "" }) })) : null, !loading && data && (exportMode || activityTab === "overview") ? (data.overview ? (_jsx(ActivityOverviewPanel, { overview: data.overview, insights: insights, timezone: validTz, heatmapMetric: heatmapMetric, onHeatmapMetricChange: setHeatmapMetric, hideUsers: cfg.hideOverviewUsers, onExplore: goExplore })) : (_jsx("p", { className: "muted", children: "Overview data is unavailable for this period." }))) : null, !loading && data && (exportMode || activityTab === "trends") ? (data.trends ? (_jsx(ActivityTrendsPanel, { trends: data.trends, hideUsers: cfg.hideTrendsUsers, hideApiKeys: cfg.hideTrendsApiKeys, onExplore: goExplore })) : (_jsx("p", { className: "muted", children: "Trends data is unavailable for this period." }))) : null, !loading && data && (exportMode || activityTab === "explore") ? (data.explore ? (_jsx(ActivityExplorePanel, { explore: data.explore, controls: exploreControls, hiddenGroups: cfg.hiddenExploreGroups, onControlsChange: patchExploreControls, onDownloadPdf: () => void exportActivity("pdf") })) : (_jsx("p", { className: "muted", children: "Explore data is unavailable for this period." }))) : null, !loading && !err && !data ? (_jsx("p", { className: "muted", children: "No usage data for this period." })) : null, footer ? (_jsxs(_Fragment, { children: [_jsx("hr", { className: "activity-section-divider" }), footer] })) : null] }));
}
