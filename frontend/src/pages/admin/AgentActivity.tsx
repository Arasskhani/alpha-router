import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import {
  activityApiPath,
  humanActivityEventType,
  nextActivitySearch,
  parseActivityQuery,
} from "../../lib/agentActivity";
import {
  agentStatusTone,
  humanAgentStatus,
  readableDate,
} from "../../lib/agentPlatform";

type ActivityItem = {
  id: string;
  source: "agent" | "tool" | "knowledge" | "governance" | "runtime";
  event_type: string;
  resource_id?: string | null;
  version_id?: string | null;
  actor_user_id?: number | null;
  reason?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

type LegalHold = {
  id: string;
  resource_type: string;
  resource_id: string;
  status: "active" | "released";
  reason: string;
  placed_by_user_id?: number | null;
  placed_at: string;
};

type AuditVerification = {
  valid: boolean;
  event_count: number;
  first_invalid_event_id?: string | null;
  head_hash?: string | null;
};

function payloadText(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value : "";
}

export default function AgentActivity() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activityQuery = useMemo(() => parseActivityQuery(searchParams), [searchParams]);
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [holds, setHolds] = useState<LegalHold[]>([]);
  const [audit, setAudit] = useState<AuditVerification | null>(null);
  const [query, setQuery] = useState("");
  const [holdType, setHoldType] = useState("knowledge_document");
  const [holdResourceId, setHoldResourceId] = useState("");
  const [holdReason, setHoldReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [activityPayload, holdPayload, auditPayload] = await Promise.all([
        api<{ items: ActivityItem[] }>(activityApiPath(activityQuery)),
        api<{ items: LegalHold[] }>("/api/admin/agents/governance/holds?status=active"),
        api<AuditVerification>("/api/admin/agents/governance/audit/verify"),
      ]);
      setItems(activityPayload.items);
      setHolds(holdPayload.items);
      setAudit(auditPayload);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [activityQuery]);

  const createHold = async () => {
    if (!holdResourceId.trim() || holdReason.trim().length < 3) return;
    setWorking(true);
    setError("");
    try {
      await api("/api/admin/agents/governance/holds", {
        method: "POST",
        body: JSON.stringify({
          resource_type: holdType,
          resource_id: holdResourceId.trim(),
          reason: holdReason.trim(),
        }),
      });
      setHoldResourceId("");
      setHoldReason("");
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  };

  const releaseHold = async (holdId: string) => {
    setWorking(true);
    setError("");
    try {
      await api(`/api/admin/agents/governance/holds/${encodeURIComponent(holdId)}/release`, {
        method: "POST",
        body: JSON.stringify({ reason: "Released from Audit" }),
      });
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  };

  const runRetention = async () => {
    setWorking(true);
    setError("");
    try {
      await api("/api/admin/agents/governance/retention/run", { method: "POST" });
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setWorking(false);
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      if (!needle) return true;
      const agentName = payloadText(item.payload, "agent_name");
      return `${item.event_type} ${item.resource_id || ""} ${item.reason || ""} ${agentName}`
        .toLowerCase()
        .includes(needle);
    });
  }, [items, query]);

  function updateActivityQuery(patch: Partial<typeof activityQuery>) {
    setSearchParams(nextActivitySearch(searchParams, patch), { replace: true });
  }

  return (
    <AdminPage
      title="Audit"
      actions={(
        <>
          <button type="button" className="btn btn-ghost" disabled={working} onClick={() => void runRetention()}>
            Run retention
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void load()}>Refresh</button>
        </>
      )}
    >
      <p className="agent-page-lead">
        Append-only lifecycle evidence and metadata-only runtime outcomes.
        {activityQuery.sinceHours
          ? ` Showing the last ${activityQuery.sinceHours} hours.`
          : ""}
      </p>
      {error ? <div className="error" role="alert">{error}</div> : null}
      <section className="agent-governance-summary" aria-label="Governance status">
        <div>
          <span>Audit chain</span>
          <strong className={`agent-status ${audit?.valid ? "is-success" : "is-danger"}`}>
            {audit ? (audit.valid ? `Verified · ${audit.event_count} events` : "Integrity failure") : "Checking…"}
          </strong>
        </div>
        <div>
          <span>Active legal holds</span>
          <strong>{holds.length}</strong>
        </div>
      </section>
      <section className="agent-hold-panel">
        <div>
          <h2>Place legal hold</h2>
          <p>Held resources are excluded from chat and Knowledge retention jobs.</p>
        </div>
        <div className="agent-hold-form">
          <select value={holdType} onChange={(event) => setHoldType(event.target.value)}>
            <option value="knowledge_document">Knowledge document</option>
            <option value="knowledge_document_version">Document version</option>
            <option value="knowledge_base">Knowledge base</option>
            <option value="chat_session">Chat session</option>
            <option value="agent_run">Agent run</option>
            <option value="agent">Agent</option>
          </select>
          <input
            value={holdResourceId}
            onChange={(event) => setHoldResourceId(event.target.value)}
            placeholder="Resource ID"
          />
          <input
            value={holdReason}
            onChange={(event) => setHoldReason(event.target.value)}
            placeholder="Reason"
          />
          <button
            type="button"
            className="btn btn-primary"
            disabled={working || !holdResourceId.trim() || holdReason.trim().length < 3}
            onClick={() => void createHold()}
          >
            Place hold
          </button>
        </div>
        {holds.length ? (
          <div className="agent-hold-list">
            {holds.map((hold) => (
              <div key={hold.id}>
                <span>
                  <strong>{humanAgentStatus(hold.resource_type)}</strong>
                  <code>{hold.resource_id}</code>
                  <small>{hold.reason} · {readableDate(hold.placed_at)}</small>
                </span>
                <button type="button" className="btn btn-ghost" disabled={working} onClick={() => void releaseHold(hold.id)}>
                  Release
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </section>
      <div className="agent-audit-toolbar">
        <input type="search" placeholder="Search event or resource…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select
          value={activityQuery.source}
          onChange={(e) => updateActivityQuery({ source: e.target.value })}
        >
          <option value="all">All sources</option>
          <option value="agent">Agent lifecycle</option>
          <option value="tool">Tool registry</option>
          <option value="knowledge">Knowledge lifecycle</option>
          <option value="governance">Governance</option>
          <option value="runtime">Runtime</option>
        </select>
        {activityQuery.source === "runtime" ? (
          <select
            value={activityQuery.status}
            onChange={(e) => updateActivityQuery({ status: e.target.value })}
          >
            <option value="">All statuses</option>
            <option value="blocked">Blocked</option>
            <option value="failed">Failed</option>
            <option value="succeeded">Succeeded</option>
            <option value="abstained">Abstained</option>
            <option value="cancelled">Cancelled</option>
          </select>
        ) : null}
        {activityQuery.sinceHours ? (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => updateActivityQuery({ sinceHours: "" })}
          >
            Last {activityQuery.sinceHours}h · Clear
          </button>
        ) : null}
      </div>
      <div className="audit-timeline" aria-busy={loading}>
        {visible.map((item) => {
          const terminal = item.event_type.split(".").at(-1) || item.source;
          const agentName = payloadText(item.payload, "agent_name");
          return (
            <article key={`${item.source}-${item.id}`} className="audit-event">
              <span className={`audit-event__dot ${agentStatusTone(terminal)}`} aria-hidden />
              <div className="audit-event__body">
                <div>
                  <strong>{humanActivityEventType(item.event_type)}</strong>
                  <span className="agent-status is-neutral">{humanAgentStatus(item.source)}</span>
                </div>
                <p>
                  {agentName || (item.resource_id ? <code>{item.resource_id}</code> : "Platform event")}
                  {item.actor_user_id ? ` · actor ${item.actor_user_id}` : ""}
                  {item.reason ? ` · ${humanAgentStatus(item.reason)}` : ""}
                </p>
                {Object.keys(item.payload || {}).length ? (
                  <details className="agent-inline-details">
                    <summary>Evidence</summary>
                    <pre>{JSON.stringify(item.payload, null, 2)}</pre>
                  </details>
                ) : null}
              </div>
              <time>{readableDate(item.created_at)}</time>
            </article>
          );
        })}
        {!loading && visible.length === 0 ? (
          <div className="agent-empty-state">
            <h2>No activity found</h2>
            <p>Try another source, status, or time range.</p>
          </div>
        ) : null}
      </div>
    </AdminPage>
  );
}
