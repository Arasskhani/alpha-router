import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import LogFilterCombobox from "../../components/admin/LogFilterCombobox";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import { formatLocalDateTime } from "../../lib/dateTime";

type Log = {
  id: number;
  request_time: string;
  username: string;
  identity_type?: "user" | "api_key" | "chat";
  api_key_name?: string;
  api_key_prefix?: string;
  app?: string;
  source?: string;
  client_app?: string;
  provider?: string;
  model_id: string;
  prompt_language: string;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens?: number;
  total_cost_usd: number;
  response_time_ms: number;
  source_ip: string;
  success: boolean;
};

type FilterOptions = {
  usernames: string[];
  models: string[];
};

export default function ApiLogs() {
  const { confirm } = useConfirm();
  const writeLock = useAdminWriteLock();
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<Log[]>([]);
  const [username, setUsername] = useState("");
  const [model, setModel] = useState(searchParams.get("model_id") || searchParams.get("model") || "");
  const [responseStatus, setResponseStatus] = useState<"" | "success" | "fail">("");
  const [promptCache, setPromptCache] = useState<"" | "yes" | "no">("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [loading, setLoading] = useState(false);
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({ usernames: [], models: [] });
  const [optionsLoading, setOptionsLoading] = useState(false);

  const loadFilterOptions = useCallback(async () => {
    setOptionsLoading(true);
    try {
      const d = await api<FilterOptions>("/api/admin/logs/filter-options");
      setFilterOptions(d);
    } catch {
      setFilterOptions({ usernames: [], models: [] });
    } finally {
      setOptionsLoading(false);
    }
  }, []);

  const load = async () => {
    const q = new URLSearchParams({ limit: "200" });
    if (username.trim()) q.set("username", username.trim());
    if (model.trim()) q.set("model_id", model.trim());
    if (responseStatus) q.set("response_status", responseStatus);
    if (promptCache) q.set("prompt_cache", promptCache);
    if (start) q.set("start_date", start);
    if (end) q.set("end_date", end);
    setLoading(true);
    try {
      const d = await api<{ items: Log[] }>(`/api/admin/logs?${q}`);
      setItems(d.items);
    } finally {
      setLoading(false);
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
        "Reports and activity charts that rely on request logs will no longer include this data. Copies exported to Excel or PDF outside NITRO are not affected.",
      confirmLabel: "Yes, delete all",
      danger: true,
    });
    if (!step2) return;

    const step3 = await confirm({
      title: "Final confirmation",
      message:
        "You are about to purge ALL API logs from NITRO. Only continue if you intentionally want an empty log table.",
      confirmLabel: "Clear all logs now",
      danger: true,
    });
    if (!step3) return;

    setLoading(true);
    try {
      await api("/api/admin/logs", { method: "DELETE" });
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
  }, []);

  return (
    <AdminPage title="API Logs">
      <div className="card api-logs-toolbar">
        <div className="api-logs-toolbar__main">
          <LogFilterCombobox
            value={username}
            onChange={setUsername}
            options={filterOptions.usernames}
            placeholder="User / API key"
            loading={optionsLoading}
            disabled={loading}
            onOpen={() => void loadFilterOptions()}
          />
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
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          <button type="button" className="btn btn-readonly-ok api-logs-toolbar-btn" onClick={() => void load()} disabled={loading}>
            Filter
          </button>
        </div>
        <div className="api-logs-toolbar__actions">
          <button
            type="button"
            className="btn btn-danger api-logs-toolbar-btn"
            {...writeLock.writeLockProps}
            onClick={() => void clearAllLogs()}
            disabled={loading || writeLock.readOnly}
          >
            Clear All Logs
          </button>
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
      </div>
      <div className="table-wrap">
        <table className="card data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Model</th>
              <th>Provider</th>
              <th>App</th>
              <th>Input</th>
              <th>Output</th>
              <th>Prompt Cache</th>
              <th>Cost $</th>
              <th title="Total provider streaming time from first model chunk to last chunk (not time-to-first-token)">
                Duration ms
              </th>
              <th>Response Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => {
              const cached = (r.cached_tokens || 0) > 0;
              return (
                <tr key={r.id}>
                  <td>{formatLocalDateTime(r.request_time)}</td>
                  <td>
                    {r.identity_type === "api_key" ? (
                      <span className="api-log-identity" title="NITRO API key">
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
                        <span>{r.api_key_name || r.username}</span>
                        <span className="api-log-identity-tag">(API Key)</span>
                      </span>
                    ) : r.identity_type === "chat" ? (
                      <span className="api-log-identity" title="NITRO web chat">
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
                        <span>{r.username}</span>
                      </span>
                    ) : (
                      r.username
                    )}
                  </td>
                  <td>{r.model_id}</td>
                  <td>{r.provider || "-"}</td>
                  <td
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
                  <td>{tok(r.prompt_tokens || 0)}</td>
                  <td>{tok(r.completion_tokens || 0)}</td>
                  <td>
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
                  <td>{r.total_cost_usd?.toFixed(5)}</td>
                  <td title={`${Math.round(r.response_time_ms)} ms total stream · ${tok(r.completion_tokens || 0)} output`}>
                    {Math.round(r.response_time_ms)}
                  </td>
                  <td>{r.success ? "Success" : "Fail"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </AdminPage>
  );
}
