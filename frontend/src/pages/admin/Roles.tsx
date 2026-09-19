import { FormEvent, useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import { api } from "../../api";
import { roleLabel, type RoleRecord } from "../../lib/rbac";
import { useConfirm } from "../../context/ConfirmContext";

type UserRow = {
  id: number;
  username: string;
  display_name?: string;
  email: string;
  role: string;
};

export default function Roles() {
  const { confirm } = useConfirm();
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [err, setErr] = useState("");
  const [flash, setFlash] = useState("");
  const [query, setQuery] = useState("");
  const [selectedRoleSlugs, setSelectedRoleSlugs] = useState<string[]>([]);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignUserIds, setAssignUserIds] = useState<number[]>([]);
  const [assignUserQuery, setAssignUserQuery] = useState("");
  const [assignSaving, setAssignSaving] = useState(false);

  const selectedSlugs = useMemo(() => new Set(selectedRoleSlugs), [selectedRoleSlugs]);

  useEffect(() => {
    api<RoleRecord[]>("/api/admin/roles")
      .then(setRoles)
      .catch((e) => setErr(String(e)));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = [...roles].sort((a, b) => a.name.localeCompare(b.name));
    if (!q) return list;
    return list.filter(
      (role) =>
        role.name.toLowerCase().includes(q) ||
        role.description.toLowerCase().includes(q) ||
        role.category.toLowerCase().includes(q),
    );
  }, [query, roles]);

  const selectedRoles = useMemo(
    () => roles.filter((role) => selectedSlugs.has(role.slug)),
    [roles, selectedSlugs],
  );

  const filteredAssignUsers = useMemo(() => {
    const q = assignUserQuery.trim().toLowerCase();
    if (!q) return users;
    return users.filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        (u.display_name || "").toLowerCase().includes(q) ||
        (u.email || "").toLowerCase().includes(q),
    );
  }, [assignUserQuery, users]);

  function toggleRole(slug: string) {
    setSelectedRoleSlugs((prev) =>
      prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug],
    );
  }

  function toggleAllVisible(checked: boolean) {
    setSelectedRoleSlugs(checked ? filtered.map((r) => r.slug) : []);
  }

  function openAssignModal() {
    if (selectedRoles.length === 0) return;
    setErr("");
    setFlash("");
    setAssignUserIds([]);
    setAssignUserQuery("");
    setAssignOpen(true);
    api<UserRow[]>("/api/admin/users")
      .then(setUsers)
      .catch((e) => setErr(String(e)));
  }

  function toggleAssignUser(userId: number) {
    setAssignUserIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId],
    );
  }

  async function submitAssign(e: FormEvent) {
    e.preventDefault();
    const slugs = selectedRoles.map((r) => r.slug);
    if (slugs.length === 0 || assignUserIds.length === 0) {
      setErr("Select at least one role and at least one user.");
      return;
    }
    // This replaces the user's whole role set - it always did, silently. An
    // administrator assigning "Reports" to someone who also held "API Logs"
    // removed "API Logs", with no confirmation, no undo and nothing in the
    // flash message to say so.
    const names = selectedRoles.map((r) => r.name).join(", ");
    const ok = await confirm({
      title: "Replace roles",
      message: `${assignUserIds.length} user${assignUserIds.length === 1 ? "" : "s"} will hold exactly ${names}. Any other role they currently have will be removed.`,
      emphasize: "Any other role they currently have will be removed",
      confirmLabel: "Replace roles",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    setAssignSaving(true);
    setErr("");
    try {
      await api("/api/admin/users/bulk", {
        method: "POST",
        body: JSON.stringify({ user_ids: assignUserIds, roles: slugs }),
      });
      setFlash(
        `${assignUserIds.length} user${assignUserIds.length === 1 ? "" : "s"} now hold exactly: ${names}.`,
      );
      setAssignOpen(false);
      setSelectedRoleSlugs([]);
    } catch (e2) {
      setErr(String(e2));
    } finally {
      setAssignSaving(false);
    }
  }

  const allVisibleSelected = filtered.length > 0 && filtered.every((r) => selectedSlugs.has(r.slug));

  return (
    <AdminPage
      title="Roles"
      actions={
        selectedRoles.length > 0 ? (
          <button type="button" className="btn" onClick={openAssignModal}>
            Assign Roles ({selectedRoles.length})
          </button>
        ) : null
      }
    >
      <p className="muted-text">
        Built-in RBAC roles define which admin sections a user can open and whether they can change settings. Select one
        or more roles, then use <strong>Assign Roles</strong> to apply them to users.
      </p>

      {flash && <p className="alert alert-success">{flash}</p>}
      {err && !assignOpen && <p className="alert alert-error" role="alert">{err}</p>}

      <div className="admin-toolbar roles-toolbar">
        <input
          type="search"
          className="input-block roles-toolbar__search"
          placeholder="Search roles…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="table-wrap table-wrap--roles">
        <table className="card data-table roles-table">
          <thead>
            <tr>
              <th className="roles-table__check">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={(e) => toggleAllVisible(e.target.checked)}
                  aria-label="Select all visible roles"
                />
              </th>
              <th>Name</th>
              <th>Description</th>
              <th>Category</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((role) => (
              <tr key={role.slug} className={selectedSlugs.has(role.slug) ? "row-selected" : ""}>
                <td className="roles-table__check">
                  <input
                    type="checkbox"
                    checked={selectedSlugs.has(role.slug)}
                    onChange={() => toggleRole(role.slug)}
                    aria-label={`Select ${role.name}`}
                  />
                </td>
                <td className="roles-table__name">
                  <strong>{role.name}</strong>
                  {role.read_only && <span className="badge badge-muted">Read only</span>}
                </td>
                <td className="roles-table__desc">{role.description}</td>
                <td className="roles-table__category">{role.category}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length === 0 && !err && <p className="muted-text">No roles match your search.</p>}

      <Modal open={assignOpen} title="Assign Roles" onClose={() => setAssignOpen(false)}>
        <form onSubmit={submitAssign}>
          {err && assignOpen && <p className="alert alert-error" role="alert">{err}</p>}
          <p className="muted-text">
            The selected users will hold <strong>exactly</strong> these {selectedRoles.length} role
            {selectedRoles.length === 1 ? "" : "s"}. Any other role they currently have is removed.
          </p>
          <ul className="roles-assign-summary">
            {selectedRoles.map((role) => (
              <li key={role.slug}>{role.name}</li>
            ))}
          </ul>
          <label className="form-label" style={{ marginTop: "1rem" }} htmlFor="roles-users">
            Users
          </label>
          <input id="roles-users"
            type="search"
            className="input-block"
            placeholder="Filter users…"
            value={assignUserQuery}
            onChange={(e) => setAssignUserQuery(e.target.value)}
          />
          <div className="roles-assign-users">
            {filteredAssignUsers.map((u) => (
              <label key={u.id} className="roles-assign-users__row">
                <input
                  type="checkbox"
                  checked={assignUserIds.includes(u.id)}
                  onChange={() => toggleAssignUser(u.id)}
                />
                <span>
                  <strong>{u.username}</strong>
                  {u.display_name && u.display_name !== u.username ? ` (${u.display_name})` : ""}
                  {u.email ? ` · ${u.email}` : ""}
                  <span className="muted-text"> · {roleLabel(roles, u.role)}</span>
                </span>
              </label>
            ))}
            {filteredAssignUsers.length === 0 && <p className="muted-text">No users match.</p>}
          </div>
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={() => setAssignOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn" disabled={assignSaving || assignUserIds.length === 0}>
              {assignSaving ? "Assigning…" : `Assign to ${assignUserIds.length || 0} user${assignUserIds.length === 1 ? "" : "s"}`}
            </button>
          </div>
        </form>
      </Modal>
    </AdminPage>
  );
}
