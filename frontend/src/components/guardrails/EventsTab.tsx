import { useCallback, useEffect, useState } from "react";

import Modal from "../Modal";
import { api, authFetch, formatApiError } from "../../api";
import { ACTION_LABELS, GUARDRAILS_BASE, formatWhen, type GuardrailEvent, type GuardrailsMeta } from "../../lib/guardrails";

const PAGE = 50;

/** What the rules did: filtered, paged, exported; never the values found. */
export default function EventsTab({ meta }: { meta: GuardrailsMeta | null }) {
  const [days, setDays] = useState(7);
  const [action, setAction] = useState("");
  const [channel, setChannel] = useState("");
  const [username, setUsername] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{ total: number; items: GuardrailEvent[] } | null>(null);
  const [open, setOpen] = useState<GuardrailEvent | null>(null);
  const [error, setError] = useState("");

  const query = useCallback(
    (extra: Record<string, string> = {}) => {
      const params = new URLSearchParams({ days: String(days), ...extra });
      if (action) params.set("action", action);
      if (channel) params.set("channel", channel);
      if (username.trim()) params.set("username", username.trim());
      return params.toString();
    },
    [days, action, channel, username],
  );

  useEffect(() => {
    let cancelled = false;
    api<{ total: number; items: GuardrailEvent[] }>(`${GUARDRAILS_BASE}/events?${query({ limit: String(PAGE), offset: String(offset) })}`)
      .then((next) => {
        if (!cancelled) setPage(next);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [query, offset]);

  async function exportCsv() {
    try {
      const res = await authFetch(`${GUARDRAILS_BASE}/events/export.csv?${query()}`);
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "guardrail-events.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  const reset = (fn: () => void) => {
    fn();
    setOffset(0);
  };

  return (
    <div className="guardrails-events">
      <div className="guardrails-toolbar guardrails-filters">
        <select aria-label="Period" value={days} onChange={(e) => reset(() => setDays(Number(e.target.value)))}>
          <option value={1}>Last 24 hours</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
        <select aria-label="Action" value={action} onChange={(e) => reset(() => setAction(e.target.value))}>
          <option value="">Any action</option>
          {["block", "redact", "route", "monitor", "engine_error"].map((a) => (
            <option key={a} value={a}>
              {ACTION_LABELS[a]}
            </option>
          ))}
        </select>
        <select aria-label="Channel" value={channel} onChange={(e) => reset(() => setChannel(e.target.value))}>
          <option value="">Any channel</option>
          {(meta?.channels ?? []).map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </select>
        <input
          type="search"
          className="input-block guardrails-search"
          placeholder="User…"
          aria-label="Username starts with"
          value={username}
          onChange={(e) => reset(() => setUsername(e.target.value))}
        />
        <button type="button" className="btn btn-ghost" onClick={() => void exportCsv()}>
          Export CSV
        </button>
      </div>
      {error ? <p className="alert alert-error" role="alert">{error}</p> : null}
      <div className="table-wrap">
        <table className="card data-table guardrails-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Rule</th>
              <th>Action</th>
              <th>Channel</th>
              <th>Found</th>
            </tr>
          </thead>
          <tbody>
            {page === null ? (
              <tr>
                <td colSpan={6} className="muted-text">
                  Loading…
                </td>
              </tr>
            ) : page.items.length === 0 ? (
              <tr>
                <td colSpan={6} className="muted-text">
                  No events in this period.
                </td>
              </tr>
            ) : (
              page.items.map((ev) => (
                <tr key={ev.id} className="guardrails-event-row" onClick={() => setOpen(ev)}>
                  <td>
                    <button type="button" className="guardrails-link" onClick={() => setOpen(ev)}>
                      {formatWhen(ev.created_at)}
                    </button>
                  </td>
                  <td>{ev.username ?? (ev.alpha_router_api_key_id ? `API key #${ev.alpha_router_api_key_id}` : "—")}</td>
                  <td>{ev.rule_name ?? "—"}</td>
                  <td>
                    <span className={`guardrails-action guardrails-action--${ev.action}`}>
                      {ACTION_LABELS[ev.action]}
                      {ev.intended_action ? ` (would ${ev.intended_action})` : ""}
                    </span>
                  </td>
                  <td>{ev.channel}</td>
                  <td className="guardrails-found">{ev.findings.map((f) => `${f.name} ×${f.count}`).join(", ") || "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {page ? (
        <div className="guardrails-pager">
          <span className="muted-text">
            {page.total ? `${offset + 1}–${Math.min(offset + PAGE, page.total)} of ${page.total}` : ""} · Values are never
            stored; only their kind and a masked hint.
          </span>
          <button type="button" className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Newer
          </button>
          <button type="button" className="btn btn-ghost" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
            Older
          </button>
        </div>
      ) : null}
      <Modal open={open !== null} title="Guardrails event" onClose={() => setOpen(null)}>
        {open ? (
          <dl className="guardrails-details">
            <dt>Time</dt>
            <dd>{formatWhen(open.created_at)}</dd>
            <dt>Rule</dt>
            <dd>
              {open.rule_name ?? "—"} {open.rule_version ? `(version ${open.rule_version})` : ""}
            </dd>
            <dt>Action</dt>
            <dd>
              {ACTION_LABELS[open.action]}
              {open.intended_action ? ` — would have: ${open.intended_action}` : ""}
            </dd>
            <dt>Who</dt>
            <dd>{open.username ?? (open.alpha_router_api_key_id ? `API key #${open.alpha_router_api_key_id}` : "—")}</dd>
            <dt>Channel</dt>
            <dd>{open.channel}</dd>
            <dt>Destination</dt>
            <dd>
              {open.destination ?? "—"} {open.destination_trust ? `(${open.destination_trust})` : ""}
            </dd>
            <dt>Found</dt>
            <dd>
              {open.findings.length
                ? open.findings.map((f) => (
                    <div key={f.ref}>
                      {f.name} ×{f.count} <span className="muted-text">{f.hints.join(", ")}</span>
                    </div>
                  ))
                : "—"}
            </dd>
            {open.message ? (
              <>
                <dt>{open.action === "engine_error" ? "Error" : "The person saw"}</dt>
                <dd>{open.message}</dd>
              </>
            ) : null}
          </dl>
        ) : null}
      </Modal>
    </div>
  );
}
