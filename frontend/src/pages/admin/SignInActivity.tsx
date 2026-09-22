import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import LogFilterCombobox from "../../components/admin/LogFilterCombobox";
import { api, authFetch, formatApiError } from "../../api";
import { formatLocalDateTime } from "../../lib/dateTime";
import { attachDragScroll } from "../../lib/dragScroll";
import {
  EMPTY_FILTERS,
  IDP_SIGN_OUT_NOTE,
  buildSignInQuery,
  eventLabel,
  methodLabel,
  outcomeBadgeClass,
  outcomeLabel,
  reasonLabel,
  scopeSentence,
  signOutIsRecordedByIdp,
  userIdFromSearch,
  type SignInEvent,
  type SignInEventDetail,
  type SignInFilterOptions,
  type SignInFilters,
} from "../../lib/signInActivity";
import { messageDirectionForText } from "../../lib/textDirection";

type ListResponse = {
  items: SignInEvent[];
  limit: number;
  offset: number;
  has_more: boolean;
};

const PAGE_SIZE = 100;

async function downloadCsv(path: string): Promise<{ truncated: boolean; rows: number }> {
  const res = await authFetch(path);
  if (!res.ok) {
    let message = `Export failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) message = String(body.detail);
    } catch {
      /* keep status fallback */
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition");
  const match = cd?.match(/filename="([^"]+)"/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = match?.[1] ?? "alpharouter-sign-in-activity.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
  return {
    truncated: res.headers.get("X-Truncated") === "true",
    rows: Number(res.headers.get("X-Row-Count") || "0") || 0,
  };
}

function userLabel(event: SignInEvent): string {
  if (event.username) return event.username;
  if (event.user_id != null) return `User #${event.user_id}`;
  return "—";
}

/**
 * Sign-in Activity.
 *
 * Every sign-in, failed attempt, sign-out and revoked session, with the
 * address it came from and the reason it failed. Filters apply on the Filter
 * button, and the CSV carries exactly the rows the filters show.
 */
export default function SignInActivity() {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<SignInEvent[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");

  // The user id from `?user=` is a filter the page arrives with, from the
  // Users page's row action. Held as a string like the other inputs.
  const [filters, setFilters] = useState<SignInFilters>(() => ({
    ...EMPTY_FILTERS,
    userId: userIdFromSearch(searchParams),
  }));
  const [options, setOptions] = useState<SignInFilterOptions | null>(null);
  const [selected, setSelected] = useState<SignInEventDetail | null>(null);
  const [selectedLoading, setSelectedLoading] = useState(false);

  const tableScrollRef = useRef<HTMLDivElement | null>(null);

  const set = (key: keyof SignInFilters) => (value: string) => setFilters((prev) => ({ ...prev, [key]: value }));

  const load = useCallback(
    async (nextOffset = 0, applied: SignInFilters = filters) => {
      setLoading(true);
      setError("");
      try {
        const q = buildSignInQuery(applied, {
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        const data = await api<ListResponse>(`/api/admin/sign-in-activity?${q}`);
        setItems(data.items || []);
        setHasMore(!!data.has_more);
        setOffset(nextOffset);
      } catch (err) {
        setError(formatApiError(err));
      } finally {
        setLoading(false);
      }
    },
    [filters],
  );

  useEffect(() => {
    // The first page, once, on mount — with the user filter the URL brought.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the effect's job is the fetch
    void load(0);
    // Filters apply on the Filter button, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- avoid refetching on every filter keystroke
  }, []);

  useEffect(() => {
    const el = tableScrollRef.current;
    if (!el) return;
    return attachDragScroll(el);
  }, []);

  async function loadOptions() {
    if (options) return;
    try {
      setOptions(await api<SignInFilterOptions>("/api/admin/sign-in-activity/filter-options"));
    } catch {
      /* the combobox still accepts free text */
    }
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    void load(0, EMPTY_FILTERS);
  }

  async function openEvent(event: SignInEvent) {
    setSelectedLoading(true);
    setSelected({ ...event, user: null });
    try {
      setSelected(await api<SignInEventDetail>(`/api/admin/sign-in-activity/${event.id}`));
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSelectedLoading(false);
    }
  }

  async function exportCsv() {
    setExporting(true);
    setError("");
    setFlash("");
    try {
      const result = await downloadCsv(`/api/admin/sign-in-activity/export.csv?${buildSignInQuery(filters)}`);
      setFlash(
        result.truncated
          ? `Exported the first ${result.rows.toLocaleString()} rows; narrow the filters for the rest. The export was recorded in Admin Logs.`
          : `Exported ${result.rows.toLocaleString()} row(s). The export was recorded in Admin Logs.`,
      );
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setExporting(false);
    }
  }

  const scopedUser = filters.userId ? items.find((e) => String(e.user_id) === filters.userId) : undefined;

  return (
    <AdminPage
      title="Sign-in Activity"
      actions={
        <>
          <button type="button" className="btn btn-ghost" onClick={() => void exportCsv()} disabled={exporting}>
            {exporting ? "Exporting…" : "Export CSV"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void load(offset)} disabled={loading}>
            {loading ? "…" : "Refresh"}
          </button>
        </>
      }
    >
      <p className="muted-text">
        Every sign-in, failed attempt, sign-out and revoked session, with the address it came from and — when it failed
        — why. A sign-out ends every session for the account, so rows are not paired into durations. Accounts that sign
        in through SAML or OIDC sign out at the identity provider, whose own log records that. Rows are kept for the
        window set on <Link to="/admin/retention-policy">Retention Policy</Link>; exporting is recorded in{" "}
        <Link to="/admin/admin-logs">Admin Logs</Link>.
      </p>

      {filters.userId ? (
        <p className="alert alert-info">
          Showing sign-in activity for{" "}
          <strong dir={messageDirectionForText(scopedUser?.username || "")}>
            {scopedUser?.username ? scopedUser.username : `user #${filters.userId}`}
          </strong>
          . <Link to={`/admin/users/${filters.userId}/activity`}>Open user</Link> ·{" "}
          <button type="button" className="btn-link" onClick={clearFilters}>
            Show everyone
          </button>
        </p>
      ) : null}

      <div className="card api-logs-toolbar">
        <div className="api-logs-toolbar__main">
          <input
            type="text"
            className="api-logs-toolbar__date"
            aria-label="Username"
            placeholder="Username starts with…"
            value={filters.username}
            onChange={(e) => set("username")(e.target.value)}
          />
          <LogFilterCombobox
            value={filters.eventType}
            onChange={set("eventType")}
            options={options?.event_types ?? []}
            placeholder="Event"
            onOpen={() => void loadOptions()}
          />
          <LogFilterCombobox
            value={filters.outcome}
            onChange={set("outcome")}
            options={options?.outcomes ?? []}
            placeholder="Outcome"
            onOpen={() => void loadOptions()}
          />
          <LogFilterCombobox
            value={filters.reasonCode}
            onChange={set("reasonCode")}
            options={options?.reason_codes ?? []}
            placeholder="Reason"
            onOpen={() => void loadOptions()}
          />
          <LogFilterCombobox
            value={filters.authMethod}
            onChange={set("authMethod")}
            options={options?.auth_methods ?? []}
            placeholder="Method"
            onOpen={() => void loadOptions()}
          />
          <input
            type="text"
            className="api-logs-toolbar__date"
            aria-label="IP address"
            placeholder="IP address"
            value={filters.ip}
            onChange={(e) => set("ip")(e.target.value)}
          />
          <input
            type="date"
            className="api-logs-toolbar__date"
            aria-label="From date"
            value={filters.start}
            onChange={(e) => set("start")(e.target.value)}
          />
          <input
            type="date"
            className="api-logs-toolbar__date"
            aria-label="To date"
            value={filters.end}
            onChange={(e) => set("end")(e.target.value)}
          />
        </div>
        <div className="api-logs-toolbar__actions">
          <button type="button" className="btn api-logs-toolbar-btn" onClick={() => void load(0)} disabled={loading}>
            Filter
          </button>
          <button
            type="button"
            className="btn btn-ghost api-logs-toolbar-btn"
            onClick={clearFilters}
            disabled={loading}
          >
            Clear
          </button>
        </div>
      </div>

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {flash ? <p className="alert alert-success">{flash}</p> : null}

      <div className="table-wrap table-wrap--api-logs" ref={tableScrollRef}>
        <table className="card data-table data-table--api-logs">
          <thead>
            <tr>
              <th className="api-log-col--time">Time</th>
              <th className="api-log-col--user">User</th>
              <th className="api-log-col--model">Event</th>
              <th className="api-log-col--secondary">Outcome</th>
              <th className="api-log-col--secondary">Method</th>
              <th className="api-log-col--secondary">IP</th>
              <th className="api-log-col--model">Reason</th>
            </tr>
          </thead>
          <tbody>
            {items.map((event) => (
              <tr
                key={event.id}
                className="api-logs-row--clickable"
                role="button"
                tabIndex={0}
                onClick={() => void openEvent(event)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    void openEvent(event);
                  }
                }}
              >
                <td className="api-log-col--time">{formatLocalDateTime(event.occurred_at)}</td>
                {/* Directory-sourced names can be Persian; the machine columns
                    beside them must stay LTR or the bidi run mangles them. */}
                <td className="api-log-col--user" dir={messageDirectionForText(userLabel(event))}>
                  {userLabel(event)}
                </td>
                <td className="api-log-col--model">
                  {eventLabel(event.event_type)}
                  {event.backfilled ? <span className="muted-text"> · imported</span> : null}
                </td>
                <td className="api-log-col--secondary">
                  <span className={outcomeBadgeClass(event)}>{outcomeLabel(event.outcome)}</span>
                </td>
                <td className="api-log-col--secondary">{methodLabel(event.auth_method)}</td>
                <td className="api-log-col--secondary">{event.ip || "—"}</td>
                <td className="api-log-col--model">{reasonLabel(event.reason_code)}</td>
              </tr>
            ))}
            {!items.length && !loading ? (
              <tr>
                <td colSpan={7} className="muted-text">
                  No sign-in events match these filters.
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

      <Modal open={!!selected} title="Sign-in event" onClose={() => setSelected(null)}>
        {selected ? (
          <div className="model-access-form">
            <p className="muted-text">
              {formatLocalDateTime(selected.occurred_at)} · {eventLabel(selected.event_type)} ·{" "}
              <span className={outcomeBadgeClass(selected)}>{outcomeLabel(selected.outcome)}</span>
              {selected.backfilled ? " · imported from the earlier audit trail" : ""}
            </p>
            <p>
              <strong dir={messageDirectionForText(userLabel(selected))}>{userLabel(selected)}</strong>
              {selected.user ? (
                <span className="muted-text">
                  {" "}
                  · <Link to={`/admin/users/${selected.user.id}/activity`}>Open user</Link>
                  {selected.user.username !== selected.username ? ` (now ${selected.user.username})` : ""}
                  {selected.user.purged_at
                    ? " · account permanently deleted"
                    : selected.user.deleted_at
                      ? " · account deleted"
                      : selected.user.is_active
                        ? ""
                        : " · account deactivated"}
                </span>
              ) : selected.user_id == null && !selectedLoading ? (
                <span className="muted-text"> · no account by this name</span>
              ) : null}
            </p>
            {scopeSentence(selected) ? <p>{scopeSentence(selected)}</p> : null}
            {signOutIsRecordedByIdp(selected.auth_method) ? <p className="muted-text">{IDP_SIGN_OUT_NOTE}</p> : null}
            <dl className="sign-in-event-facts">
              <dt>Method</dt>
              <dd>{methodLabel(selected.auth_method)}</dd>
              <dt>IP address</dt>
              <dd>{selected.ip || "not recorded"}</dd>
              <dt>Reason</dt>
              <dd>{reasonLabel(selected.reason_code)}</dd>
              {selected.reason_detail ? (
                <>
                  <dt>Provider message</dt>
                  <dd>
                    <pre className="admin-log-detail">{selected.reason_detail}</pre>
                  </dd>
                </>
              ) : null}
              <dt>User agent</dt>
              <dd className="sign-in-event-facts__mono">{selected.user_agent || "not recorded"}</dd>
              <dt>Session ID</dt>
              <dd className="sign-in-event-facts__mono">{selected.session_id || "not recorded"}</dd>
              <dt>Correlation ID</dt>
              <dd className="sign-in-event-facts__mono">{selected.correlation_id || "not recorded"}</dd>
              <dt>Event ID</dt>
              <dd className="sign-in-event-facts__mono">{selected.id}</dd>
            </dl>
          </div>
        ) : null}
      </Modal>
    </AdminPage>
  );
}
