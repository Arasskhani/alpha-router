import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import LogFilterCombobox from "../../components/admin/LogFilterCombobox";
import ModelName from "../../components/ModelName";
import RequestLogCostDetailsModal from "../../components/RequestLogCostDetailsModal";
import ApiKeyInspectButtons from "../../components/apiKeys/ApiKeyInspectButtons";
import { api, authFetch, formatApiError } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import { formatLocalDateTime } from "../../lib/dateTime";
import { confidenceLabel, fetchAdminRequestLogCostDetails, isPersonalApiKeyLog, } from "../../lib/requestLogCostDetails";
async function downloadCsvExport(path) {
    const res = await authFetch(path);
    if (!res.ok) {
        let message = `Export failed (${res.status})`;
        try {
            const body = await res.json();
            if (body?.detail)
                message = String(body.detail);
        }
        catch {
            /* ignore */
        }
        throw new Error(message);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition");
    const match = cd?.match(/filename="([^"]+)"/);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = match?.[1] ?? "alpharouter-api-logs.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
}
export default function ApiLogs({ apiKeyId }) {
    const { confirm } = useConfirm();
    const writeLock = useAdminWriteLock();
    const [searchParams] = useSearchParams();
    const fromKeyRoute = Number.isFinite(apiKeyId) && apiKeyId > 0;
    const queryKeyId = Number(searchParams.get("api_key_id") || "") || undefined;
    const scopedKeyId = fromKeyRoute ? apiKeyId : queryKeyId;
    const [items, setItems] = useState([]);
    const [keyMeta, setKeyMeta] = useState(null);
    const [username, setUsername] = useState("");
    const [model, setModel] = useState(searchParams.get("model_id") || searchParams.get("model") || "");
    const [responseStatus, setResponseStatus] = useState("");
    const [promptCache, setPromptCache] = useState("");
    const [start, setStart] = useState("");
    const [end, setEnd] = useState("");
    const [loading, setLoading] = useState(false);
    const [filterOptions, setFilterOptions] = useState({ usernames: [], models: [] });
    const [optionsLoading, setOptionsLoading] = useState(false);
    const [selectedLog, setSelectedLog] = useState(null);
    const [costDetails, setCostDetails] = useState(null);
    const [costDetailsLoading, setCostDetailsLoading] = useState(false);
    const [costDetailsError, setCostDetailsError] = useState("");
    const [exporting, setExporting] = useState(false);
    const [exportingOne, setExportingOne] = useState(false);
    const [exportError, setExportError] = useState("");
    const buildFilterQuery = useCallback((limit) => {
        const q = new URLSearchParams();
        if (limit)
            q.set("limit", limit);
        if (username.trim())
            q.set("username", username.trim());
        if (model.trim())
            q.set("model_id", model.trim());
        if (responseStatus)
            q.set("response_status", responseStatus);
        if (promptCache)
            q.set("prompt_cache", promptCache);
        if (start)
            q.set("start_date", start);
        if (end)
            q.set("end_date", end);
        if (!fromKeyRoute && scopedKeyId)
            q.set("api_key_id", String(scopedKeyId));
        return q;
    }, [username, model, responseStatus, promptCache, start, end, fromKeyRoute, scopedKeyId]);
    const logsPath = fromKeyRoute ? `/api/admin/api-keys/${apiKeyId}/logs` : "/api/admin/logs";
    const loadFilterOptions = useCallback(async () => {
        setOptionsLoading(true);
        try {
            const d = await api("/api/admin/logs/filter-options");
            setFilterOptions(d);
        }
        catch {
            setFilterOptions({ usernames: [], models: [] });
        }
        finally {
            setOptionsLoading(false);
        }
    }, []);
    const load = useCallback(async () => {
        const q = buildFilterQuery("200");
        setLoading(true);
        try {
            const d = await api(`${logsPath}?${q}`);
            setItems(d.items);
            setKeyMeta(d.api_key ?? null);
        }
        finally {
            setLoading(false);
        }
    }, [buildFilterQuery, logsPath]);
    const exportFiltered = async () => {
        setExportError("");
        setExporting(true);
        try {
            const q = buildFilterQuery("5000");
            await downloadCsvExport(`${logsPath}/export?${q}`);
        }
        catch (err) {
            setExportError(formatApiError(err));
        }
        finally {
            setExporting(false);
        }
    };
    const exportSelected = async () => {
        if (!selectedLog)
            return;
        setExportError("");
        setExportingOne(true);
        try {
            await downloadCsvExport(`/api/admin/logs/${selectedLog.id}/export`);
        }
        catch (err) {
            setExportError(formatApiError(err));
        }
        finally {
            setExportingOne(false);
        }
    };
    const fmt = (n) => new Intl.NumberFormat("en-US").format(n || 0);
    const tok = (n) => `${fmt(n)} tok`;
    const cacheHint = (cached, prompt) => {
        if (cached <= 0)
            return "No prompt cache hit on this request";
        const pct = prompt > 0 ? Math.round((cached / prompt) * 100) : 0;
        const share = pct > 0 ? ` (${pct}% of ${fmt(prompt)} input tokens)` : "";
        return `Prompt cache hit: ${fmt(cached)} prompt tokens served from provider cache${share}`;
    };
    const costQuality = (log) => {
        const base = confidenceLabel(log.cost_confidence || "unknown", !!log.has_unpriced_usage);
        const details = log.has_unpriced_usage
            ? [
                "At least one upstream call did not expose enough billing data; the shown total excludes that unknown cost.",
            ]
            : [
                `Source: ${log.cost_source || "unknown"}`,
                log.provider_cost_usd != null ? `Provider: $${log.provider_cost_usd.toFixed(8)}` : "",
                log.calculated_cost_usd != null ? `Calculated: $${log.calculated_cost_usd.toFixed(8)}` : "",
                log.reconciled_at ? `Reconciled: ${formatLocalDateTime(log.reconciled_at)}` : "",
                "Click row for cost details",
            ].filter(Boolean);
        return { ...base, title: details.join(" · ") };
    };
    const openCostDetails = async (log) => {
        setSelectedLog(log);
        setCostDetails(null);
        setCostDetailsError("");
        setExportError("");
        setCostDetailsLoading(true);
        try {
            const details = await fetchAdminRequestLogCostDetails(log.id);
            setCostDetails(details);
        }
        catch (err) {
            setCostDetailsError(err instanceof Error ? err.message : "Failed to load cost details");
        }
        finally {
            setCostDetailsLoading(false);
        }
    };
    const closeCostDetails = () => {
        setSelectedLog(null);
        setCostDetails(null);
        setCostDetailsError("");
        setExportError("");
        setCostDetailsLoading(false);
    };
    async function clearAllLogs() {
        const step1 = await confirm({
            title: "Clear all API logs?",
            message: "This permanently deletes every row in the API Logs table — users, models, costs, cache hits, and errors. This action cannot be undone.",
            confirmLabel: "Continue",
            danger: true,
        });
        if (!step1)
            return;
        const step2 = await confirm({
            title: "Delete all request history?",
            message: "Reports and activity charts that rely on request logs will no longer include this data. Copies exported to Excel or PDF outside Alpharouter are not affected.",
            confirmLabel: "Yes, delete all",
            danger: true,
        });
        if (!step2)
            return;
        const step3 = await confirm({
            title: "Final confirmation",
            message: "You are about to purge ALL API logs from Alpharouter. Only continue if you intentionally want an empty log table.",
            confirmLabel: "Clear all logs now",
            danger: true,
        });
        if (!step3)
            return;
        setLoading(true);
        try {
            await api("/api/admin/logs", { method: "DELETE" });
            setItems([]);
            await load();
        }
        finally {
            setLoading(false);
        }
    }
    useEffect(() => {
        const m = searchParams.get("model_id") || searchParams.get("model");
        if (m)
            setModel(m);
    }, [searchParams]);
    useEffect(() => {
        void load();
        void loadFilterOptions();
        // Refetch when the API key scope changes; Filter/Refresh still call load() directly.
        // eslint-disable-next-line react-hooks/exhaustive-deps -- avoid refetching on every filter keystroke
    }, [scopedKeyId, fromKeyRoute]);
    return (_jsxs(AdminPage, { title: keyMeta?.name ? `API Logs — ${keyMeta.name}` : "API Logs", actions: scopedKeyId ? (_jsxs("div", { className: "api-logs-page-actions", children: [_jsx(Link, { to: "/admin/api-keys", className: "btn btn-ghost activity-back", children: "API Keys" }), _jsx(ApiKeyInspectButtons, { keyId: scopedKeyId, active: "logs" })] })) : undefined, children: [keyMeta ? (_jsxs("p", { className: "muted-text api-logs-key-banner", children: ["Showing requests for gateway key ", _jsx("strong", { children: keyMeta.name }), keyMeta.prefix ? ` (${keyMeta.prefix}…)` : "", "."] })) : null, _jsxs("div", { className: "card api-logs-toolbar", children: [_jsxs("div", { className: "api-logs-toolbar__main", children: [scopedKeyId ? null : (_jsx(LogFilterCombobox, { value: username, onChange: setUsername, options: filterOptions.usernames, placeholder: "User / API key", loading: optionsLoading, disabled: loading, onOpen: () => void loadFilterOptions() })), _jsx(LogFilterCombobox, { value: model, onChange: setModel, options: filterOptions.models, placeholder: "Model", loading: optionsLoading, disabled: loading, onOpen: () => void loadFilterOptions() }), _jsxs("select", { value: responseStatus, onChange: (e) => setResponseStatus(e.target.value), "aria-label": "Response Status", children: [_jsx("option", { value: "", children: "All statuses" }), _jsx("option", { value: "success", children: "Success" }), _jsx("option", { value: "fail", children: "Fail" })] }), _jsxs("select", { value: promptCache, onChange: (e) => setPromptCache(e.target.value), "aria-label": "Prompt Cache", children: [_jsx("option", { value: "", children: "All cache" }), _jsx("option", { value: "yes", children: "Cache hit" }), _jsx("option", { value: "no", children: "No cache" })] }), _jsx("input", { className: "api-logs-toolbar__date", type: "date", value: start, onChange: (e) => setStart(e.target.value), "aria-label": "Start date" }), _jsx("input", { className: "api-logs-toolbar__date", type: "date", value: end, onChange: (e) => setEnd(e.target.value), "aria-label": "End date" }), _jsx("button", { type: "button", className: "btn btn-readonly-ok api-logs-toolbar-btn api-logs-toolbar__filter-btn", onClick: () => void load(), disabled: loading, children: "Filter" })] }), _jsxs("div", { className: "api-logs-toolbar__actions", children: [_jsx("button", { type: "button", className: "btn btn-readonly-ok api-logs-toolbar-btn", onClick: () => void exportFiltered(), disabled: loading || exporting, title: "Export the current filtered logs as CSV", children: exporting ? "Exporting…" : "Export" }), scopedKeyId ? null : (_jsx("button", { type: "button", className: "btn btn-danger api-logs-toolbar-btn", ...writeLock.writeLockProps, onClick: () => void clearAllLogs(), disabled: loading || writeLock.readOnly, children: "Clear All Logs" })), _jsxs("button", { type: "button", className: `btn btn-readonly-ok api-logs-toolbar-btn${loading ? " api-logs-toolbar-btn--loading" : ""}`, onClick: () => void load(), disabled: loading, "aria-label": "Refresh logs", title: "Refresh logs", children: [_jsxs("svg", { className: "api-logs-toolbar-btn__icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.75", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true, children: [_jsx("path", { d: "M21 12a9 9 0 1 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" }), _jsx("path", { d: "M3 3v5h5" }), _jsx("path", { d: "M21 12a9 9 0 1 1-9 9 9.75 9.75 0 0 1 6.74-2.74L21 16" }), _jsx("path", { d: "M16 16h5v5" })] }), "Refresh"] })] }), exportError && !selectedLog && _jsx("p", { className: "error api-logs-export-error", children: exportError })] }), _jsx("div", { className: "table-wrap table-wrap--api-logs", children: _jsxs("table", { className: "card data-table data-table--api-logs", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { className: "api-log-col--time", children: "Time" }), _jsx("th", { className: "api-log-col--user", children: "User" }), _jsx("th", { className: "api-log-col--model", children: "Model" }), _jsx("th", { className: "api-log-col--secondary", children: "Provider" }), _jsx("th", { className: "api-log-col--secondary", children: "App" }), _jsx("th", { className: "api-log-col--tokens", children: "Input" }), _jsx("th", { className: "api-log-col--tokens", children: "Output" }), _jsx("th", { className: "api-log-col--secondary api-log-col--cache", children: "Prompt Cache" }), _jsx("th", { className: "api-log-col--cost", children: "Cost $" }), _jsx("th", { className: "api-log-col--secondary api-log-col--duration", title: "Total provider streaming time from first model chunk to last chunk (not time-to-first-token)", children: "Duration ms" }), _jsx("th", { className: "api-log-col--status", children: "Response Status" })] }) }), _jsx("tbody", { children: items.map((r) => {
                                const cached = (r.cached_tokens || 0) > 0;
                                const cost = costQuality(r);
                                return (_jsxs("tr", { className: "api-logs-row--clickable", onClick: () => void openCostDetails(r), onKeyDown: (e) => {
                                        if (e.key === "Enter" || e.key === " ") {
                                            e.preventDefault();
                                            void openCostDetails(r);
                                        }
                                    }, tabIndex: 0, role: "button", "aria-label": `Open cost details for request ${r.id}`, children: [_jsx("td", { className: "api-log-col--time", children: formatLocalDateTime(r.request_time) }), _jsx("td", { className: "api-log-col--user", title: r.identity_type === "api_key"
                                                ? `Alpharouter API key: ${r.api_key_name || r.username}`
                                                : r.identity_type === "chat"
                                                    ? `Alpharouter web chat: ${r.username}`
                                                    : isPersonalApiKeyLog(r)
                                                        ? r.api_key_name
                                                            ? `Personal API key: ${r.api_key_name}`
                                                            : `Personal API key: ${r.username}`
                                                        : r.username, children: r.identity_type === "api_key" ? (_jsxs("span", { className: "api-log-identity", children: [_jsxs("svg", { className: "api-log-identity-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", children: [_jsx("circle", { cx: "8", cy: "15", r: "4" }), _jsx("path", { d: "M12 15h9M16 15v3M20 15v2" })] }), _jsx("span", { className: "api-log-identity__name", children: r.api_key_name || r.username }), _jsx("span", { className: "api-log-identity-tag", children: "(Gateway API Key)" })] })) : r.identity_type === "chat" ? (_jsxs("span", { className: "api-log-identity", children: [_jsx("svg", { className: "api-log-identity-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", children: _jsx("path", { d: "M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z" }) }), _jsx("span", { className: "api-log-identity__name", children: r.username })] })) : isPersonalApiKeyLog(r) ? (_jsxs("span", { className: "api-log-identity", children: [_jsxs("svg", { className: "api-log-identity-icon", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", children: [_jsx("circle", { cx: "8", cy: "15", r: "4" }), _jsx("path", { d: "M12 15h9M16 15v3M20 15v2" })] }), _jsx("span", { className: "api-log-identity__name", children: r.username })] })) : (_jsx("span", { className: "api-log-identity", children: _jsx("span", { className: "api-log-identity__name", children: r.username }) })) }), _jsx("td", { className: "api-log-col--model", title: r.model_id, children: _jsx(ModelName, { modelId: r.model_id, label: r.model_id, size: 14 }) }), _jsx("td", { className: "api-log-col--secondary", children: r.provider || "-" }), _jsx("td", { className: "api-log-col--secondary", title: r.client_app
                                                ? `Client: ${r.client_app}${r.source ? ` · Auth: ${r.source}` : ""}`
                                                : r.source
                                                    ? `Auth: ${r.source}`
                                                    : undefined, children: r.app || "Unknown" }), _jsx("td", { className: "api-log-col--tokens", children: tok(r.prompt_tokens || 0) }), _jsx("td", { className: "api-log-col--tokens", children: tok(r.completion_tokens || 0) }), _jsx("td", { className: "api-log-col--secondary api-log-col--cache", children: _jsx("span", { className: `api-log-prompt-cache api-log-prompt-cache--${cached ? "yes" : "no"}`, title: cacheHint(r.cached_tokens || 0, r.prompt_tokens || 0), "aria-label": cacheHint(r.cached_tokens || 0, r.prompt_tokens || 0), children: cached ? (_jsx("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", "aria-hidden": "true", children: _jsx("path", { d: "M5 13l4 4L19 7", strokeLinecap: "round", strokeLinejoin: "round" }) })) : (_jsx("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", "aria-hidden": "true", children: _jsx("path", { d: "M6 6l12 12M18 6L6 18", strokeLinecap: "round", strokeLinejoin: "round" }) })) }) }), _jsx("td", { className: "api-log-col--cost", children: _jsxs("span", { className: "api-log-cost", title: cost.title, children: [_jsx("span", { children: r.total_cost_usd?.toFixed(5) }), _jsx("span", { className: `api-log-cost-quality api-log-cost-quality--${cost.key}`, children: cost.label })] }) }), _jsx("td", { className: "api-log-col--secondary api-log-col--duration", title: `${Math.round(r.response_time_ms)} ms total stream · ${tok(r.completion_tokens || 0)} output`, children: Math.round(r.response_time_ms) }), _jsx("td", { className: "api-log-col--status", children: r.success ? "Success" : "Fail" })] }, r.id));
                            }) })] }) }), _jsx(RequestLogCostDetailsModal, { open: !!selectedLog, log: selectedLog, details: costDetails, loading: costDetailsLoading, error: costDetailsError, onClose: closeCostDetails, exportError: exportError, exportSlot: _jsx("button", { type: "button", className: "btn btn-readonly-ok api-logs-toolbar-btn", onClick: () => void exportSelected(), disabled: exportingOne || costDetailsLoading, title: "Export this request and its cost ledger as CSV", children: exportingOne ? "Exporting…" : "Export" }) })] }));
}
