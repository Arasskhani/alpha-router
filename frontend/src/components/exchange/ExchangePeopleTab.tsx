import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ConnectionBadge, errorText } from "./ExchangeControls";
import { useConfirm } from "../../context/ConfirmContext";
import { useTableCards } from "../../hooks/useTableCards";
import { exchangeAdminApi, type AdminConnection, type AdminConnectionList, type ConnectionStatus } from "../../lib/exchangeMail";
import { STATUS_FILTERS, ago, fullTime, plural } from "../../lib/exchangeAdmin";

const PEOPLE_PAGE_SIZE = 50;

function readStatus(value: string | null): ConnectionStatus | "" {
  return value === "connected" || value === "needs_password" || value === "error" ? value : "";
}

function personName(row: AdminConnection): string {
  return row.display_name || row.username;
}

/**
 * Exchange EWS › People: every connected mailbox, with search, a status
 * filter and pages; an administrator who may write can disconnect one. The
 * status filter is kept in the address, so the Overview's counts link here.
 */
export default function ExchangePeopleTab({ canEdit }: { canEdit: boolean }) {
  const [params, setParams] = useSearchParams();
  const tableRef = useTableCards<HTMLTableElement>();
  const confirmer = useConfirm();
  const status = readStatus(params.get("status"));
  const [qDraft, setQDraft] = useState(params.get("q") ?? "");
  const [q, setQ] = useState(qDraft.trim());
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ key: string; list: AdminConnectionList } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);
  const key = `${q}|${status}|${offset}|${reload}`;

  // The search runs when typing pauses, from the first page.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      const next = qDraft.trim();
      if (next === q) return;
      setQ(next);
      setOffset(0);
      setParams(
        (current) => {
          const out = new URLSearchParams(current);
          if (next) out.set("q", next);
          else out.delete("q");
          return out;
        },
        { replace: true },
      );
    }, 300);
    return () => window.clearTimeout(handle);
  }, [qDraft, q, setParams]);

  useEffect(() => {
    let live = true;
    exchangeAdminApi
      .connections({ q, status, limit: PEOPLE_PAGE_SIZE, offset })
      .then((list) => {
        if (!live) return;
        setData({ key, list });
        setError("");
      })
      .catch((err: unknown) => {
        if (live) setError(errorText(err));
      });
    return () => {
      live = false;
    };
  }, [q, status, offset, key]);

  function setStatus(next: ConnectionStatus | "") {
    setOffset(0);
    setParams(
      (current) => {
        const out = new URLSearchParams(current);
        if (next) out.set("status", next);
        else out.delete("status");
        return out;
      },
      { replace: true },
    );
  }

  async function disconnect(row: AdminConnection) {
    const name = personName(row);
    const ok = await confirmer.confirm({
      title: `Disconnect ${name}'s mailbox?`,
      message: `${row.primary_smtp || row.login} is disconnected from Alpharouter: the saved password, the list of mailboxes, the drafts list and the emails waiting for action are deleted here. Nothing changes in Exchange, and ${name} can connect again. Recorded in Admin Logs.`,
      confirmLabel: "Disconnect",
      danger: true,
    });
    if (ok !== true) return;
    setBusyId(row.id);
    setNotice("");
    try {
      await exchangeAdminApi.disconnect(row.id);
      setNotice(`${name}'s mailbox was disconnected.`);
      const left = (data?.list.total ?? 1) - 1;
      // The last row of the last page: go back a page rather than show an empty one.
      if (offset > 0 && offset >= left) setOffset(Math.max(0, offset - PEOPLE_PAGE_SIZE));
      else setReload((n) => n + 1);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusyId(null);
    }
  }

  const list = data?.list ?? null;
  const loading = !data || data.key !== key;
  const items = list?.items ?? [];
  const total = list?.total ?? 0;
  const page = Math.floor(offset / PEOPLE_PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PEOPLE_PAGE_SIZE));
  const filtered = Boolean(q || status);

  return (
    <div className="ews-admin-people">
      <div className="ews-admin-toolbar">
        <input
          type="search"
          className="input-block ews-admin-search"
          placeholder="Search name, user name, email or mailbox"
          aria-label="Search people"
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
        />
        <select
          className="input-block ews-admin-status-filter"
          aria-label="Status"
          value={status}
          onChange={(e) => setStatus(readStatus(e.target.value))}
        >
          {STATUS_FILTERS.map((option) => (
            <option key={option.value || "all"} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="muted-text ews-admin-toolbar__count" aria-live="polite">
          {list ? plural(total, "person", "people") : ""}
        </span>
      </div>

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert-success" role="status">
          {notice}
        </p>
      ) : null}

      <div className={`ews-admin-card ews-admin-people__card${loading && list ? " is-loading" : ""}`} aria-busy={loading}>
        <div className="table-wrap ews-admin-people__scroll">
          <table ref={tableRef} className="table data-table data-table--cards ews-admin-people__table">
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Login</th>
                <th scope="col">Mailbox</th>
                <th scope="col">Status</th>
                <th scope="col">Mailboxes</th>
                <th scope="col">Last check</th>
                <th scope="col">Last error</th>
                {canEdit ? (
                  <th scope="col" className="col-actions ews-admin-people__actions">
                    <span className="sr-only">Actions</span>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="ews-admin-person">
                      <bdi className="ews-admin-person__name">{personName(row)}</bdi>
                      <span className="muted-text" dir="ltr">
                        {row.username}
                        {row.email && row.email !== row.primary_smtp ? ` · ${row.email}` : ""}
                      </span>
                    </div>
                  </td>
                  <td className="ews-admin-nowrap">
                    <code dir="ltr">{row.login}</code>
                  </td>
                  <td className="ews-admin-nowrap" dir="ltr">
                    {row.primary_smtp || "—"}
                  </td>
                  <td>
                    <ConnectionBadge status={row.status} />
                  </td>
                  <td className="ews-admin-nowrap">
                    {/* One piece: on a phone the cell is a flex line and would space its parts apart. */}
                    <span>
                      {row.mailbox_count}
                      {row.full_access_count ? (
                        <span className="muted-text"> · {row.full_access_count} Full Access</span>
                      ) : null}
                    </span>
                  </td>
                  <td className="ews-admin-nowrap">
                    <span title={fullTime(row.last_checked_at)}>{ago(row.last_checked_at)}</span>
                  </td>
                  <td className={`ews-admin-people__error${row.last_error ? "" : " ews-admin-people__error--none"}`}>
                    {row.last_error ? <span dir="auto">{row.last_error}</span> : <span className="muted-text">—</span>}
                  </td>
                  {canEdit ? (
                    <td className="col-actions ews-admin-people__actions">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm ews-admin-danger-ghost"
                        disabled={busyId === row.id}
                        aria-label={`Disconnect ${personName(row)}`}
                        onClick={() => void disconnect(row)}
                      >
                        {busyId === row.id ? "Disconnecting…" : "Disconnect"}
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!list ? (
          <p className="ews-admin-people__empty muted-text">{error ? "" : "Loading people…"}</p>
        ) : items.length === 0 ? (
          <p className="ews-admin-people__empty muted-text">
            {filtered
              ? "Nobody matches."
              : "Nobody has connected a mailbox yet. People connect from their profile menu › Connections."}
          </p>
        ) : null}
        {list && total > PEOPLE_PAGE_SIZE ? (
          <nav className="ews-admin-pager" aria-label="Pages">
            <span className="muted-text">
              {offset + 1}–{Math.min(offset + PEOPLE_PAGE_SIZE, total)} of {total}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={page <= 1}
              onClick={() => setOffset(Math.max(0, offset - PEOPLE_PAGE_SIZE))}
            >
              ‹ Previous
            </button>
            <span>
              Page {page} of {pages}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={page >= pages}
              onClick={() => setOffset(offset + PEOPLE_PAGE_SIZE)}
            >
              Next ›
            </button>
          </nav>
        ) : null}
      </div>
    </div>
  );
}
