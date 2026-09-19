import { useCallback, useEffect, useRef, useState } from "react";

import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import LogFilterCombobox from "../../components/admin/LogFilterCombobox";
import { api, formatApiError } from "../../api";
import { formatLocalDateTime } from "../../lib/dateTime";
import { attachDragScroll } from "../../lib/dragScroll";
import { messageDirectionForText } from "../../lib/textDirection";

type AdminLogEvent = {
  source: AuditSource;
  id: string;
  created_at: string | null;
  actor_user_id: number | null;
  actor_username: string | null;
  actor_email: string | null;
  actor_ip: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  detail: Record<string, unknown> | unknown[] | null;
  outcome: string | null;
  detail_redacted_at: string | null;
};

type ListResponse = {
  items: AdminLogEvent[];
  limit: number;
  offset: number;
  has_more: boolean;
};

type FilterOptions = {
  sources: string[];
  actions: string[];
  resource_types: string[];
  actors: string[];
};

const PAGE_SIZE = 100;

/**
 * The trails the server can read, in the order the picker lists them. The keys
 * are those of `app.services.admin_log_union.SOURCES`; the labels are the
 * words the rest of the admin panel already uses for each domain.
 */
export const AUDIT_SOURCES = [
  ["all", "All trails"],
  ["security", "Security settings"],
  ["agents", "Agents"],
  ["tools", "Agent tools"],
  ["knowledge", "Knowledge"],
  ["governance", "Governance"],
  ["projects", "Projects"],
  ["api_keys", "API keys"],
  ["connections", "Provider connections"],
] as const;

type AuditSource = (typeof AUDIT_SOURCES)[number][0];

const SOURCE_LABEL: Record<string, string> = Object.fromEntries(AUDIT_SOURCES);

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

/** A detail is worth a "View" when it carries anything at all. */
export function hasDetail(detail: AdminLogEvent["detail"]): boolean {
  if (detail == null) return false;
  if (Array.isArray(detail)) return detail.length > 0;
  return Object.keys(detail).length > 0;
}

/** "tls_activate" reads as machine output; "Tls activate" reads as an event. */
function humanAction(value: string): string {
  const spaced = value.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Who the event names, in the form an investigation needs.
 *
 * The username is a copy taken when the event was written, so it still answers
 * "who" after the account is deleted — which is exactly when somebody asks.
 * Events recorded before that copy existed name their actor only by id; the
 * server looks those up while the account exists, and only once an account is
 * permanently deleted is there genuinely no name left to show.
 */
function actorLabel(event: AdminLogEvent): string {
  if (event.actor_username) return event.actor_username;
  if (event.actor_user_id != null) return `User #${event.actor_user_id}`;
  return "—";
}

/**
 * Administrative audit trail.
 *
 * The events behind this page have been recorded since the security settings
 * shipped, and until now there was no way to read them without a database
 * client — while the Admin Guide told operators the trail existed.
 */
export default function AdminLogs() {
  const [items, setItems] = useState<AdminLogEvent[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [source, setSource] = useState<AuditSource>("all");
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const [options, setOptions] = useState<FilterOptions>({ sources: [], actions: [], resource_types: [], actors: [] });
  // The comboboxes are scoped to the trail on screen, so remember which trail
  // the loaded options belong to rather than a bare "loaded" flag.
  const [optionsFor, setOptionsFor] = useState<AuditSource | null>(null);
  const [selected, setSelected] = useState<AdminLogEvent | null>(null);

  const tableScrollRef = useRef<HTMLDivElement | null>(null);

  const buildQuery = useCallback(
    (nextOffset: number) => {
      const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(nextOffset), source });
      if (actor.trim()) q.set("actor", actor.trim());
      if (action.trim()) q.set("action", action.trim());
      if (resourceType.trim()) q.set("resource_type", resourceType.trim());
      if (start) q.set("start_date", start);
      if (end) q.set("end_date", end);
      return q;
    },
    [source, actor, action, resourceType, start, end],
  );

  const load = useCallback(
    async (nextOffset = 0) => {
      setLoading(true);
      setError("");
      try {
        const data = await api<ListResponse>(`/api/admin/admin-logs?${buildQuery(nextOffset)}`);
        setItems(data.items || []);
        setHasMore(!!data.has_more);
        setOffset(nextOffset);
      } catch (err) {
        setError(formatApiError(err));
      } finally {
        setLoading(false);
      }
    },
    [buildQuery],
  );

  useEffect(() => {
    // Fetch the first page once, on mount. The rule wants an effect to talk to
    // an external system rather than set state, and fetching from the server is
    // exactly that - load() only writes state from the request's own callbacks.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the effect's job is the fetch
    void load(0);
    // Filters apply on the Filter button, not on every keystroke, so load must
    // stay out of the dependency array - the same contract as API Logs.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- avoid refetching on every filter keystroke
  }, []);

  useEffect(() => {
    const el = tableScrollRef.current;
    if (!el) return;
    return attachDragScroll(el);
  }, []);

  async function loadOptions() {
    if (optionsFor === source) return;
    try {
      setOptions(await api<FilterOptions>(`/api/admin/admin-logs/filter-options?source=${source}`));
      setOptionsFor(source);
    } catch {
      /* the combobox still accepts free text */
    }
  }

  function clearFilters() {
    setSource("all");
    setActor("");
    setAction("");
    setResourceType("");
    setStart("");
    setEnd("");
  }

  return (
    <AdminPage
      title="Admin Logs"
      actions={
        <button type="button" className="btn btn-ghost" onClick={() => void load(offset)} disabled={loading}>
          {loading ? "…" : "Refresh"}
        </button>
      }
    >
      <p className="muted-text">
        Administrative actions recorded with who took them, from where, and what changed — across every trail the
        platform keeps: security settings, agents, tools, knowledge, governance, projects, API keys and provider
        connections. Security entries are kept under the windows set on <strong>Retention Policy</strong>; older
        entries keep the action but lose their detail.
      </p>

      <div className="card api-logs-toolbar">
        <div className="api-logs-toolbar__main">
          <select
            className="api-logs-toolbar__date"
            aria-label="Audit trail"
            value={source}
            onChange={(e) => setSource(e.target.value as AuditSource)}
          >
            {AUDIT_SOURCES.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <LogFilterCombobox
            value={actor}
            onChange={setActor}
            options={options.actors}
            placeholder="Administrator"
            onOpen={() => void loadOptions()}
          />
          <LogFilterCombobox
            value={action}
            onChange={setAction}
            options={options.actions}
            placeholder="Action"
            onOpen={() => void loadOptions()}
          />
          <LogFilterCombobox
            value={resourceType}
            onChange={setResourceType}
            options={options.resource_types}
            placeholder="Resource"
            onOpen={() => void loadOptions()}
          />
          <input
            type="date"
            className="api-logs-toolbar__date"
            aria-label="From date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <input
            type="date"
            className="api-logs-toolbar__date"
            aria-label="To date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
        <div className="api-logs-toolbar__actions">
          <button type="button" className="btn api-logs-toolbar-btn" onClick={() => void load(0)} disabled={loading}>
            Filter
          </button>
          <button
            type="button"
            className="btn btn-ghost api-logs-toolbar-btn"
            onClick={() => {
              clearFilters();
            }}
            disabled={loading}
          >
            Clear
          </button>
        </div>
      </div>

      {error ? <p className="alert alert-error" role="alert">{error}</p> : null}

      <div className="table-wrap table-wrap--api-logs" ref={tableScrollRef}>
        <table className="card data-table data-table--api-logs">
          <thead>
            <tr>
              <th className="api-log-col--time">Time</th>
              <th className="api-log-col--secondary">Trail</th>
              <th className="api-log-col--user">Administrator</th>
              <th className="api-log-col--secondary">IP</th>
              <th className="api-log-col--model">Action</th>
              <th className="api-log-col--secondary">Resource</th>
              <th className="api-log-col--secondary">Detail</th>
            </tr>
          </thead>
          <tbody>
            {items.map((event) => (
              <tr
                key={`${event.source}:${event.id}`}
                className="api-logs-row--clickable"
                role="button"
                tabIndex={0}
                onClick={() => setSelected(event)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelected(event);
                  }
                }}
              >
                <td className="api-log-col--time">{formatLocalDateTime(event.created_at)}</td>
                <td className="api-log-col--secondary">{sourceLabel(event.source)}</td>
                {/* Directory-sourced names can be Persian; the machine columns
                    beside them must stay LTR or the bidi run mangles them. */}
                <td className="api-log-col--user" dir={messageDirectionForText(actorLabel(event))}>
                  {actorLabel(event)}
                </td>
                <td className="api-log-col--secondary">{event.actor_ip || "—"}</td>
                <td className="api-log-col--model">
                  {humanAction(event.action)}
                  {event.outcome && event.outcome !== "success" ? (
                    <span className="muted-text"> · {event.outcome}</span>
                  ) : null}
                </td>
                <td className="api-log-col--secondary">
                  {event.resource_type}
                  {event.resource_id ? ` #${event.resource_id}` : ""}
                </td>
                <td className="api-log-col--secondary">
                  {event.detail_redacted_at ? (
                    <span className="muted-text">Aged out</span>
                  ) : hasDetail(event.detail) ? (
                    "View"
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
            {!items.length && !loading ? (
              <tr>
                <td colSpan={7} className="muted-text">
                  No administrative events match these filters.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="api-logs-toolbar__actions">
        <button
          type="button"
          className="btn btn-ghost"
          disabled={loading || offset === 0}
          onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={loading || !hasMore}
          onClick={() => void load(offset + PAGE_SIZE)}
        >
          Next
        </button>
      </div>

      <Modal open={!!selected} title="Audit event" onClose={() => setSelected(null)}>
        {selected ? (
          <div className="model-access-form">
            <p className="muted-text">
              {sourceLabel(selected.source)} · {formatLocalDateTime(selected.created_at)} ·{" "}
              {humanAction(selected.action)}
              {selected.outcome ? ` (${selected.outcome})` : ""} · {selected.resource_type}
              {selected.resource_id ? ` #${selected.resource_id}` : ""}
            </p>
            <p>
              <strong dir={messageDirectionForText(actorLabel(selected))}>{actorLabel(selected)}</strong>
              {selected.actor_email ? <span className="muted-text"> · {selected.actor_email}</span> : null}
              {selected.actor_ip ? <span className="muted-text"> · {selected.actor_ip}</span> : null}
            </p>
            {selected.detail_redacted_at ? (
              <p className="muted-text">
                The detail for this event was cleared by the retention policy on{" "}
                {formatLocalDateTime(selected.detail_redacted_at)}. The action itself is kept.
              </p>
            ) : hasDetail(selected.detail) ? (
              <pre className="admin-log-detail">{JSON.stringify(selected.detail, null, 2)}</pre>
            ) : (
              <p className="muted-text">No detail was recorded for this event.</p>
            )}
          </div>
        ) : null}
      </Modal>
    </AdminPage>
  );
}
