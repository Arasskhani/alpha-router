import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import AdminPage from "../../components/AdminPage";
import ChatToolIcon from "../../components/ChatToolIcon";
import Modal from "../../components/Modal";
import ExtensionSettingsCard from "../../components/admin/ExtensionSettingsCard";
import ResourceAccessEditor from "../../components/admin/ResourceAccessEditor";
import { api, formatApiError } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { useTableCards } from "../../hooks/useTableCards";

type ChatToolRow = {
  key: string;
  title: string;
  description: string;
  icon: string;
  access_type: "public" | "private";
  allow_count: number;
  deny_count: number;
  updated_at: string | null;
};

const LIST_PATH = "/api/admin/chat-tools";

function accessLabel(row: ChatToolRow): string {
  if (row.access_type === "public") {
    return row.deny_count > 0
      ? `Everyone except ${row.deny_count} ${row.deny_count === 1 ? "exception" : "exceptions"}`
      : "Everyone";
  }
  const granted = `${row.allow_count} ${row.allow_count === 1 ? "grant" : "grants"}`;
  return row.deny_count > 0 ? `Restricted — ${granted}, ${row.deny_count} denied` : `Restricted — ${granted}`;
}

function when(value: string | null): string {
  if (!value) return "—";
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? "—" : at.toLocaleString();
}

/**
 * Who may use each tool in the chat composer.
 *
 * Every row comes from the server-side registry, not from a list written
 * here, so a tool added to `app/services/chat_tool_registry.py` appears on
 * this page with access control already working — no page change, no
 * migration. That is the whole design: the registry is the only place a tool
 * is declared.
 *
 * Access itself is the same editor, and the same rules, as agents and
 * knowledge bases: public until restricted, deny beats allow, and no implicit
 * exception for Super Admin.
 */
export default function ChatTools() {
  // On a phone the tools are drawn as a list of cards (styles.css).
  const tableCardsRef = useTableCards<HTMLTableElement>();
  const readOnly = useReadOnly();
  const [rows, setRows] = useState<ChatToolRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<ChatToolRow | null>(null);

  // No setState before the first await: the mount effect calls this directly,
  // and a synchronous state change inside an effect body is a cascading render.
  const load = useCallback(async (message?: string) => {
    try {
      setRows(await api<ChatToolRow[]>(LIST_PATH));
      setError("");
      if (message) setNotice(message);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(() => {
    setLoading(true);
    void load();
  }, [load]);

  useEffect(() => {
    // Inline rather than calling load(): the first paint must not queue a state
    // change from inside the effect body, and a page that unmounts mid-request
    // should not write to it afterwards.
    let cancelled = false;
    void (async () => {
      try {
        const data = await api<ChatToolRow[]>(LIST_PATH);
        if (cancelled) return;
        setRows(data);
        setError("");
      } catch (err) {
        if (!cancelled) setError(formatApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AdminPage
      title="Chat Tools"
      actions={
        <button type="button" className="btn btn-ghost" onClick={refresh} disabled={loading}>
          {loading ? "…" : "Refresh"}
        </button>
      }
    >
      <p className="muted-text">
        Each tool in the chat composer, and who may use it. A tool left open is available to everyone; restrict one
        and only the people, groups, departments or roles granted it can turn it on. A denial always wins over a
        grant. Code Interpreter has settings of its own on{" "}
        <Link to="/admin/code-interpreter">Code Interpreter</Link>, and the browser extension&apos;s are below the
        table; changes here are recorded in <Link to="/admin/admin-logs">Admin Logs</Link>.
      </p>

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

      <div className="table-wrap">
        <table ref={tableCardsRef} className="table data-table data-table--cards chat-tools-table">
          <thead>
            <tr>
              <th scope="col">Tool</th>
              <th scope="col">Who can use it</th>
              <th scope="col">Last changed</th>
              <th scope="col" className="chat-tools-table__actions">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows?.map((row) => (
              <tr key={row.key}>
                <td>
                  <div className="chat-tools-table__tool">
                    <span className="chat-tools-table__icon" aria-hidden>
                      <ChatToolIcon name={row.icon} />
                    </span>
                    <div>
                      <strong>{row.title}</strong>
                      <p className="muted-text">{row.description}</p>
                    </div>
                  </div>
                </td>
                <td>
                  <span
                    className={`badge ${
                      row.access_type === "public" && row.deny_count === 0 ? "badge-open" : "badge-restricted"
                    }`}
                  >
                    {accessLabel(row)}
                  </span>
                </td>
                <td className="muted-text">{when(row.updated_at)}</td>
                <td className="chat-tools-table__actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      setNotice("");
                      setEditing(row);
                    }}
                  >
                    {readOnly ? "View access" : "Manage access"}
                  </button>
                </td>
              </tr>
            ))}
            {!loading && !rows?.length ? (
              <tr>
                <td colSpan={4} className="muted-text">
                  No chat tools are registered.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <ExtensionSettingsCard />

      <Modal
        open={editing !== null}
        title={editing ? `Access — ${editing.title}` : ""}
        onClose={() => setEditing(null)}
        panelClassName="modal-panel--md"
      >
        {editing ? (
          <ResourceAccessEditor
            title={`Who can use ${editing.title}`}
            loadPath={`${LIST_PATH}/${encodeURIComponent(editing.key)}/access`}
            savePath={`${LIST_PATH}/${encodeURIComponent(editing.key)}/access`}
            disabled={readOnly}
            onError={setError}
            onSaved={() => {
              setEditing(null);
              void load(`Access for ${editing.title} updated.`);
            }}
          />
        ) : null}
      </Modal>
    </AdminPage>
  );
}
