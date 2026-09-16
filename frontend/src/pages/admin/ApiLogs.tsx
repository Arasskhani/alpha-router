import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import LogFilterCombobox from "../../components/admin/LogFilterCombobox";
import ModelName from "../../components/ModelName";
import RequestLogCostDetailsModal from "../../components/RequestLogCostDetailsModal";
import ApiKeyInspectButtons from "../../components/apiKeys/ApiKeyInspectButtons";
import { api, authFetch, formatApiError } from "../../api";
import { attachDragScroll } from "../../lib/dragScroll";
import { useConfirm } from "../../context/ConfirmContext";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import { formatLocalDateTime } from "../../lib/dateTime";
import {
  confidenceLabel,
  errorCodeLabel,
  fetchAdminRequestLogCostDetails,
  isPersonalApiKeyLog,
  operationTypeLabel,
  type CostDetails,
  type RequestLogSummary,
} from "../../lib/requestLogCostDetails";

type Log = RequestLogSummary;

type FilterOptions = {
  usernames: string[];
  models: string[];
  operation_types?: string[];
  error_codes?: string[];
};

type ApiKeyMeta = {
  id: number;
  name: string;
  prefix?: string;
};

type Props = {
  /** When set, this page is the API-key-scoped logs view. */
  apiKeyId?: number;
};

async function downloadCsvExport(path: string): Promise<void> {
  const res = await authFetch(path);
  if (!res.ok) {
    let message = `Export failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) message = String(body.detail);
    } catch {
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

export default function ApiLogs({ apiKeyId }: Props) {
  const { confirm, prompt } = useConfirm();
  const writeLock = useAdminWriteLock();
  const [searchParams] = useSearchParams();
  const fromKeyRoute = Number.isFinite(apiKeyId) && (apiKeyId as number) > 0;
  const queryKeyId = Number(searchParams.get("api_key_id") || "") || undefined;
  const scopedKeyId = fromKeyRoute ? (apiKeyId as number) : queryKeyId;
  const [items, setItems] = useState<Log[]>([]);
  const [keyMeta, setKeyMeta] = useState<ApiKeyMeta | null>(null);
  const [username, setUsername] = useState("");
  const [model, setModel] = useState(searchParams.get("model_id") || searchParams.get("model") || "");
  const [responseStatus, setResponseStatus] = useState<"" | "success" | "fail">("");
  const [promptCache, setPromptCache] = useState<"" | "yes" | "no">("");
  const tableScrollRef = useRef<HTMLDivElement | null>(null);

  // Grab-and-pull sideways. The table is wider than the page on a laptop now
  // that columns are no longer hidden, and a mouse has no other way across it
  // than the scrollbar under a full screen of rows.
  useEffect(() => {
    const el = tableScrollRef.current;
    if (!el) return;
    return attachDragScroll(el);
  }, []);
  const [operationType, setOperationType] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [loading, setLoading] = useState(false);
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({
    usernames: [],
    models: [],
    operation_types: [],
    error_codes: [],
  });
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [selectedLog, setSelectedLog] = useState<Log | null>(null);
  const [costDetails, setCostDetails] = useState<CostDetails | null>(null);
  const [costDetailsLoading, setCostDetailsLoading] = useState(false);
  const [costDetailsError, setCostDetailsError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportingOne, setExportingOne] = useState(false);
  const [exportError, setExportError] = useState("");

  const buildFilterQuery = useCallback(
    (limit?: string) => {
      const q = new URLSearchParams();
      if (limit) q.set("limit", limit);
      if (username.trim()) q.set("username", username.trim());
      if (model.trim()) q.set("model_id", model.trim());
      if (responseStatus) q.set("response_status", responseStatus);
      if (promptCache) q.set("prompt_cache", promptCache);
      if (operationType) q.set("operation_type", operationType);
      if (errorCode) q.set("error_code", errorCode);
      if (start) q.set("start_date", start);
      if (end) q.set("end_date", end);
      if (!fromKeyRoute && scopedKeyId) q.set("api_key_id", String(scopedKeyId));
      return q;
    },
    [username, model, responseStatus, promptCache, operationType, errorCode, start, end, fromKeyRoute, scopedKeyId],
  );

  const logsPath = fromKeyRoute ? `/api/admin/api-keys/${apiKeyId}/logs` : "/api/admin/logs";

  const loadFilterOptions = useCallback(async () => {
    setOptionsLoading(true);
    try {
      const d = await api<FilterOptions>("/api/admin/logs/filter-options");
      setFilterOptions(d);
    } catch {
      setFilterOptions({ usernames: [], models: [], operation_types: [], error_codes: [] });
    } finally {
      setOptionsLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    const q = buildFilterQuery("200");
    setLoading(true);
    try {
      const d = await api<{ items: Log[]; api_key?: ApiKeyMeta }>(`${logsPath}?${q}`);
      setItems(d.items);
      setKeyMeta(d.api_key ?? null);
    } finally {
      setLoading(false);
    }
  }, [buildFilterQuery, logsPath]);

  const exportFiltered = async () => {
    setExportError("");
    setExporting(true);
    try {
      const q = buildFilterQuery("5000");
      await downloadCsvExport(`${logsPath}/export?${q}`);
    } catch (err) {
      setExportError(formatApiError(err));
    } finally {
      setExporting(false);
    }
  };

  const exportSelected = async () => {
    if (!selectedLog) return;
    setExportError("");
    setExportingOne(true);
    try {
      await downloadCsvExport(`/api/admin/logs/${selectedLog.id}/export`);
    } catch (err) {
      setExportError(formatApiError(err));
    } finally {
      setExportingOne(false);
    }
  };

  const fmt = (n: number) => new Intl.NumberFormat("en-US").format(n || 0);
  const tok = (n: number) => `${fmt(n)} tok`;
  const cacheHint = (cached: number, prompt: number) => {
    if (cached <= 0) return "No prompt cache hit on this request";
    const pct = prompt > 0 ? Math.round((cached / prompt) * 100) : 0;
    const share = pct > 0 ? ` (${pct}% of ${fmt(prompt)} input tokens)` : "";
    return `Prompt cache hit: ${fmt(cached)} prompt tokens served from provider cache${share}`;
  };
  const costQuality = (log: Log) => {
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

  const openCostDetails = async (log: Log) => {
    setSelectedLog(log);
    setCostDetails(null);
    setCostDetailsError("");
    setExportError("");
    setCostDetailsLoading(true);
    try {
      const details = await fetchAdminRequestLogCostDetails(log.id);
      setCostDetails(details);
    } catch (err) {
      setCostDetailsError(err instanceof Error ? err.message : "Failed to load cost details");
    } finally {
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
      message:
        "This permanently deletes every row in the API Logs table — users, models, costs, cache hits, and errors. This action cannot be undone.",
      confirmLabel: "Continue",
      danger: true,
    });
    if (!step1) return;

    const step2 = await confirm({
      title: "Delete all request history?",
      message:
        "Reports and activity charts that rely on request logs will no longer include this data. Copies exported to Excel or PDF outside Alpharouter are not affected.",
      confirmLabel: "Yes, delete all",
      danger: true,
    });
    if (!step2) return;

    // The server verifies this phrase too (and requires Super Admin): the
    // dialog is a courtesy, the typed phrase is the control.
    const typed = await prompt({
      title: "Final confirmation",
      message:
        "You are about to purge ALL API logs from Alpharouter. Only continue if you intentionally want an empty log table.",
      promptLabel: 'Type "DELETE ALL LOGS" to confirm',
      promptExactMatch: "DELETE ALL LOGS",
      confirmLabel: "Clear all logs now",
      danger: true,
    });
    if (typed !== "DELETE ALL LOGS") return;

    setLoading(true);
    try {
      await api("/api/admin/logs", {
        method: "DELETE",
        body: JSON.stringify({ confirm: typed }),
      });
      setItems([]);
      await load();
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const m = searchParams.get("model_id") || searchParams.get("model");
    if (m) setModel(m);
  }, [searchParams]);

  useEffect(() => {
    void load();
    void loadFilterOptions();
    // Refetch when the API key scope changes; Filter/Refresh still call load() directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- avoid refetching on every filter keystroke
  }, [scopedKeyId, fromKeyRoute]);

  return (
    <AdminPage
      title={keyMeta?.name ? `API Logs — ${keyMeta.name}` : "API Logs"}
      actions={
        scopedKeyId ? (
          <div className="api-logs-page-actions">
            <Link to="/admin/api-keys" className="btn btn-ghost activity-back">
              API Keys
            </Link>
            <ApiKeyInspectButtons keyId={scopedKeyId} active="logs" />
          </div>
        ) : undefined
      }
    >
      {keyMeta ? (
        <p className="muted-text api-logs-key-banner">
          Showing requests for gateway key <strong>{keyMeta.name}</strong>
          {keyMeta.prefix ? ` (${keyMeta.prefix}…)` : ""}.
        </p>
      ) : null}
      <div className="card api-logs-toolbar">
        <div className="api-logs-toolbar__main">
          {scopedKeyId ? null : (
            <LogFilterCombobox
              value={username}
              onChange={setUsername}
              options={filterOptions.usernames}
              placeholder="User / API key"
              loading={optionsLoading}
              disabled={loading}
              onOpen={() => void loadFilterOptions()}
            />
          )}
          <LogFilterCombobox
            value={model}
            onChange={setModel}
            options={filterOptions.models}
            placeholder="Model"
            loading={optionsLoading}
            disabled={loading}
            onOpen={() => void loadFilterOptions()}
          />
          <select
            value={responseStatus}
            onChange={(e) => setResponseStatus(e.target.value as "" | "success" | "fail")}
            aria-label="Response Status"
          >
            <option value="">All statuses</option>
            <option value="success">Success</option>
            <option value="fail">Fail</option>
          </select>
          <select
            value={promptCache}
            onChange={(e) => setPromptCache(e.target.value as "" | "yes" | "no")}
            aria-label="Prompt Cache"
          >
            <option value="">All cache</option>
            <option value="yes">Cache hit</option>
            <option value="no">No cache</option>
          </select>
          <select
            value={operationType}
            onChange={(e) => setOperationType(e.target.value)}
            aria-label="Request type"
            disabled={loading}
          >
            <option value="">All types</option>
            {(filterOptions.operation_types || []).map((t) => (
              <option key={t} value={t}>
                {operationTypeLabel(t)}
              </option>
            ))}
          </select>
          <select
            value={errorCode}
            onChange={(e) => setErrorCode(e.target.value)}
            aria-label="Failure reason"
            disabled={loading}
          >
            <option value="">All failures</option>
            {(filterOptions.error_codes || []).map((c) => (
              <option key={c} value={c}>
                {errorCodeLabel(c)}
              </option>
            ))}
          </select>
          <input
            className="api-logs-toolbar__date"
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            aria-label="Start date"
          />
          <input
            className="api-logs-toolbar__date"
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            aria-label="End date"
          />
          <button
            type="button"
            className="btn btn-readonly-ok api-logs-toolbar-btn api-logs-toolbar__filter-btn"
            onClick={() => void load()}
            disabled={loading}
          >
            Filter
          </button>
        </div>
        <div className="api-logs-toolbar__actions">
          <button
            type="button"
            className="btn btn-readonly-ok api-logs-toolbar-btn"
            onClick={() => void exportFiltered()}
            disabled={loading || exporting}
            title="Export the current filtered logs as CSV"
          >
            {exporting ? "Exporting…" : "Export"}
          </button>
          {scopedKeyId ? null : (
            <button
              type="button"
              className="btn btn-danger api-logs-toolbar-btn"
              {...writeLock.writeLockProps}
              onClick={() => void clearAllLogs()}
              disabled={loading || writeLock.readOnly}
            >
              Clear All Logs
            </button>
          )}
          <button
            type="button"
            className={`btn btn-readonly-ok api-logs-toolbar-btn${loading ? " api-logs-toolbar-btn--loading" : ""}`}
            onClick={() => void load()}
            disabled={loading}
            aria-label="Refresh logs"
            title="Refresh logs"
          >
            <svg
              className="api-logs-toolbar-btn__icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M21 12a9 9 0 1 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M21 12a9 9 0 1 1-9 9 9.75 9.75 0 0 1 6.74-2.74L21 16" />
              <path d="M16 16h5v5" />
            </svg>
            Refresh
          </button>
        </div>
        {exportError && !selectedLog && <p className="error api-logs-export-error">{exportError}</p>}
      </div>
      <div className="table-wrap table-wrap--api-logs" ref={tableScrollRef}>
        <table className="card data-table data-table--api-logs">
          <thead>
            <tr>
              <th className="api-log-col--time">Time</th>
              <th className="api-log-col--user">User</th>
              <th className="api-log-col--secondary">Type</th>
              <th className="api-log-col--model">Model</th>
              <th className="api-log-col--secondary">Provider</th>
              <th className="api-log-col--secondary">App</th>
              <th className="api-log-col--tokens">Input</th>
              <th className="api-log-col--tokens">Output</th>
              <th className="api-log-col--secondary api-log-col--cache">Prompt Cache</th>
              <th className="api-log-col--cost">Cost $</th>
              <th
                className="api-log-col--secondary api-log-col--duration"
                title="Total provider streaming time from first model chunk to last chunk (not time-to-first-token)"
              >
                Duration ms
              </th>
              <th className="api-log-col--status">Response Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => {
              const cached = (r.cached_tokens || 0) > 0;
              const cost = costQuality(r);
              return (
                <tr
                  key={r.id}
                  className="api-logs-row--clickable"
                  onClick={() => void openCostDetails(r)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      void openCostDetails(r);
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={`Open cost details for request ${r.id}`}
                >
                  <td className="api-log-col--time">{formatLocalDateTime(r.request_time)}</td>
                  <td
                    className="api-log-col--user"
                    title={
                      r.identity_type === "api_key"
                        ? `Alpharouter API key: ${r.api_key_name || r.username}`
                        : r.identity_type === "chat"
                          ? `Alpharouter web chat: ${r.username}`
                          : isPersonalApiKeyLog(r)
                            ? r.api_key_name
                              ? `Personal API key: ${r.api_key_name}`
                              : `Personal API key: ${r.username}`
                            : r.username
                    }
                  >
                    {r.identity_type === "api_key" ? (
                      <span className="api-log-identity">
                        <svg
                          className="api-log-identity-icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <circle cx="8" cy="15" r="4" />
                          <path d="M12 15h9M16 15v3M20 15v2" />
                        </svg>
                        <span className="api-log-identity__name">{r.api_key_name || r.username}</span>
                        <span className="api-log-identity-tag">(Gateway API Key)</span>
                      </span>
                    ) : r.identity_type === "chat" ? (
                      <span className="api-log-identity">
                        <svg
                          className="api-log-identity-icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z" />
                        </svg>
                        <span className="api-log-identity__name">{r.username}</span>
                      </span>
                    ) : isPersonalApiKeyLog(r) ? (
                      <span className="api-log-identity">
                        <svg
                          className="api-log-identity-icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <circle cx="8" cy="15" r="4" />
                          <path d="M12 15h9M16 15v3M20 15v2" />
                        </svg>
                        <span className="api-log-identity__name">{r.username}</span>
                      </span>
                    ) : (
                      <span className="api-log-identity">
                        <span className="api-log-identity__name">{r.username}</span>
                      </span>
                    )}
                  </td>
                  <td className="api-log-col--secondary">{operationTypeLabel(r.operation_type)}</td>
                  <td className="api-log-col--model" title={r.model_id}>
                    <ModelName modelId={r.model_id} label={r.model_id} size={14} />
                  </td>
                  <td className="api-log-col--secondary">{r.provider || "-"}</td>
                  <td
                    className="api-log-col--secondary"
                    title={
                      r.client_app
                        ? `Client: ${r.client_app}${r.source ? ` · Auth: ${r.source}` : ""}`
                        : r.source
                          ? `Auth: ${r.source}`
                          : undefined
                    }
                  >
                    {r.app || "Unknown"}
                  </td>
                  <td className="api-log-col--tokens">{tok(r.prompt_tokens || 0)}</td>
                  <td className="api-log-col--tokens">{tok(r.completion_tokens || 0)}</td>
                  <td className="api-log-col--secondary api-log-col--cache">
                    <span
                      className={`api-log-prompt-cache api-log-prompt-cache--${cached ? "yes" : "no"}`}
                      title={cacheHint(r.cached_tokens || 0, r.prompt_tokens || 0)}
                      aria-label={cacheHint(r.cached_tokens || 0, r.prompt_tokens || 0)}
                    >
                      {cached ? (
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                          <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      ) : (
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                          <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </span>
                  </td>
                  <td className="api-log-col--cost">
                    <span className="api-log-cost" title={cost.title}>
                      <span>{r.total_cost_usd?.toFixed(5)}</span>
                      <span className={`api-log-cost-quality api-log-cost-quality--${cost.key}`}>
                        {cost.label}
                      </span>
                    </span>
                  </td>
                  <td
                    className="api-log-col--secondary api-log-col--duration"
                    title={`${Math.round(r.response_time_ms)} ms total stream · ${tok(r.completion_tokens || 0)} output`}
                  >
                    {Math.round(r.response_time_ms)}
                  </td>
                  <td className="api-log-col--status">
                    {r.success ? (
                      "Success"
                    ) : (
                      <span
                        className="api-log-failure"
                        title={r.error_message || errorCodeLabel(r.error_code) || "Failed"}
                      >
                        <span className="api-log-failure__code">
                          {r.error_code ? errorCodeLabel(r.error_code) : "Fail"}
                        </span>
                        {r.error_message ? (
                          <span className="api-log-failure__message">{r.error_message}</span>
                        ) : null}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <RequestLogCostDetailsModal
        open={!!selectedLog}
        log={selectedLog}
        details={costDetails}
        loading={costDetailsLoading}
        error={costDetailsError}
        onClose={closeCostDetails}
        exportError={exportError}
        exportSlot={
          <button
            type="button"
            className="btn btn-readonly-ok api-logs-toolbar-btn"
            onClick={() => void exportSelected()}
            disabled={exportingOne || costDetailsLoading}
            title="Export this request and its cost ledger as CSV"
          >
            {exportingOne ? "Exporting…" : "Export"}
          </button>
        }
      />
    </AdminPage>
  );
}
