import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
function humanSize(bytes) {
    if (bytes == null)
        return "—";
    let v = bytes;
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v.toFixed(1)} ${units[i]}`;
}
function engineLabel(engine) {
    if (engine === "sqlite")
        return "SQLite";
    if (engine === "postgresql")
        return "PostgreSQL";
    return engine;
}
/** Soft cap for database size bar (same idea as Storage page). */
const DB_SIZE_VIZ_CAP_BYTES = 5 * 1024 * 1024 * 1024;
/** Ping bar fills at this latency (ms). */
const PING_VIZ_CAP_MS = 200;
function barPercent(value, cap) {
    if (cap <= 0)
        return 0;
    return Math.min(100, Math.round((value / cap) * 1000) / 10);
}
export default function DatabaseMonitor() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const payload = await api("/api/admin/database/monitor");
            setData(payload);
        }
        catch (e) {
            setError(String(e));
            setData(null);
        }
        finally {
            setLoading(false);
        }
    }, []);
    useEffect(() => {
        void load();
    }, [load]);
    const totalRows = data?.tables.reduce((sum, t) => sum + (typeof t.row_count === "number" ? t.row_count : 0), 0) ?? 0;
    const dbSizeBytes = data?.database_size_bytes ?? 0;
    const dbSizePct = barPercent(dbSizeBytes, DB_SIZE_VIZ_CAP_BYTES);
    const pingMs = data?.ping_ms ?? 0;
    const pingPct = data?.ping_ms != null ? barPercent(pingMs, PING_VIZ_CAP_MS) : 0;
    return (_jsxs(AdminPage, { title: "Database", actions: _jsx("button", { type: "button", className: "btn btn-secondary btn-readonly-ok", onClick: () => void load(), disabled: loading, children: loading ? "Refreshing…" : "Refresh" }), children: [_jsx("p", { className: "muted-text", children: "Read-only monitoring for the Alpharouter PostgreSQL database and for CPU/RAM on the host (or container) running this API process. No queries or schema changes from this page." }), error && _jsx("p", { className: "alert alert-error", children: error }), data?.error && data.connected === false && (_jsx("p", { className: "alert alert-error", children: data.error })), data && (_jsxs(_Fragment, { children: [_jsxs("div", { className: "db-monitor-status-row", children: [_jsx("span", { className: `db-monitor-pill ${data.connected ? "db-monitor-pill--ok" : "db-monitor-pill--bad"}`, children: data.connected ? "Connected" : "Unreachable" }), _jsx("span", { className: "db-monitor-pill db-monitor-pill--muted", children: engineLabel(data.engine) })] }), _jsxs("div", { className: "card db-monitor-overview", children: [_jsx("h3", { children: "Overview" }), _jsxs("dl", { className: "db-monitor-dl", children: [data.engine === "postgresql" && (_jsxs("div", { children: [_jsx("dt", { children: "Other sessions" }), _jsx("dd", { children: data.postgres_connections ?? "—" })] })), data.engine === "sqlite" && data.database_file_path && (_jsxs("div", { className: "db-monitor-dl-wide", children: [_jsx("dt", { children: "File path" }), _jsx("dd", { children: _jsx("code", { children: data.database_file_path }) })] })), _jsxs("div", { className: "db-monitor-dl-wide", children: [_jsx("dt", { children: "Connection (masked)" }), _jsx("dd", { children: _jsx("code", { children: data.database_url_masked }) })] })] })] }), _jsxs("div", { className: "card db-monitor-resources", children: [_jsx("h3", { children: "CPU, memory & database" }), _jsx("p", { className: "muted-text", style: { marginTop: 0 }, children: "Snapshot at refresh. Host = machine or Docker container; database size/ping = current engine; process = this Alpharouter API worker." }), _jsx("div", { className: "db-monitor-metric db-monitor-metric--static", children: _jsxs("div", { className: "db-monitor-metric-label", children: [_jsx("span", { children: "Version" }), _jsx("span", { children: data.version || "—" })] }) }), _jsx("div", { className: "db-monitor-metric db-monitor-metric--static", children: _jsxs("div", { className: "db-monitor-metric-label", children: [_jsx("span", { children: "Database" }), _jsx("span", { children: data.database_name || "—" })] }) }), data.system && !data.system.available && (_jsx("p", { className: "muted-text", children: data.system.error || "System metrics unavailable." })), data.system?.available && data.system.host && (_jsxs(_Fragment, { children: [_jsx("h4", { className: "db-monitor-resource-heading", children: "Host" }), _jsxs("div", { className: "db-monitor-metric", children: [_jsxs("div", { className: "db-monitor-metric-label", children: [_jsx("span", { children: "CPU" }), _jsxs("span", { children: [data.system.host.cpu_percent, "%"] })] }), _jsx("div", { className: "db-monitor-usage-bar", children: _jsx("div", { className: "db-monitor-usage-fill", style: { width: `${Math.min(100, data.system.host.cpu_percent)}%` } }) })] }), _jsxs("div", { className: "db-monitor-metric", children: [_jsxs("div", { className: "db-monitor-metric-label", children: [_jsx("span", { children: "RAM" }), _jsxs("span", { children: [humanSize(data.system.host.memory_used_bytes), " / ", humanSize(data.system.host.memory_total_bytes), " ", "(", data.system.host.memory_percent, "%)"] })] }), _jsx("div", { className: "db-monitor-usage-bar", children: _jsx("div", { className: "db-monitor-usage-fill db-monitor-usage-fill--memory", style: { width: `${Math.min(100, data.system.host.memory_percent)}%` } }) })] })] })), _jsxs("div", { className: "db-monitor-metric", children: [_jsxs("div", { className: "db-monitor-metric-label", children: [_jsx("span", { children: "Size" }), _jsx("span", { children: humanSize(data.database_size_bytes) })] }), _jsx("div", { className: "db-monitor-usage-bar", children: _jsx("div", { className: "db-monitor-usage-fill db-monitor-usage-fill--database", style: { width: `${data.database_size_bytes != null ? dbSizePct : 0}%` } }) })] }), _jsxs("div", { className: "db-monitor-metric", children: [_jsxs("div", { className: "db-monitor-metric-label", children: [_jsx("span", { children: "Ping" }), _jsx("span", { children: data.ping_ms != null ? `${data.ping_ms} ms` : "—" })] }), _jsx("div", { className: "db-monitor-usage-bar", children: _jsx("div", { className: "db-monitor-usage-fill db-monitor-usage-fill--ping", style: { width: `${data.ping_ms != null ? pingPct : 0}%` } }) })] }), data.system?.available && data.system.process && (_jsxs(_Fragment, { children: [_jsx("h4", { className: "db-monitor-resource-heading", children: "Alpharouter process" }), _jsxs("dl", { className: "db-monitor-dl", children: [_jsxs("div", { children: [_jsx("dt", { children: "PID" }), _jsx("dd", { children: data.system.process.pid })] }), _jsxs("div", { children: [_jsx("dt", { children: "Name" }), _jsx("dd", { children: _jsx("code", { children: data.system.process.name }) })] }), _jsxs("div", { children: [_jsx("dt", { children: "CPU" }), _jsxs("dd", { children: [data.system.process.cpu_percent, "%"] })] }), _jsxs("div", { children: [_jsx("dt", { children: "RSS memory" }), _jsx("dd", { children: humanSize(data.system.process.memory_rss_bytes) })] })] })] }))] }), _jsxs("div", { className: "card", children: [_jsx("h3", { children: "Tables" }), _jsxs("p", { className: "muted-text", style: { marginTop: 0 }, children: ["Row counts across Alpharouter tables (approx. ", totalRows.toLocaleString(), " rows total)."] }), _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Table" }), _jsx("th", { children: "Name" }), _jsx("th", { className: "col-num", children: "Rows" })] }) }), _jsx("tbody", { children: data.tables.map((t) => (_jsxs("tr", { children: [_jsx("td", { children: t.label }), _jsx("td", { children: _jsx("code", { children: t.name }) }), _jsxs("td", { className: "col-num", children: [!t.exists && _jsx("span", { className: "muted-text", children: "missing" }), t.exists && t.error && _jsx("span", { className: "muted-text", title: t.error, children: "error" }), t.exists && !t.error && t.row_count != null && t.row_count.toLocaleString(), t.exists && !t.error && t.row_count == null && "—"] })] }, t.name))) })] })] })] }))] }));
}
