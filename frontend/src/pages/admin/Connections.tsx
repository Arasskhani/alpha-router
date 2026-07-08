import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import ConnectionFormModal, { type ConnectionFormValues } from "../../components/connections/ConnectionFormModal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { formatLocalDateTime } from "../../lib/dateTime";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";

type Conn = {
  id: number;
  name: string;
  provider_type: string;
  base_url: string | null;
  is_active: boolean;
  sync_interval_hours: number;
  last_sync_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  usage_usd: number;
  api_key_masked: string;
};

function formatDateTime(iso: string | null) {
  return formatLocalDateTime(iso);
}

function formatUsd(v: number) {
  if (v >= 1) return `$${v.toFixed(2)}`;
  if (v > 0) return `$${v.toFixed(4)}`;
  return "$0";
}

function syncScheduleLabel(hours: number) {
  if (!hours || hours <= 0) return "Manual only";
  if (hours === 1) return "Every 1 hour";
  return `Every ${hours} hours`;
}

function truncateUrl(url: string | null, max = 42) {
  if (!url) return "Default";
  if (url.length <= max) return url;
  return `${url.slice(0, max - 1)}…`;
}

export default function Connections() {
  const { confirm } = useConfirm();
  const navigate = useNavigate();
  const [list, setList] = useState<Conn[]>([]);
  const [search, setSearch] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editConn, setEditConn] = useState<Conn | null>(null);

  const load = useCallback(async () => {
    try {
      setErr("");
      const data = await api<Conn[]>("/api/admin/connections");
      setList(data);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = list.filter((c) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      c.name.toLowerCase().includes(q) ||
      c.provider_type.toLowerCase().includes(q) ||
      (c.base_url || "").toLowerCase().includes(q)
    );
  });

  async function createConnection(values: ConnectionFormValues) {
    await api("/api/admin/connections?sync_now=false", {
      method: "POST",
      body: JSON.stringify({
        name: values.name,
        provider_type: values.provider_type,
        api_key: values.api_key,
        base_url: values.base_url || null,
        sync_interval_hours: values.sync_interval_hours,
      }),
    });
    setMsg(`Connection "${values.name}" added. Use Sync now to pull models.`);
    await load();
  }

  async function updateConnection(values: ConnectionFormValues) {
    if (!editConn) return;
    const body: Record<string, unknown> = {
      name: values.name,
      provider_type: values.provider_type,
      base_url: values.base_url || null,
      sync_interval_hours: values.sync_interval_hours,
    };
    if (values.api_key.trim()) body.api_key = values.api_key.trim();
    await api(`/api/admin/connections/${editConn.id}`, { method: "PATCH", body: JSON.stringify(body) });
    setMsg("Connection updated.");
    await load();
  }

  async function syncNow(id: number) {
    try {
      const r = await api<{ synced: number }>(`/api/admin/connections/${id}/sync`, { method: "POST" });
      setMsg(`Synced ${r.synced} models.`);
      window.dispatchEvent(new CustomEvent("nitro-models-sync-flash"));
      await load();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function toggleConn(c: Conn) {
    await api(`/api/admin/connections/${c.id}/toggle?enabled=${!c.is_active}`, { method: "PATCH" });
    setMsg(
      c.is_active
        ? "Connection disabled. All its models were turned off."
        : "Connection enabled. Its models were turned on.",
    );
    await load();
  }

  async function removeConnection(c: Conn) {
    const ok = await confirm({
      title: "Delete connection",
      message: `Delete connection "${c.name}"? Synced models for this provider will be removed. This cannot be undone.`,
      danger: true,
    });
    if (!ok) return;
    await api(`/api/admin/connections/${c.id}`, { method: "DELETE" });
    if (editConn?.id === c.id) setEditConn(null);
    setMsg(`Connection "${c.name}" deleted.`);
    await load();
  }

  return (
    <AdminPage
      title="Connections"
      actions={
        <button type="button" className="btn connections-new-btn" onClick={() => setCreateOpen(true)}>
          + New Connection
        </button>
      }
    >
      <p className="muted-text connections-lead">
        Upstream provider accounts (OpenRouter, OpenAI, …). Set a custom <strong>Base URL</strong> per connection for
        chat, embeddings, video, or other API paths — then sync models for that endpoint.
      </p>
      {msg && <p className="alert alert-success">{msg}</p>}
      {err && <p className="alert alert-error">{err}</p>}

      <div className="connections-toolbar card">
        <input
          type="search"
          className="input-block connections-search"
          placeholder="Search name, provider, or base URL…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="table-wrap">
        <table className="card data-table connections-table">
          <thead>
            <tr>
              <th>Name</th>
              <th className="col-sm">Provider</th>
              <th className="col-lg">Base URL</th>
              <th className="col-sm">Usage</th>
              <th className="col-lg">Last sync</th>
              <th className="col-md">Schedule</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="muted-text">
                  {list.length === 0 ? "No connections yet. Add one with + New Connection." : "No matches."}
                </td>
              </tr>
            )}
            {filtered.map((c) => (
              <tr key={c.id} className={c.is_active ? "" : "connections-row--disabled"}>
                <td>
                  <div className="connections-name-cell">
                    <strong>{c.name}</strong>
                    {!c.is_active ? <span className="connections-badge">Disabled</span> : null}
                  </div>
                </td>
                <td className="col-sm">{c.provider_type}</td>
                <td className="col-lg">
                  <code className="connections-base-url" title={c.base_url || undefined}>
                    {truncateUrl(c.base_url)}
                  </code>
                </td>
                <td className="col-sm">
                  <strong>{formatUsd(c.usage_usd ?? 0)}</strong>
                </td>
                <td className="col-lg">{c.last_sync_at ? formatDateTime(c.last_sync_at) : "—"}</td>
                <td className="col-md">{syncScheduleLabel(c.sync_interval_hours)}</td>
                <td className="col-actions">
                  <RowActionsMenu
                    actions={[
                      { label: "Edit", onClick: () => setEditConn(c) },
                      {
                        label: USAGE_AND_ACTIVITY_LABEL,
                        menuWrap: true,
                        onClick: () => navigate(`/admin/connections/${c.id}/activity`),
                      },
                      { label: "Sync now", onClick: () => syncNow(c.id) },
                      { label: c.is_active ? "Disable" : "Enable", onClick: () => toggleConn(c) },
                      { label: "Delete", onClick: () => removeConnection(c), danger: true },
                    ]}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ConnectionFormModal open={createOpen} title="Add connection" onClose={() => setCreateOpen(false)} onSubmit={createConnection} />

      <ConnectionFormModal
        open={!!editConn}
        title="Edit connection"
        initial={
          editConn
            ? {
                name: editConn.name,
                provider_type: editConn.provider_type,
                base_url: editConn.base_url ?? "",
                sync_interval_hours: editConn.sync_interval_hours,
                api_key_masked: editConn.api_key_masked,
              }
            : undefined
        }
        onClose={() => setEditConn(null)}
        onSubmit={updateConnection}
      />
    </AdminPage>
  );
}
