import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import ApiKeyFormModal, { type ApiKeyFormValues } from "../../components/apiKeys/ApiKeyFormModal";
import ApiKeyCreatedModal from "../../components/apiKeys/ApiKeyCreatedModal";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import { formatLocalDate, formatLocalDateTime } from "../../lib/dateTime";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";

type KeysListResponse = {
  items: NitroKey[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

type NitroKey = {
  id: number;
  name: string;
  prefix: string;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_used_at: string | null;
  owner_user_id: number | null;
  owner_email: string | null;
  owner_username: string | null;
  owner_display_name: string | null;
  credit_limit_usd: number;
  reset_period: "daily" | "weekly" | "monthly";
  expires_at: string | null;
  expiration_never: boolean;
  period_used_usd: number;
  total_used_usd: number;
};

function formatExpire(k: NitroKey) {
  if (k.expiration_never || !k.expires_at) return "Never";
  return formatLocalDate(k.expires_at);
}

function formatDateTime(iso: string | null) {
  return formatLocalDateTime(iso);
}

const PAGE_SIZE_OPTIONS = [10, 20, 30, 50] as const;

function formatUsd(v: number) {
  if (v >= 1) return `$${v.toFixed(2)}`;
  if (v > 0) return `$${v.toFixed(4)}`;
  return "$0";
}

export default function AdminApiKeys() {
  const { confirm } = useConfirm();
  const navigate = useNavigate();
  const [keys, setKeys] = useState<NitroKey[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(10);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [searchName, setSearchName] = useState("");
  const [searchOwner, setSearchOwner] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editKey, setEditKey] = useState<NitroKey | null>(null);
  const [created, setCreated] = useState<{
    api_key: string;
    url: string;
    name: string;
    owner_user_id: number;
    owner_email: string;
  } | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = useCallback(() => {
    const qs = new URLSearchParams();
    qs.set("page", String(page));
    qs.set("page_size", String(pageSize));
    if (searchName.trim()) qs.set("q", searchName.trim());
    if (searchOwner.trim()) qs.set("owner", searchOwner.trim());
    api<KeysListResponse>(`/api/admin/api-keys?${qs}`)
      .then((res) => {
        setKeys(res.items);
        setTotal(res.total);
        setPage(res.page);
        setTotalPages(res.total_pages);
        setSelectedIds([]);
      })
      .catch((e) => setErr(String(e)));
  }, [searchName, searchOwner, page, pageSize]);

  const visibleIds = useMemo(() => keys.map((k) => k.id), [keys]);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));

  function toggleSelectAllVisible() {
    if (allVisibleSelected) {
      setSelectedIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
    } else {
      setSelectedIds((prev) => [...new Set([...prev, ...visibleIds])]);
    }
  }

  function toggleRowSelection(id: number) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  useEffect(() => {
    const t = window.setTimeout(load, 250);
    return () => window.clearTimeout(t);
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [searchName, searchOwner, pageSize]);

  async function createKey(values: ApiKeyFormValues) {
    const res = await api<{
      api_key: string;
      url: string;
      name: string;
      owner_user_id: number;
      owner_email: string;
    }>("/api/admin/api-keys", {
      method: "POST",
      body: JSON.stringify({
        name: values.name,
        owner_user_id: values.owner_user_id,
        credit_limit_usd: values.credit_limit_usd ?? 0,
        reset_period: values.reset_period,
        expiration_days: values.expiration_never ? null : values.expiration_days,
      }),
    });
    setCreated({
      api_key: res.api_key,
      url: res.url,
      name: res.name,
      owner_user_id: res.owner_user_id,
      owner_email: res.owner_email,
    });
    setMsg("Gateway key created.");
    load();
  }

  async function updateKey(values: ApiKeyFormValues) {
    if (!editKey) return;
    await api(`/api/admin/api-keys/${editKey.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: values.name,
        owner_user_id: values.owner_user_id,
        credit_limit_usd: values.credit_limit_usd ?? 0,
        reset_period: values.reset_period,
        expiration_days: values.expiration_never ? null : values.expiration_days,
        expiration_never: values.expiration_never,
      }),
    });
    setMsg("API key updated.");
    load();
  }

  async function toggleKey(k: NitroKey) {
    await api(`/api/admin/api-keys/${k.id}/toggle?enabled=${!k.is_active}`, { method: "PATCH" });
    setMsg(k.is_active ? "Key disabled." : "Key enabled.");
    load();
  }

  async function deleteKey(k: NitroKey) {
    const ok = await confirm({
      title: "Delete API key",
      message: `Delete "${k.name}" permanently?`,
      danger: true,
    });
    if (!ok) return;
    await api(`/api/admin/api-keys/${k.id}`, { method: "DELETE" });
    setMsg("API key deleted.");
    load();
  }

  async function runBulk(action: "on" | "off" | "delete") {
    if (!selectedIds.length) return;
    if (action === "delete") {
      const ok = await confirm({
        title: "Delete API keys",
        message: `Delete ${selectedIds.length} selected key(s) permanently?`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
    }
    setBulkBusy(true);
    setErr("");
    try {
      const r = await api<{ count: number }>(`/api/admin/api-keys/bulk?action=${action}`, {
        method: "POST",
        body: JSON.stringify({ ids: selectedIds }),
      });
      setMsg(
        action === "delete"
          ? `Deleted ${r.count} key(s).`
          : `${action === "on" ? "Enabled" : "Disabled"} ${r.count} key(s).`,
      );
      setBulkOpen(false);
      setSelectedIds([]);
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <AdminPage
      title="API Keys"
      actions={
        <button type="button" className="btn api-keys-new-btn" onClick={() => setCreateOpen(true)}>
          + New Key
        </button>
      }
    >
      <p className="muted-text api-keys-lead">
        Admin gateway keys for products and services (Open WebUI, integrations). Per-user keys are managed from Users.
      </p>
      {msg && <p className="alert alert-success">{msg}</p>}
      {err && <p className="alert alert-error">{err}</p>}

      <div className="api-keys-toolbar card">
        <input
          type="search"
          className="input-block api-keys-search"
          placeholder="Search by name…"
          value={searchName}
          onChange={(e) => setSearchName(e.target.value)}
        />
        <input
          type="search"
          className="input-block api-keys-search"
          placeholder="Filter by owner…"
          value={searchOwner}
          onChange={(e) => setSearchOwner(e.target.value)}
        />
        <button
          type="button"
          className="btn btn-ghost api-keys-bulk-btn"
          disabled={selectedIds.length === 0}
          onClick={() => setBulkOpen(true)}
          title={selectedIds.length ? `${selectedIds.length} selected` : "Select keys first"}
        >
          Bulk Edit
        </button>
      </div>

      <div className="table-wrap">
        <table className="card data-table api-keys-table">
          <thead>
            <tr>
              <th className="col-sm">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleSelectAllVisible}
                  aria-label="Select all keys on this page"
                />
              </th>
              <th>Name</th>
              <th className="col-lg">Date Created</th>
              <th className="col-lg">Date Modified</th>
              <th className="col-md">Expire</th>
              <th className="col-lg">Last used</th>
              <th className="col-sm">Usage</th>
              <th className="col-md">Limit</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {keys.length === 0 && (
              <tr>
                <td colSpan={9} className="muted-text">
                  No gateway keys yet. Create one with + New Key.
                </td>
              </tr>
            )}
            {keys.map((k) => {
              const limit = k.credit_limit_usd;
              const periodPct = limit > 0 ? Math.min(100, (k.period_used_usd / limit) * 100) : 0;
              return (
                <tr key={k.id} className={k.is_active ? "" : "api-keys-row--disabled"}>
                  <td className="col-sm">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(k.id)}
                      onChange={() => toggleRowSelection(k.id)}
                      aria-label={`Select ${k.name}`}
                    />
                  </td>
                  <td>
                    <div className="api-keys-name-cell">
                      <strong>{k.name}</strong>
                      {k.owner_email || k.owner_username ? (
                        <span className="muted-text api-keys-owner">
                          {k.owner_display_name || k.owner_username} · {k.owner_email}
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="col-lg">{formatDateTime(k.created_at)}</td>
                  <td className="col-lg">{formatDateTime(k.updated_at)}</td>
                  <td className="col-md">{formatExpire(k)}</td>
                  <td className="col-lg">{k.last_used_at ? formatDateTime(k.last_used_at) : "Never"}</td>
                  <td className="col-sm">{formatUsd(k.total_used_usd)}</td>
                  <td className="col-md">
                    <div className="api-keys-limit">
                      <span>{limit > 0 ? formatUsd(limit) : "—"}</span>
                      {limit > 0 ? (
                        <div className="api-keys-limit-bar" aria-hidden>
                          <div className="api-keys-limit-fill" style={{ width: `${periodPct}%` }} />
                        </div>
                      ) : null}
                      <span className="muted-text api-keys-limit-period">
                        {k.reset_period} · period {formatUsd(k.period_used_usd)}
                      </span>
                    </div>
                  </td>
                  <td className="col-actions">
                    <RowActionsMenu
                      actions={[
                        {
                          label: "Edit",
                          onClick: () => setEditKey(k),
                        },
                        {
                          label: USAGE_AND_ACTIVITY_LABEL,
                          menuWrap: true,
                          onClick: () => navigate(`/admin/api-keys/${k.id}/activity`),
                        },
                        {
                          label: k.is_active ? "Disable" : "Enable",
                          onClick: () => toggleKey(k),
                        },
                        { label: "Delete", onClick: () => deleteKey(k), danger: true },
                      ]}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="api-keys-footer-bar">
        <p className="muted-text api-keys-footer">
          {total} key{total === 1 ? "" : "s"}
          {total > 0 ? ` · page ${page} of ${totalPages}` : ""}
          {selectedIds.length > 0 ? ` · ${selectedIds.length} selected` : ""}
        </p>
        <div className="api-keys-footer-controls">
          <label className="api-keys-page-size">
            <span className="muted-text">Per page</span>
            <select
              className="input-block"
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <div className="api-keys-pager">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              ‹ Prev
            </button>
            <span className="api-keys-pager__status">
              {page} / {totalPages}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              Next ›
            </button>
          </div>
        </div>
      </div>

      <ApiKeyFormModal
        open={createOpen}
        title="Create API Key"
        onClose={() => setCreateOpen(false)}
        onSubmit={createKey}
      />

      <ApiKeyFormModal
        open={!!editKey}
        title="Edit API Key"
        initial={
          editKey
            ? {
                name: editKey.name,
                owner_user_id: editKey.owner_user_id ?? undefined,
                credit_limit_usd: editKey.credit_limit_usd,
                reset_period: editKey.reset_period,
                expiration_never: editKey.expiration_never,
                expiration_days: editKey.expiration_never
                  ? null
                  : editKey.expires_at && editKey.created_at
                    ? Math.max(
                        1,
                        Math.round(
                          (new Date(editKey.expires_at).getTime() - new Date(editKey.created_at).getTime()) /
                            86400000,
                        ),
                      )
                    : 60,
              }
            : undefined
        }
        onClose={() => setEditKey(null)}
        onSubmit={updateKey}
      />

      <Modal
        open={bulkOpen}
        title={`Bulk Edit (${selectedIds.length} keys)`}
        onClose={() => !bulkBusy && setBulkOpen(false)}
      >
        <p className="muted-text">Apply an action to all selected API keys on this page and other pages.</p>
        <div className="dialog-actions" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <button type="button" className="btn" disabled={bulkBusy} onClick={() => runBulk("on")}>
            {bulkBusy ? "…" : "Enable"}
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => runBulk("off")}>
            Disable
          </button>
          <button type="button" className="btn btn-danger" disabled={bulkBusy} onClick={() => runBulk("delete")}>
            Delete
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => setBulkOpen(false)}>
            Cancel
          </button>
        </div>
      </Modal>

      {created ? (
        <ApiKeyCreatedModal
          open
          apiKey={created.api_key}
          url={created.url}
          name={created.name}
          ownerUserId={created.owner_user_id}
          ownerEmail={created.owner_email}
          onClose={() => setCreated(null)}
        />
      ) : null}
    </AdminPage>
  );
}
