import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import { api, formatApiError } from "../../api";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";

type ProjectUsageRow = {
  id: string;
  name: string;
  status: string;
  visibility: string;
  costUsd: number;
  mediaCostUsd: number;
  requests: number;
  tokens: number;
};

const PERIODS = [
  { value: "day", label: "Last 24 hours" },
  { value: "week", label: "Last 7 days" },
  { value: "month", label: "Last 30 days" },
];

function formatUsd(n: number): string {
  return `$${n.toFixed(2)}`;
}

export default function ProjectUsage() {
  const navigate = useNavigate();
  const [period, setPeriod] = useState("month");
  const [rows, setRows] = useState<ProjectUsageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<{ projects: ProjectUsageRow[] }>(`/api/admin/project-usage?period=${encodeURIComponent(period)}`)
      .then((data) => {
        if (active) setRows(data.projects ?? []);
      })
      .catch((err) => {
        if (active) setError(formatApiError(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [period]);

  return (
    <AdminPage
      title="Projects"
      actions={
        <label className="form-field form-field--inline">
          <span>Period</span>
          <select className="input" value={period} onChange={(e) => setPeriod(e.target.value)}>
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
      }
    >
      <p className="muted-text">
        Organization project spend for the selected period. Open Activity to see the same Overview / Trends / Explore
        charts used elsewhere, scoped to one project.
      </p>
      {error ? <p className="flash flash-error">{error}</p> : null}
      {loading ? <div className="loading-state">Loading…</div> : null}
      <div className="table-wrap table-wrap--phone-scroll">
        <table className="data-table data-table--sticky-first">
          <thead>
            <tr>
              <th>Project</th>
              <th>Status</th>
              <th>Visibility</th>
              <th>Cost</th>
              <th>Media</th>
              <th>Requests</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td>
                <td>{row.status}</td>
                <td>{row.visibility}</td>
                <td>{formatUsd(row.costUsd)}</td>
                <td>{formatUsd(row.mediaCostUsd)}</td>
                <td>{row.requests}</td>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => navigate(`/app/projects/${row.id}/activity`)}
                  >
                    {USAGE_AND_ACTIVITY_LABEL}
                  </button>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty-state">
                  No projects yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </AdminPage>
  );
}
