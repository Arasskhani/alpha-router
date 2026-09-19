import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import { useConfirm } from "../../context/ConfirmContext";
import {
  agentStatusTone,
  humanAgentStatus,
  readableDate,
} from "../../lib/agentPlatform";

type ApprovalItem = {
  id: string;
  kind: "agent_version" | "tool_version" | "knowledge_binding" | "document_version";
  title: string;
  status: string;
  submitted_by_user_id?: number | null;
  submitted_by_username?: string | null;
  submitted_by_display_name?: string | null;
  created_at: string;
};

function submittedByLabel(item: ApprovalItem): string {
  const name = (item.submitted_by_display_name || item.submitted_by_username || "").trim();
  if (name) return name;
  if (item.submitted_by_user_id) return `User #${item.submitted_by_user_id}`;
  return "";
}

export default function AgentApprovals() {
  const { confirm, prompt } = useConfirm();
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await api<{ items: ApprovalItem[] }>("/api/admin/agents/approvals");
      setItems(payload.items);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(
    () => filter === "all" ? items : items.filter((item) => item.kind === filter),
    [items, filter],
  );

  async function approve(item: ApprovalItem) {
    let path = "";
    let body: string | undefined;
    if (item.kind === "agent_version") {
      const ok = await confirm({
        title: "Publish Agent version",
        message: `Publish ${item.title}? This makes the version active for users who can access the Agent.`,
        confirmLabel: "Publish",
      });
      if (!ok) return;
      path = `/api/admin/agents/versions/${item.id}/publish`;
    } else if (item.kind === "tool_version") {
      const ok = await confirm({
        title: "Publish Tool version",
        message: `Publish ${item.title}?`,
        confirmLabel: "Publish",
      });
      if (!ok) return;
      path = `/api/admin/agents/tool-versions/${item.id}/publish`;
    } else if (item.kind === "knowledge_binding") {
      const reason = await prompt({
        title: "Approve knowledge binding",
        message: `Approve binding for ${item.title}?`,
        promptLabel: "Approval reason",
        promptDefault: "Reviewed and approved",
        confirmLabel: "Approve",
      });
      if (!reason?.trim()) return;
      path = item.status === "pending_domain_approval"
        ? `/api/admin/agents/bindings/${item.id}/approve-domain`
        : `/api/admin/agents/bindings/${item.id}/approve-knowledge`;
      body = JSON.stringify({ reason: reason.trim() });
    } else {
      const reason = await prompt({
        title: "Approve document version",
        message: `Approve ${item.title} for Knowledge releases?`,
        promptLabel: "Document review reason",
        promptDefault: "Reviewed and approved",
        confirmLabel: "Approve",
      });
      if (!reason?.trim()) return;
      path = `/api/admin/knowledge/document-versions/${item.id}/approve`;
      body = JSON.stringify({ reason: reason.trim() });
    }
    setBusyId(item.id);
    setError("");
    setFlash("");
    try {
      await api(path, { method: "POST", body });
      setFlash(`${item.title} approved.`);
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusyId("");
    }
  }

  const filters = [
    ["all", "All"],
    ["agent_version", "Agents"],
    ["knowledge_binding", "Bindings"],
    ["document_version", "Documents"],
    ["tool_version", "Tools"],
  ] as const;

  return (
    <AdminPage
      title="Approvals"
      actions={<button type="button" className="btn btn-ghost" onClick={() => void load()}>Refresh</button>}
    >
      <p className="agent-page-lead">
        Maker-checker queue for version publication and sensitive knowledge access.
        Super Admin can complete both maker and checker steps when needed.
      </p>
      {error ? <div className="error" role="alert">{error}</div> : null}
      {flash ? <div className="success">{flash}</div> : null}
      <div className="agent-filter-tabs" role="tablist">
        {filters.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={filter === value ? "is-active" : ""}
            onClick={() => setFilter(value)}
          >
            {label}
            <span>{value === "all" ? items.length : items.filter((item) => item.kind === value).length}</span>
          </button>
        ))}
      </div>
      <div className="approval-grid" aria-busy={loading}>
        {visible.map((item) => (
          <article className="approval-card" key={`${item.kind}-${item.id}`}>
            <div>
              <span className="approval-card__kind">{humanAgentStatus(item.kind)}</span>
              <h2>{item.title}</h2>
              <p>
                Submitted {readableDate(item.created_at)}
                {submittedByLabel(item) ? ` · ${submittedByLabel(item)}` : ""}
              </p>
            </div>
            <div className="approval-card__actions">
              <span className={`agent-status ${agentStatusTone(item.status)}`}>
                {humanAgentStatus(item.status)}
              </span>
              <button
                type="button"
                className="btn"
                disabled={!!busyId}
                onClick={() => void approve(item)}
              >
                {busyId === item.id ? "Approving…" : "Approve"}
              </button>
            </div>
          </article>
        ))}
        {!loading && visible.length === 0 ? (
          <div className="agent-empty-state"><h2>Approval queue is clear</h2><p>No pending items match this view.</p></div>
        ) : null}
      </div>
    </AdminPage>
  );
}
