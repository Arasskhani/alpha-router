import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import { runtimeHealthHref } from "../../lib/agentActivity";

type OverviewPayload = {
  agents: { total: number; active: number; draft: number; in_review: number };
  knowledge: {
    bases: number;
    documents: number;
    review: number;
    failed_jobs: number;
  };
  tools: { total: number; active: number; in_review: number };
  runs_24h: { total: number; succeeded: number; blocked: number; failed: number };
  pending_approvals: number;
};

const emptyOverview: OverviewPayload = {
  agents: { total: 0, active: 0, draft: 0, in_review: 0 },
  knowledge: { bases: 0, documents: 0, review: 0, failed_jobs: 0 },
  tools: { total: 0, active: 0, in_review: 0 },
  runs_24h: { total: 0, succeeded: 0, blocked: 0, failed: 0 },
  pending_approvals: 0,
};

export default function AgentsOverview() {
  const [data, setData] = useState<OverviewPayload>(emptyOverview);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await api<OverviewPayload>("/api/admin/agents/overview"));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const successRate = data.runs_24h.total
    ? Math.round((data.runs_24h.succeeded / data.runs_24h.total) * 100)
    : 0;

  return (
    <AdminPage
      title="Agents & Knowledge"
      actions={
        <button type="button" className="btn btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      }
    >
      <p className="agent-page-lead">
        Govern specialist Agents, approved knowledge, tool contracts, and runtime evidence.
      </p>
      {error ? <div className="error">{error}</div> : null}
      <div className="agent-kpi-grid" aria-busy={loading}>
        <Link className="agent-kpi-card" to="/admin/agents/studio">
          <span>Agents</span>
          <strong>{data.agents.active}</strong>
          <small>
            {data.agents.total} total · {data.agents.in_review} awaiting review
          </small>
        </Link>
        <Link className="agent-kpi-card" to="/admin/knowledge">
          <span>Knowledge</span>
          <strong>{data.knowledge.documents}</strong>
          <small>
            {data.knowledge.bases} bases · {data.knowledge.failed_jobs} failed jobs
          </small>
        </Link>
        <Link className="agent-kpi-card" to="/admin/agent-tools">
          <span>Tools</span>
          <strong>{data.tools.active}</strong>
          <small>
            {data.tools.total} registered · {data.tools.in_review} awaiting review
          </small>
        </Link>
        <Link className="agent-kpi-card" to="/admin/agent-approvals">
          <span>Approvals</span>
          <strong>{data.pending_approvals}</strong>
          <small>Agent, knowledge, binding, and tool decisions</small>
        </Link>
      </div>

      <section className="agent-section-card">
        <div className="agent-section-card__head">
          <div>
            <h2>Runtime health · last 24 hours</h2>
            <p>Metadata-only Agent turn outcomes; prompts and provider output are excluded.</p>
          </div>
          <Link className="btn btn-ghost" to="/admin/agent-activity">
            View audit
          </Link>
        </div>
        <div className="agent-runtime-summary">
          <Link to={runtimeHealthHref()}>
            <strong>{data.runs_24h.total}</strong>
            <span>Turns</span>
          </Link>
          <div>
            <strong>{successRate}%</strong>
            <span>Success rate</span>
          </div>
          <Link to={runtimeHealthHref("blocked")}>
            <strong>{data.runs_24h.blocked}</strong>
            <span>Guardrail blocked</span>
          </Link>
          <Link to={runtimeHealthHref("failed")}>
            <strong>{data.runs_24h.failed}</strong>
            <span>Failed</span>
          </Link>
        </div>
      </section>

      <div className="agent-quick-grid">
        <Link to="/admin/agents/studio" className="agent-quick-card">
          <strong>Build an Agent</strong>
          <span>Create a draft, bind policies and knowledge, then submit it for review.</span>
        </Link>
        <Link to="/admin/knowledge" className="agent-quick-card">
          <strong>Curate knowledge</strong>
          <span>Upload governed documents, monitor ingestion, and publish immutable releases.</span>
        </Link>
        <Link to="/admin/agent-evaluations" className="agent-quick-card">
          <strong>Check readiness</strong>
          <span>Validate policy completeness and inspect production success signals.</span>
        </Link>
      </div>
    </AdminPage>
  );
}
