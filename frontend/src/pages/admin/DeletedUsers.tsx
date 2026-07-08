import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import RowActionsMenu, { RowAction } from "../../components/RowActionsMenu";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";

type DeletedUser = {
  id: number;
  username: string;
  email: string | null;
  display_name: string | null;
  auth_provider: string;
  is_active: boolean;
  deleted_at: string | null;
  last_login_at: string | null;
};

export default function DeletedUsers() {
  const navigate = useNavigate();
  const { confirm } = useConfirm();
  const [users, setUsers] = useState<DeletedUser[]>([]);
  const [flash, setFlash] = useState("");
  const [err, setErr] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = () => {
    api<DeletedUser[]>("/api/admin/deleted-users")
      .then(setUsers)
      .catch((e) => setErr(String(e)));
  };

  useEffect(() => {
    load();
  }, []);

  const allVisibleSelected = useMemo(
    () => users.length > 0 && users.every((u) => selectedIds.includes(u.id)),
    [users, selectedIds],
  );

  function toggleSelection(userId: number) {
    setSelectedIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId],
    );
  }

  function toggleSelectAllVisible() {
    setSelectedIds((prev) => {
      if (allVisibleSelected) {
        return prev.filter((id) => !users.some((u) => u.id === id));
      }
      const merged = new Set(prev);
      for (const u of users) merged.add(u.id);
      return Array.from(merged);
    });
  }

  async function permanentlyDeleteUser(u: DeletedUser) {
    const ok1 = await confirm({
      title: "Permanently delete user",
      message: `Permanently delete "${u.username}"? All chat history, media, and account data will be removed from the server. This cannot be undone.`,
      confirmLabel: "Continue",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok1) return;
    const ok2 = await confirm({
      title: "Final confirmation",
      message: `You are about to permanently erase "${u.username}" from NITRO. Confirm permanent deletion?`,
      confirmLabel: "Permanently delete",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok2) return;
    setErr("");
    try {
      await api(`/api/admin/users/${u.id}/permanently-delete`, { method: "POST" });
      setFlash(`User "${u.username}" permanently deleted.`);
      setSelectedIds((prev) => prev.filter((id) => id !== u.id));
      load();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function bulkPermanentlyDelete() {
    if (!selectedIds.length) return;
    const ok1 = await confirm({
      title: "Permanently delete users",
      message: `Permanently delete ${selectedIds.length} selected user(s)? All their data will be removed from the server.`,
      confirmLabel: "Continue",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok1) return;
    const ok2 = await confirm({
      title: "Final confirmation",
      message: `Confirm permanent deletion of ${selectedIds.length} user(s)? This cannot be undone.`,
      confirmLabel: "Permanently delete all",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok2) return;
    setBulkBusy(true);
    setErr("");
    try {
      const res = await api<{ deleted: number }>("/api/admin/deleted-users/bulk-permanently-delete", {
        method: "POST",
        body: JSON.stringify({ user_ids: selectedIds }),
      });
      setFlash(`Permanently deleted ${res.deleted ?? 0} user(s).`);
      setSelectedIds([]);
      setBulkOpen(false);
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBulkBusy(false);
    }
  }

  function rowActions(u: DeletedUser): RowAction[] {
    return [
      {
        label: USAGE_AND_ACTIVITY_LABEL,
        menuWrap: true,
        onClick: () => navigate(`/admin/users/${u.id}/activity`),
      },
      {
        label: "User Storage",
        onClick: () => navigate(`/admin/users/${u.id}/media`),
      },
      {
        label: "Permanently Delete User",
        onClick: () => void permanentlyDeleteUser(u),
        danger: true,
      },
    ];
  }

  const prov = (p: string) => `badge badge-${p === "local" ? "local" : p === "ldap" ? "ldap" : "keycloak"}`;

  return (
    <AdminPage title="Deleted Users">
      {flash && <p className="alert alert-success">{flash}</p>}
      {err && <p className="alert alert-error">{err}</p>}
      <p className="muted-text">
        Users removed from sync or deleted by an admin. They cannot sign in. Data is kept until permanently deleted.
      </p>
      <div className="search-bar">
        <button
          className="btn btn-ghost"
          type="button"
          disabled={selectedIds.length === 0}
          onClick={() => setBulkOpen(true)}
        >
          Bulk Edit{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
        </button>
      </div>
      <div className="table-wrap">
        <table className="card data-table">
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAllVisible} aria-label="Select all" />
              </th>
              <th>User</th>
              <th>Source</th>
              <th>Deleted</th>
              <th>Last login</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(u.id)}
                    onChange={() => toggleSelection(u.id)}
                    aria-label={`Select ${u.username}`}
                  />
                </td>
                <td>
                  {u.display_name || u.username}
                  <br />
                  <small>{u.username}{u.email ? ` · ${u.email}` : ""}</small>
                </td>
                <td>
                  <span className={prov(u.auth_provider)}>{u.auth_provider}</span>
                </td>
                <td>{u.deleted_at ? new Date(u.deleted_at).toLocaleString() : "—"}</td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}</td>
                <td className="col-actions">
                  <RowActionsMenu actions={rowActions(u)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={bulkOpen} title={`Bulk Edit (${selectedIds.length} users)`} onClose={() => !bulkBusy && setBulkOpen(false)}>
        <p className="muted-text">Permanently remove selected users and all their data from the server.</p>
        <div className="dialog-actions">
          <button type="button" className="btn btn-danger" disabled={bulkBusy} onClick={() => void bulkPermanentlyDelete()}>
            {bulkBusy ? "…" : "Permanently Delete User"}
          </button>
          <button type="button" className="btn btn-ghost" disabled={bulkBusy} onClick={() => setBulkOpen(false)}>
            Cancel
          </button>
        </div>
      </Modal>
    </AdminPage>
  );
}
