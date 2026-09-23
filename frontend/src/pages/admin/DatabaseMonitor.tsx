import { useCallback, useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";

type TableStat = {
  name: string;
  label: string;
  exists: boolean;
  row_count: number | null;
  error?: string;
};

type SystemHost = {
  cpu_percent: number;
  memory_total_bytes: number;
  memory_used_bytes: number;
  memory_available_bytes: number;
  memory_percent: number;
};

type SystemProcess = {
  pid: number;
  name: string;
  cpu_percent: number;
  memory_rss_bytes: number;
};

type SystemMetrics = {
  available: boolean;
  host: SystemHost | null;
  process: SystemProcess | null;
  error: string | null;
};

type MonitorPayload = {
  connected: boolean;
  engine: string;
  database_url_masked: string;
  ping_ms: number | null;
  version: string | null;
  database_name: string | null;
  database_size_bytes: number | null;
  database_file_path: string | null;
  postgres_connections: number | null;
  tables: TableStat[];
  system: SystemMetrics;
  error: string | null;
};

function humanSize(bytes: number | null | undefined) {
  if (bytes == null) return "—";
  let v = bytes;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

function engineLabel(engine: string) {
  if (engine === "sqlite") return "SQLite";
  if (engine === "postgresql") return "PostgreSQL";
  return engine;
}

/** Soft cap for database size bar (same idea as Storage page). */
const DB_SIZE_VIZ_CAP_BYTES = 5 * 1024 * 1024 * 1024;
/** Ping bar fills at this latency (ms). */
const PING_VIZ_CAP_MS = 200;

function barPercent(value: number, cap: number) {
  if (cap <= 0) return 0;
  return Math.min(100, Math.round((value / cap) * 1000) / 10);
}

export default function DatabaseMonitor() {
  const [data, setData] = useState<MonitorPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await api<MonitorPayload>("/api/admin/database/monitor");
      setData(payload);
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const totalRows =
    data?.tables.reduce((sum, t) => sum + (typeof t.row_count === "number" ? t.row_count : 0), 0) ?? 0;

  const dbSizeBytes = data?.database_size_bytes ?? 0;
  const dbSizePct = barPercent(dbSizeBytes, DB_SIZE_VIZ_CAP_BYTES);
  const pingMs = data?.ping_ms ?? 0;
  const pingPct = data?.ping_ms != null ? barPercent(pingMs, PING_VIZ_CAP_MS) : 0;

  return (
    <AdminPage
      title="Database"
      actions={
        <button type="button" className="btn btn-secondary btn-readonly-ok" onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      }
    >
      <p className="muted-text">
        Read-only monitoring for the Alpharouter PostgreSQL database and for CPU/RAM on the host (or container) running
        this API process. No queries or schema changes from this page.
      </p>
      {error && <p className="alert alert-error" role="alert">{error}</p>}
      {data?.error && data.connected === false && (
        <p className="alert alert-error" role="alert">{data.error}</p>
      )}

      {data && (
        <>
          <div className="db-monitor-status-row">
            <span
              className={`db-monitor-pill ${data.connected ? "db-monitor-pill--ok" : "db-monitor-pill--bad"}`}
            >
              {data.connected ? "Connected" : "Unreachable"}
            </span>
            <span className="db-monitor-pill db-monitor-pill--muted">{engineLabel(data.engine)}</span>
          </div>

          <div className="card db-monitor-overview">
            <h3>Overview</h3>
            <dl className="db-monitor-dl">
              {data.engine === "postgresql" && (
                <div>
                  <dt>Other sessions</dt>
                  <dd>{data.postgres_connections ?? "—"}</dd>
                </div>
              )}
              {data.engine === "sqlite" && data.database_file_path && (
                <div className="db-monitor-dl-wide">
                  <dt>File path</dt>
                  <dd>
                    <code>{data.database_file_path}</code>
                  </dd>
                </div>
              )}
              <div className="db-monitor-dl-wide">
                <dt>Connection (masked)</dt>
                <dd>
                  <code>{data.database_url_masked}</code>
                </dd>
              </div>
            </dl>
          </div>

          <div className="card db-monitor-resources">
            <h3>CPU, memory & database</h3>
            <p className="muted-text" style={{ marginTop: 0 }}>
              Snapshot at refresh. Host = machine or Docker container; database size/ping = current engine; process =
              this Alpharouter API worker.
            </p>

            <div className="db-monitor-metric db-monitor-metric--static">
              <div className="db-monitor-metric-label">
                <span>Version</span>
                <span>{data.version || "—"}</span>
              </div>
            </div>
            <div className="db-monitor-metric db-monitor-metric--static">
              <div className="db-monitor-metric-label">
                <span>Database</span>
                <span>{data.database_name || "—"}</span>
              </div>
            </div>

            {data.system && !data.system.available && (
              <p className="muted-text">{data.system.error || "System metrics unavailable."}</p>
            )}
            {data.system?.available && data.system.host && (
              <>
                <h4 className="db-monitor-resource-heading">Host</h4>
                <div className="db-monitor-metric">
                  <div className="db-monitor-metric-label">
                    <span>CPU</span>
                    <span>{data.system.host.cpu_percent}%</span>
                  </div>
                  <div className="db-monitor-usage-bar">
                    <div
                      className="db-monitor-usage-fill"
                      style={{ width: `${Math.min(100, data.system.host.cpu_percent)}%` }}
                    />
                  </div>
                </div>
                <div className="db-monitor-metric">
                  <div className="db-monitor-metric-label">
                    <span>RAM</span>
                    <span>
                      {humanSize(data.system.host.memory_used_bytes)} / {humanSize(data.system.host.memory_total_bytes)}{" "}
                      ({data.system.host.memory_percent}%)
                    </span>
                  </div>
                  <div className="db-monitor-usage-bar">
                    <div
                      className="db-monitor-usage-fill db-monitor-usage-fill--memory"
                      style={{ width: `${Math.min(100, data.system.host.memory_percent)}%` }}
                    />
                  </div>
                </div>
              </>
            )}

            <div className="db-monitor-metric">
              <div className="db-monitor-metric-label">
                <span>Size</span>
                <span>{humanSize(data.database_size_bytes)}</span>
              </div>
              <div className="db-monitor-usage-bar">
                <div
                  className="db-monitor-usage-fill db-monitor-usage-fill--database"
                  style={{ width: `${data.database_size_bytes != null ? dbSizePct : 0}%` }}
                />
              </div>
            </div>
            <div className="db-monitor-metric">
              <div className="db-monitor-metric-label">
                <span>Ping</span>
                <span>{data.ping_ms != null ? `${data.ping_ms} ms` : "—"}</span>
              </div>
              <div className="db-monitor-usage-bar">
                <div
                  className="db-monitor-usage-fill db-monitor-usage-fill--ping"
                  style={{ width: `${data.ping_ms != null ? pingPct : 0}%` }}
                />
              </div>
            </div>

            {data.system?.available && data.system.process && (
                <>
                  <h4 className="db-monitor-resource-heading">Alpharouter process</h4>
                  <dl className="db-monitor-dl">
                    <div>
                      <dt>PID</dt>
                      <dd>{data.system.process.pid}</dd>
                    </div>
                    <div>
                      <dt>Name</dt>
                      <dd>
                        <code>{data.system.process.name}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>CPU</dt>
                      <dd>{data.system.process.cpu_percent}%</dd>
                    </div>
                    <div>
                      <dt>RSS memory</dt>
                      <dd>{humanSize(data.system.process.memory_rss_bytes)}</dd>
                    </div>
                  </dl>
                </>
            )}
          </div>

          <div className="card">
            <h3>Tables</h3>
            <p className="muted-text" style={{ marginTop: 0 }}>
              Row counts across Alpharouter tables (approx. {totalRows.toLocaleString()} rows total).
            </p>
            <div className="table-wrap table-wrap--phone-scroll">
              <table className="data-table data-table--sticky-first">
                <thead>
                  <tr>
                    <th>Table</th>
                    <th>Name</th>
                    <th className="col-num">Rows</th>
                  </tr>
                </thead>
                <tbody>
                  {data.tables.map((t) => (
                    <tr key={t.name}>
                      <td>{t.label}</td>
                      <td>
                        <code>{t.name}</code>
                      </td>
                      <td className="col-num">
                        {!t.exists && <span className="muted-text">missing</span>}
                        {t.exists && t.error && <span className="muted-text" title={t.error}>error</span>}
                        {t.exists && !t.error && t.row_count != null && t.row_count.toLocaleString()}
                        {t.exists && !t.error && t.row_count == null && "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </AdminPage>
  );
}
