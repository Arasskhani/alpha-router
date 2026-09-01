import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import OperationsMetricCard from "../../components/operations/OperationsMetricCard";
import OperationsSlowModelsTable from "../../components/operations/OperationsSlowModelsTable";
import OperationsTimeRangeMenu, { DEFAULT_OPS_RANGE, } from "../../components/operations/OperationsTimeRangeMenu";
import { api } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { formatLocalDateTime } from "../../lib/dateTime";
function humanSize(bytes) {
    if (!bytes)
        return "0 B";
    let v = bytes;
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v.toFixed(1)} ${units[i]}`;
}
function formatFooter(f) {
    if (!f)
        return undefined;
    const suffix = f.suffix ?? "";
    const val = Number.isInteger(f.value) ? String(f.value) : String(f.value);
    return { label: f.label, value: `${val}${suffix}` };
}
function formatCount(v) {
    if (v >= 1_000_000)
        return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1000)
        return `${Math.round(v / 1000)}K`;
    return String(Math.round(v));
}
function formatCheckedAt(iso) {
    if (!iso)
        return "Never";
    return formatLocalDateTime(iso);
}
function OpsCardView({ card, formatValue, footer, }) {
    return (_jsx(OperationsMetricCard, { title: card.title, total: card.total, unit: card.unit, changePct: card.change_pct, segments: card.segments, chartRows: card.chart, formatValue: formatValue, footer: footer }));
}
export default function Operations() {
    const readOnly = useReadOnly();
    const [data, setData] = useState(null);
    const [capacity, setCapacity] = useState(null);
    const [capacityMax, setCapacityMax] = useState(200);
    const [capacityPerSubject, setCapacityPerSubject] = useState(2);
    const [capacityRetryAfter, setCapacityRetryAfter] = useState(30);
    const [savingCapacity, setSavingCapacity] = useState(false);
    const [rangeKey, setRangeKey] = useState(DEFAULT_OPS_RANGE);
    const [loading, setLoading] = useState(true);
    const [checking, setChecking] = useState(false);
    const [error, setError] = useState("");
    const intervalRef = useRef(null);
    const loadCapacity = useCallback(async () => {
        try {
            const payload = await api("/api/admin/operations/code-interpreter-capacity");
            setCapacity(payload);
            setCapacityMax(payload.settings.max_concurrent_turns);
            setCapacityPerSubject(payload.settings.max_per_subject);
            setCapacityRetryAfter(payload.settings.retry_after_seconds);
        }
        catch (e) {
            setError(String(e));
        }
    }, []);
    const load = useCallback(async (record, range) => {
        if (record)
            setChecking(true);
        else
            setLoading(true);
        setError("");
        const qs = new URLSearchParams({ range });
        if (record)
            qs.set("record", "true");
        try {
            const path = record
                ? `/api/admin/operations/check-now?${qs}`
                : `/api/admin/operations/dashboard?${qs}`;
            const payload = record
                ? await api(path, { method: "POST" })
                : await api(path);
            setData(payload);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setLoading(false);
            setChecking(false);
        }
    }, []);
    useEffect(() => {
        void load(false, rangeKey);
        void loadCapacity();
        intervalRef.current = window.setInterval(() => {
            void load(false, rangeKey);
            void loadCapacity();
        }, 3600_000);
        return () => {
            if (intervalRef.current)
                window.clearInterval(intervalRef.current);
        };
    }, [load, loadCapacity, rangeKey]);
    async function saveCapacity(e) {
        e.preventDefault();
        const hardMax = capacity?.settings.hard_max_concurrent_turns ?? 200;
        const nextMax = Math.max(1, Math.min(hardMax, Math.round(Number(capacityMax) || 1)));
        const nextPerSubject = Math.max(1, Math.min(nextMax, Math.round(Number(capacityPerSubject) || 1)));
        const nextRetry = Math.max(1, Math.min(300, Math.round(Number(capacityRetryAfter) || 1)));
        setSavingCapacity(true);
        setError("");
        try {
            const payload = await api("/api/admin/operations/code-interpreter-capacity", {
                method: "PATCH",
                body: JSON.stringify({
                    max_concurrent_turns: nextMax,
                    max_per_subject: nextPerSubject,
                    retry_after_seconds: nextRetry,
                }),
            });
            setCapacity(payload);
            setCapacityMax(payload.settings.max_concurrent_turns);
            setCapacityPerSubject(payload.settings.max_per_subject);
            setCapacityRetryAfter(payload.settings.retry_after_seconds);
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setSavingCapacity(false);
        }
    }
    const c = data?.cards;
    return (_jsxs(AdminPage, { title: "Operations", actions: _jsxs("div", { className: "operations-header-actions", children: [_jsx(OperationsTimeRangeMenu, { value: rangeKey, onChange: setRangeKey, disabled: loading || checking }), _jsx("button", { type: "button", className: "btn", disabled: checking || loading, onClick: () => {
                        void load(true, rangeKey);
                        void loadCapacity();
                    }, children: checking ? "Checking…" : "Check Now" })] }), children: [_jsxs("p", { className: "muted-text", children: ["Infrastructure snapshots (CPU, memory, DB) plus API traffic from ", _jsx("code", { children: "request_logs" }), " for", " ", _jsx("strong", { children: data?.time_range?.label ?? "Past 1 Day" }), ". Auto-refreshes every 1 hour. Live DB detail:", " ", _jsx(Link, { to: "/admin/database", children: "Database" }), " \u00B7 Usage & cost: ", _jsx(Link, { to: "/admin", children: "Dashboard" }), "."] }), data && (_jsxs("p", { className: "operations-meta muted-text", children: ["Last checked: ", _jsx("strong", { children: formatCheckedAt(data.last_checked_at) }), data.db_engine && (_jsxs(_Fragment, { children: [" ", "\u00B7 Engine: ", _jsx("strong", { children: data.db_engine })] })), data.snapshot_count > 0 && _jsxs(_Fragment, { children: [" \u00B7 ", data.snapshot_count, " infra samples"] }), data.request_log_count >= 0 && _jsxs(_Fragment, { children: [" \u00B7 ", formatCount(data.request_log_count), " API log rows"] })] })), error && _jsx("p", { className: "alert alert-error", children: error }), capacity && (_jsxs(_Fragment, { children: [_jsx("h3", { className: "operations-section-title", children: "Code Interpreter capacity" }), _jsxs("div", { className: "card operations-capacity-card", children: [_jsxs("div", { className: "operations-capacity-summary", children: [_jsxs("span", { children: [_jsx("strong", { children: capacity.runtime.active }), " active"] }), _jsxs("span", { children: [_jsx("strong", { children: capacity.runtime.available }), " available"] }), _jsxs("span", { children: [_jsxs("strong", { children: [capacity.runtime.utilization_percent.toFixed(1), "%"] }), " utilized"] }), _jsxs("span", { children: [_jsx("strong", { children: capacity.broker.status === "ok" ? capacity.broker.active_jobs ?? 0 : "—" }), " ", "broker jobs"] })] }), _jsx("div", { className: "operations-capacity-track", "aria-label": "Code Interpreter capacity utilization", children: _jsx("span", { style: { width: `${Math.min(100, capacity.runtime.utilization_percent)}%` } }) }), _jsxs("form", { className: "operations-capacity-form", onSubmit: saveCapacity, children: [_jsxs("label", { children: ["Concurrent turns", _jsx("input", { type: "number", min: 1, max: capacity.settings.hard_max_concurrent_turns, value: capacityMax, onChange: (e) => setCapacityMax(Number(e.target.value)), disabled: readOnly || savingCapacity })] }), _jsxs("label", { children: ["Per user / API key", _jsx("input", { type: "number", min: 1, max: capacityMax, value: capacityPerSubject, onChange: (e) => setCapacityPerSubject(Number(e.target.value)), disabled: readOnly || savingCapacity })] }), _jsxs("label", { children: ["Retry-After (seconds)", _jsx("input", { type: "number", min: 1, max: 300, value: capacityRetryAfter, onChange: (e) => setCapacityRetryAfter(Number(e.target.value)), disabled: readOnly || savingCapacity })] }), _jsx("button", { className: "btn btn-primary", disabled: readOnly || savingCapacity, children: savingCapacity ? "Saving…" : "Save capacity" })] }), _jsxs("p", { className: "muted-text", children: ["Environment hard ceiling: ", capacity.settings.hard_max_concurrent_turns, " turns \u00B7 lease TTL", " ", capacity.settings.lease_ttl_seconds, "s \u00B7 heartbeat ", capacity.settings.heartbeat_seconds, "s. Requests above the operational limit are rejected immediately with HTTP 429."] })] })] })), c && (_jsxs(_Fragment, { children: [_jsx("h3", { className: "operations-section-title", children: "Infrastructure" }), _jsxs("div", { className: "activity-metrics-grid operations-metrics-grid", children: [_jsx(OpsCardView, { card: c.cpu, formatValue: (v) => `${v.toFixed(1)}` }), _jsx(OpsCardView, { card: c.memory, formatValue: (v) => `${v.toFixed(1)}`, footer: c.memory.footer
                                    ? { label: c.memory.footer.label, value: humanSize(c.memory.footer.value) }
                                    : undefined }), _jsx(OpsCardView, { card: c.database, formatValue: (v) => `${v.toFixed(2)}`, footer: c.database.footer
                                    ? { label: c.database.footer.label, value: humanSize(c.database.footer.value) }
                                    : undefined })] }), _jsx("h3", { className: "operations-section-title", children: "API traffic (request logs)" }), _jsxs("div", { className: "activity-metrics-grid operations-metrics-grid", children: [_jsx(OpsCardView, { card: c.errors, formatValue: (v) => formatCount(v), footer: formatFooter(c.errors.footer) }), _jsx(OpsCardView, { card: c.latency, formatValue: (v) => `${Math.round(v)}`, footer: formatFooter(c.latency.footer) }), _jsx(OpsCardView, { card: c.throughput, formatValue: (v) => formatCount(v), footer: formatFooter(c.throughput.footer) })] }), _jsx("h3", { className: "operations-section-title", children: "Model experience" }), _jsxs("p", { className: "muted-text operations-section-lead", children: ["When users say models feel slow \u2014 P95 by model, slow requests (\u2265", " ", (data.model_experience.slow_request_threshold_ms / 1000).toFixed(0), "s), and comparison to the prior", " ", data.time_range?.period_short ?? "period", "."] }), _jsxs("div", { className: "activity-metrics-grid operations-metrics-grid", children: [_jsx(OpsCardView, { card: c.slow_requests, formatValue: (v) => formatCount(v), footer: formatFooter(c.slow_requests.footer) }), _jsx(OpsCardView, { card: c.p95_vs_prior, formatValue: (v) => `${Math.round(v)}`, footer: formatFooter(c.p95_vs_prior.footer) }), _jsx(OpsCardView, { card: c.models_p95, formatValue: (v) => `${Math.round(v)}`, footer: formatFooter(c.models_p95.footer) })] }), _jsx(OperationsSlowModelsTable, { rows: data.model_experience.slowest_models, thresholdMs: data.model_experience.slow_request_threshold_ms })] })), loading && !data && _jsx("p", { className: "muted-text", children: "Loading operations dashboard\u2026" })] }));
}
