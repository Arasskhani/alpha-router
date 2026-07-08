import { Link } from "react-router-dom";

export type SlowModelRow = {
  model_id: string;
  requests: number;
  avg_ms: number;
  p95_ms: number;
  error_pct: number;
};

type Props = {
  rows: SlowModelRow[];
  thresholdMs: number;
};

function fmtMs(ms: number) {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export default function OperationsSlowModelsTable({ rows, thresholdMs }: Props) {
  return (
    <div className="card operations-slow-models">
      <h3>Slowest models (by P95)</h3>
      <p className="muted-text" style={{ marginTop: 0 }}>
        Models with at least 3 requests in the last 24h, sorted by P95 latency. Slow request threshold:{" "}
        <strong>{thresholdMs / 1000}s</strong>.{" "}
        <Link to="/admin/logs">Open API Logs</Link> to inspect individual calls.
      </p>
      {rows.length === 0 ? (
        <p className="muted-text">Not enough request data yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Model</th>
                <th className="col-num">Requests</th>
                <th className="col-num">Avg</th>
                <th className="col-num">P95</th>
                <th className="col-num">Errors</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.model_id}>
                  <td>
                    <code title={r.model_id}>{r.model_id}</code>
                  </td>
                  <td className="col-num">{r.requests.toLocaleString()}</td>
                  <td className="col-num">{fmtMs(r.avg_ms)}</td>
                  <td className="col-num">{fmtMs(r.p95_ms)}</td>
                  <td className="col-num">{r.error_pct}%</td>
                  <td>
                    <Link
                      to={`/admin/logs?model_id=${encodeURIComponent(r.model_id)}`}
                      className="btn btn-ghost btn-sm"
                    >
                      Logs
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
