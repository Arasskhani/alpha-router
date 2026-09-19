import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import Tabs from "../../components/Tabs";
import {
  agentStatusTone,
  humanAgentStatus,
  readableDate,
} from "../../lib/agentPlatform";

type ReadinessRow = {
  agent_id: string;
  agent_name: string;
  agent_version_id: string;
  version_number: number;
  status: string;
  ready: boolean;
  validation_errors: string[];
  run_count: number;
  success_rate?: number | null;
};

type EvaluationDataset = {
  id: string;
  agent_id: string;
  agent_name: string;
  slug: string;
  name: string;
  version_number: number;
  status: string;
  minimum_case_count: number;
  is_publish_gate: boolean;
  thresholds: Record<string, unknown>;
  case_count: number;
  activated_at?: string | null;
};

type EvaluationRun = {
  id: string;
  dataset_id: string;
  agent_version_id: string;
  trigger_type: string;
  status: string;
  review_status: string;
  case_count: number;
  passed_case_count: number;
  failed_case_count: number;
  metrics: {
    retrieval_recall_at_10?: number;
    routing_accuracy?: number;
    abstention_rate?: number;
    citation_integrity?: number;
    acl_leak_count?: number;
    case_pass_rate?: number;
  };
  created_at: string;
};

type View = "readiness" | "datasets" | "runs";

export default function AgentEvaluations() {
  const [items, setItems] = useState<ReadinessRow[]>([]);
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "ready" | "attention">("all");
  const [view, setView] = useState<View>("readiness");
  const [showCreate, setShowCreate] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [datasetSlug, setDatasetSlug] = useState("");
  const [minimumCases, setMinimumCases] = useState(100);
  const [requireReview, setRequireReview] = useState(false);
  const [caseImports, setCaseImports] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [readiness, datasetPayload, runPayload] = await Promise.all([
        api<{ items: ReadinessRow[] }>("/api/admin/agents/evaluations"),
        api<{ items: EvaluationDataset[] }>("/api/admin/agents/evaluations/datasets"),
        api<{ items: EvaluationRun[] }>("/api/admin/agents/evaluations/runs"),
      ]);
      setItems(readiness.items);
      setDatasets(datasetPayload.items);
      setRuns(runPayload.items);
      if (!agentId && readiness.items.length) setAgentId(readiness.items[0].agent_id);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(
    () => items.filter((item) =>
      filter === "all" || (filter === "ready" ? item.ready : !item.ready),
    ),
    [items, filter],
  );

  const agents = useMemo(() => {
    const unique = new Map<string, string>();
    items.forEach((item) => unique.set(item.agent_id, item.agent_name));
    return [...unique.entries()];
  }, [items]);

  const createDataset = async () => {
    if (!agentId || !datasetName.trim() || !datasetSlug.trim()) return;
    setWorking(true);
    setError("");
    try {
      await api("/api/admin/agents/evaluations/datasets", {
        method: "POST",
        body: JSON.stringify({
          agent_id: agentId,
          name: datasetName.trim(),
          slug: datasetSlug.trim(),
          minimum_case_count: minimumCases,
          is_publish_gate: true,
          thresholds: { require_human_review: requireReview },
        }),
      });
      setDatasetName("");
      setDatasetSlug("");
      setShowCreate(false);
      setView("datasets");
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  };

  const importCases = async (datasetId: string) => {
    setWorking(true);
    setError("");
    try {
      const cases = JSON.parse(caseImports[datasetId] || "[]");
      if (!Array.isArray(cases)) throw new Error("Cases JSON must be an array.");
      await api(`/api/admin/agents/evaluations/datasets/${encodeURIComponent(datasetId)}/cases`, {
        method: "PUT",
        body: JSON.stringify({ cases }),
      });
      setCaseImports((current) => ({ ...current, [datasetId]: "" }));
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  };

  const activateDataset = async (datasetId: string) => {
    setWorking(true);
    setError("");
    try {
      await api(`/api/admin/agents/evaluations/datasets/${encodeURIComponent(datasetId)}/activate`, {
        method: "POST",
      });
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  };

  const reviewRun = async (runId: string, approved: boolean) => {
    setWorking(true);
    setError("");
    try {
      await api(`/api/admin/agents/evaluations/runs/${encodeURIComponent(runId)}/review`, {
        method: "POST",
        body: JSON.stringify({
          approved,
          notes: approved ? "Approved from Agent Evaluations" : "Rejected from Agent Evaluations",
        }),
      });
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  };

  return (
    <AdminPage
      title="Agent Evaluations"
      actions={(
        <>
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate((value) => !value)}>
            New dataset
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void load()}>Refresh</button>
        </>
      )}
    >
      <p className="agent-page-lead">
        Versioned bilingual golden sets, deterministic scorecards, independent review, and
        fail-closed publish gates.
      </p>
      {error ? <div className="error" role="alert">{error}</div> : null}
      {showCreate ? (
        <section className="agent-hold-panel">
          <div>
            <h2>Create publish-gate dataset</h2>
            <p>Active gates require Persian and English cases across routing, retrieval, citation, abstention, ACL, and injection.</p>
          </div>
          <div className="agent-hold-form">
            <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
              {agents.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
            <input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="Dataset name" />
            <input value={datasetSlug} onChange={(event) => setDatasetSlug(event.target.value)} placeholder="dataset-slug" />
            <input type="number" min={1} max={10000} value={minimumCases} onChange={(event) => setMinimumCases(Number(event.target.value) || 1)} />
            <label className="agent-evaluation-checkbox">
              <input type="checkbox" checked={requireReview} onChange={(event) => setRequireReview(event.target.checked)} />
              Require independent human review
            </label>
            <button type="button" className="btn btn-primary" disabled={working} onClick={() => void createDataset()}>
              Create draft
            </button>
          </div>
        </section>
      ) : null}
      <Tabs
        className="agent-filter-tabs"
        idBase="evaluations-view"
        ariaLabel="Evaluation views"
        items={(["readiness", "datasets", "runs"] as const).map((value) => ({
          id: value,
          label: (
            <>
              {humanAgentStatus(value)}
              <span>{value === "readiness" ? items.length : value === "datasets" ? datasets.length : runs.length}</span>
            </>
          ),
        }))}
        value={view}
        onChange={setView}
        tabClassName={(_id, active) => (active ? "is-active" : "")}
      />
      {view === "readiness" ? (
        <>
      <Tabs
        className="agent-filter-tabs"
        idBase="evaluations-filter"
        ariaLabel="Readiness filter"
        items={(["all", "ready", "attention"] as const).map((value) => ({
          id: value,
          label: (
            <>
              {humanAgentStatus(value)}
              <span>
                {value === "all"
                  ? items.length
                  : items.filter((item) => value === "ready" ? item.ready : !item.ready).length}
              </span>
            </>
          ),
        }))}
        value={filter}
        onChange={setFilter}
        tabClassName={(_id, active) => (active ? "is-active" : "")}
      />
      <div className="table-wrap" aria-busy={loading}>
        <table>
          <thead>
            <tr><th>Agent version</th><th>Lifecycle</th><th>Policy check</th><th>Runs</th><th>Success</th><th>Details</th></tr>
          </thead>
          <tbody>
            {visible.map((item) => (
              <tr key={item.agent_version_id}>
                <td><strong>{item.agent_name}</strong><small className="agent-table-sub">v{item.version_number}</small></td>
                <td><span className={`agent-status ${agentStatusTone(item.status)}`}>{humanAgentStatus(item.status)}</span></td>
                <td>
                  <span className={`agent-status ${item.ready ? "is-success" : "is-danger"}`}>
                    {item.ready ? "Ready" : `${item.validation_errors.length} issue${item.validation_errors.length === 1 ? "" : "s"}`}
                  </span>
                </td>
                <td>{item.run_count}</td>
                <td>{item.success_rate == null ? "No data" : `${item.success_rate}%`}</td>
                <td>
                  {item.validation_errors.length ? (
                    <details className="agent-inline-details">
                      <summary>Validation</summary>
                      <ul>{item.validation_errors.map((message) => <li key={message}>{message}</li>)}</ul>
                    </details>
                  ) : (
                    <Link to="/admin/agents/studio" className="agent-inline-link">Open Studio</Link>
                  )}
                </td>
              </tr>
            ))}
            {!loading && visible.length === 0 ? <tr><td colSpan={6}>No evaluation rows match this view.</td></tr> : null}
          </tbody>
        </table>
      </div>
        </>
      ) : null}
      {view === "datasets" ? (
        <div className="table-wrap" aria-busy={loading}>
          <table>
            <thead>
              <tr><th>Dataset</th><th>Agent</th><th>Lifecycle</th><th>Cases</th><th>Gate</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {datasets.map((dataset) => (
                <tr key={dataset.id}>
                  <td><strong>{dataset.name}</strong><small className="agent-table-sub">{dataset.slug} · v{dataset.version_number}</small></td>
                  <td>{dataset.agent_name}</td>
                  <td><span className={`agent-status ${agentStatusTone(dataset.status)}`}>{humanAgentStatus(dataset.status)}</span></td>
                  <td>{dataset.case_count} / {dataset.minimum_case_count}</td>
                  <td>{dataset.is_publish_gate ? "Required" : "Advisory"}</td>
                  <td>
                    {dataset.status === "draft" ? (
                      <details className="agent-inline-details agent-evaluation-import">
                        <summary>Import cases</summary>
                        <textarea
                          value={caseImports[dataset.id] || ""}
                          onChange={(event) => setCaseImports((current) => ({ ...current, [dataset.id]: event.target.value }))}
                          placeholder='[{"case_key":"...","category":"routing","language":"fa","prompt":"...","expected":{...}}]'
                          rows={7}
                        />
                        <div>
                          <button type="button" className="btn btn-ghost" disabled={working} onClick={() => void importCases(dataset.id)}>Replace cases</button>
                          <button type="button" className="btn btn-primary" disabled={working || dataset.case_count < dataset.minimum_case_count} onClick={() => void activateDataset(dataset.id)}>Activate gate</button>
                        </div>
                      </details>
                    ) : (
                      <small>{dataset.activated_at ? readableDate(dataset.activated_at) : "—"}</small>
                    )}
                  </td>
                </tr>
              ))}
              {!loading && datasets.length === 0 ? <tr><td colSpan={6}>No evaluation datasets exist yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      ) : null}
      {view === "runs" ? (
        <div className="table-wrap" aria-busy={loading}>
          <table>
            <thead>
              <tr><th>Run</th><th>Status</th><th>Cases</th><th>Recall@10</th><th>Routing</th><th>Abstention</th><th>ACL leaks</th><th>Review</th></tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td><code>{run.id.slice(0, 8)}</code><small className="agent-table-sub">{humanAgentStatus(run.trigger_type)} · {readableDate(run.created_at)}</small></td>
                  <td><span className={`agent-status ${agentStatusTone(run.status)}`}>{humanAgentStatus(run.status)}</span></td>
                  <td>{run.passed_case_count}/{run.case_count}<small className="agent-table-sub">{run.failed_case_count} failed</small></td>
                  <td>{run.metrics.retrieval_recall_at_10 == null ? "—" : `${Math.round(run.metrics.retrieval_recall_at_10 * 100)}%`}</td>
                  <td>{run.metrics.routing_accuracy == null ? "—" : `${Math.round(run.metrics.routing_accuracy * 100)}%`}</td>
                  <td>{run.metrics.abstention_rate == null ? "—" : `${Math.round(run.metrics.abstention_rate * 100)}%`}</td>
                  <td>{run.metrics.acl_leak_count ?? "—"}</td>
                  <td>
                    {run.status === "awaiting_review" ? (
                      <span className="agent-evaluation-review-actions">
                        <button type="button" className="btn btn-primary" disabled={working} onClick={() => void reviewRun(run.id, true)}>Approve</button>
                        <button type="button" className="btn btn-ghost" disabled={working} onClick={() => void reviewRun(run.id, false)}>Reject</button>
                      </span>
                    ) : humanAgentStatus(run.review_status)}
                  </td>
                </tr>
              ))}
              {!loading && runs.length === 0 ? <tr><td colSpan={8}>No evaluation runs have been submitted.</td></tr> : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </AdminPage>
  );
}
