import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useDebounced } from "../../hooks/useDebounced";
import AdminPage from "../../components/AdminPage";
import CreateLocalUserModal, { type CreateLocalUserValues } from "../../components/users/CreateLocalUserModal";
import Modal from "../../components/Modal";
import RoleMultiSelect from "../../components/RoleMultiSelect";
import RowActionsMenu, { RowAction } from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
import { normalizeRole, roleLabel, type RoleRecord } from "../../lib/rbac";

function userPlanSelectValue(u: U): string {
  if (u.user_plan_mode === "none") return "__none__";
  if (u.user_plan_mode === "assigned" && u.user_plan_id) return String(u.user_plan_id);
  return "__inherit__";
}

type UserPlanDisplay = {
  planName: string | null;
  sourceTag: "gp" | "up" | null;
};

function resolveUserPlanDisplay(u: U): UserPlanDisplay {
  if (u.user_plan_mode === "assigned" && u.user_plan_name) {
    return { planName: u.user_plan_name, sourceTag: "up" };
  }
  if (u.user_plan_mode === "inherit" && u.inherited_plan_name) {
    return { planName: u.inherited_plan_name, sourceTag: "gp" };
  }
  return { planName: null, sourceTag: null };
}

function userPlanShowsSourceOverlay(u: U): boolean {
  return resolveUserPlanDisplay(u).sourceTag !== null;
}

function userPlanSelectTitle(u: U): string {
  const display = resolveUserPlanDisplay(u);
  if (display.sourceTag === "up" && display.planName) {
    return `(up) ${display.planName} — assigned directly to user`;
  }
  if (display.sourceTag === "gp" && display.planName) {
    const via = u.inherited_plan_source === "department" ? "department" : "group";
    return `(gp) ${display.planName} — inherited from ${via}`;
  }
  if (u.user_plan_mode === "none") return "No Plan — user blocked from inheriting group plan";
  return "No Plan";
}

function UserPlanSelect({
  user,
  plans,
  onAssign,
}: {
  user: U;
  plans: Plan[];
  onAssign: (userId: number, planId: string) => void;
}) {
  const planDisplay = resolveUserPlanDisplay(user);
  const showOverlay = userPlanShowsSourceOverlay(user);

  return (
    <div className="user-plan-select-wrap">
      {showOverlay ? (
        <span className="user-plan-select-label" aria-hidden="true">
          <span className="user-plan-source-tag">({planDisplay.sourceTag})</span>
          {planDisplay.planName}
        </span>
      ) : null}
      <select
        className={
          showOverlay
            ? "role-select user-plan-select user-plan-select--overlay"
            : "role-select user-plan-select"
        }
        value={userPlanSelectValue(user)}
        onChange={(e) => {
          onAssign(user.id, e.target.value);
        }}
        title={userPlanSelectTitle(user)}
      >
        <option value="__inherit__">From group</option>
        <option value="__none__">No Plan</option>
        {plans.map((p) => (
          <option key={p.id} value={String(p.id)}>{p.name}</option>
        ))}
      </select>
    </div>
  );
}

function formatBudgetRatio(used: number, total: number): string {
  if (total <= 0) return "No Plan";
  const fmt = (value: number) => {
    const rounded = Math.round(value * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
  };
  return `${fmt(used)}/${fmt(total)} $`;
}

type U = {
  id: number;
  username: string;
  email: string;
  display_name?: string;
  auth_provider: string;
  role: string;
  roles?: string[];
  is_active?: boolean;
  group_names?: string[];
  department?: string;
  job_title?: string;
  office?: string;
  reporting_to?: string;
  user_plan_id?: number | null;
  user_plan_name?: string | null;
  user_plan_mode?: "inherit" | "none" | "assigned";
  inherited_plan_id?: number | null;
  inherited_plan_name?: string | null;
  inherited_plan_source?: "group" | "department" | null;
  monthly_budget_usd: number;
  budget_used_usd: number;
};
type Plan = { id: number; name: string };
type GroupOption = { id: number; name: string };

type StatusFilter = "" | "enabled" | "disabled";
type BulkGroupAction = "" | "add" | "remove";
type BulkStatusAction = "" | "enable" | "disable";

type EditForm = {
  display_name: string;
  email: string;
  department: string;
  office: string;
  job_title: string;
  reporting_to: string;
  new_password: string;
  confirm_password: string;
};

const emptyEditForm: EditForm = {
  display_name: "",
  email: "",
  department: "",
  office: "",
  job_title: "",
  reporting_to: "",
  new_password: "",
  confirm_password: "",
};

export default function Users() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { confirm } = useConfirm();
  const filterGroupId = searchParams.get("group_id") || "";
  const filterGroupName = searchParams.get("group_name") || "";
  const [users, setUsers] = useState<U[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [filterUser, setFilterUser] = useState("");
  const [filterEmail, setFilterEmail] = useState("");
  const [filterDepartment, setFilterDepartment] = useState("");
  const [filterJobTitle, setFilterJobTitle] = useState("");
  const [filterRole, setFilterRole] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const debouncedUser = useDebounced(filterUser, 280);
  const debouncedEmail = useDebounced(filterEmail, 280);
  const debouncedDepartment = useDebounced(filterDepartment, 280);
  const debouncedJobTitle = useDebounced(filterJobTitle, 280);
  const [createOpen, setCreateOpen] = useState(false);
  const [flash, setFlash] = useState("");
  const [err, setErr] = useState("");
  const [keyModalOpen, setKeyModalOpen] = useState(false);
  const [keyModal, setKeyModal] = useState({ email: "", apiKey: "", url: "" });
  const [keyLoading, setKeyLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [editUser, setEditUser] = useState<U | null>(null);
  const [editForm, setEditForm] = useState<EditForm>(emptyEditForm);
  const [editSaving, setEditSaving] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [bulkDepartment, setBulkDepartment] = useState("");
  const [bulkOffice, setBulkOffice] = useState("");
  const [bulkPlanChoice, setBulkPlanChoice] = useState<string>("");
  const [bulkGroupId, setBulkGroupId] = useState("");
  const [bulkGroupAction, setBulkGroupAction] = useState<BulkGroupAction>("");
  const [bulkStatusAction, setBulkStatusAction] = useState<BulkStatusAction>("");
  const [roleCatalog, setRoleCatalog] = useState<RoleRecord[]>([]);
  const usersLoadSeq = useRef(0);

  function buildUsersQuery(): string {
    const params = new URLSearchParams();
    if (debouncedUser.trim()) params.set("username", debouncedUser.trim());
    if (debouncedEmail.trim()) params.set("email", debouncedEmail.trim());
    if (debouncedDepartment.trim()) params.set("department", debouncedDepartment.trim());
    if (debouncedJobTitle.trim()) params.set("job_title", debouncedJobTitle.trim());
    if (filterRole) params.set("role", filterRole);
    if (statusFilter === "enabled") params.set("is_active", "true");
    if (statusFilter === "disabled") params.set("is_active", "false");
    if (filterGroupId) params.set("group_id", filterGroupId);
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }

  async function loadUsers() {
    const seq = ++usersLoadSeq.current;
    try {
      const rows = await api<U[]>(`/api/admin/users${buildUsersQuery()}`);
      if (seq !== usersLoadSeq.current) return;
      const nextUsers = rows.map((u) => {
        const roles = (u.roles?.length ? u.roles : [u.role]).map(normalizeRole);
        return { ...u, roles, role: normalizeRole(u.role) };
      });
      setUsers(nextUsers);
      setSelectedUserIds((prev) => prev.filter((id) => nextUsers.some((u) => u.id === id)));
    } catch (e) {
      if (seq !== usersLoadSeq.current) return;
      setErr(String(e));
    }
  }

  function load() {
    void loadUsers();
    api<Plan[]>("/api/admin/plans").then(setPlans).catch(() => {});
    api<GroupOption[]>("/api/admin/groups").then(setGroups).catch(() => {});
  }

  useEffect(() => {
    void loadUsers();
    api<Plan[]>("/api/admin/plans").then(setPlans).catch(() => {});
    api<GroupOption[]>("/api/admin/groups").then(setGroups).catch(() => {});
    api<RoleRecord[]>("/api/admin/roles").then(setRoleCatalog).catch(() => {});
  }, [debouncedUser, debouncedEmail, debouncedDepartment, debouncedJobTitle, filterRole, statusFilter, filterGroupId]);

  async function createLocalUser(values: CreateLocalUserValues) {
    setErr("");
    const body: Record<string, unknown> = {
      username: values.username,
      email: values.email,
      password: values.password,
      role: values.role,
      display_name: values.display_name || undefined,
      department: values.department || undefined,
      job_title: values.job_title || undefined,
      group_id: values.group_id ?? undefined,
    };
    if (values.budget_plan === "__inherit__") {
      body.inherit_group_plan = true;
    } else if (values.budget_plan === "__none__") {
      body.no_plan = true;
    } else {
      body.plan_id = Number(values.budget_plan);
    }
    await api("/api/admin/users", {
      method: "POST",
      body: JSON.stringify(body),
    });
    setFlash("User created.");
    load();
  }

  async function changeRoles(userId: number, roles: string[]) {
    const next = roles.map(normalizeRole);
    const previousUser = users.find((u) => u.id === userId);
    const previous = (previousUser?.roles?.length ? previousUser.roles : [previousUser?.role || "user"]).map(
      normalizeRole,
    );
    setUsers((list) =>
      list.map((u) =>
        u.id === userId ? { ...u, roles: next, role: next[0] || "user" } : u,
      ),
    );
    setErr("");
    try {
      const updated = await api<{ id: number; role: string; roles: string[] }>(`/api/admin/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ roles: next }),
      });
      const saved = (updated.roles?.length ? updated.roles : [updated.role]).map(normalizeRole);
      setUsers((list) =>
        list.map((u) =>
          u.id === userId ? { ...u, roles: saved, role: normalizeRole(updated.role) } : u,
        ),
      );
      const label =
        saved.length === 1
          ? roleLabel(roleCatalog, saved[0])
          : `${saved.length} roles`;
      setFlash(`Roles updated (${label}).`);
      await loadUsers();
    } catch (e) {
      setUsers((list) =>
        list.map((u) =>
          u.id === userId ? { ...u, roles: previous, role: previous[0] || "user" } : u,
        ),
      );
      setErr(String(e));
    }
  }

  async function assignPlan(userId: number, planId: string) {
    setErr("");
    const optimisticMode =
      planId === "__none__" ? "none" : planId === "__inherit__" ? "inherit" : "assigned";
    const optimisticPlanId =
      planId === "__none__" || planId === "__inherit__" ? null : Number(planId);
    const selected = planId !== "__none__" && planId !== "__inherit__" ? plans.find((p) => p.id === Number(planId)) : null;
    setUsers((list) =>
      list.map((u) =>
        u.id === userId
          ? {
              ...u,
              user_plan_mode: optimisticMode,
              user_plan_id: optimisticPlanId,
              user_plan_name: selected?.name || null,
              inherited_plan_id: planId === "__inherit__" ? u.inherited_plan_id ?? null : null,
              inherited_plan_name: planId === "__inherit__" ? u.inherited_plan_name ?? null : null,
              inherited_plan_source: planId === "__inherit__" ? u.inherited_plan_source ?? null : null,
            }
          : u,
      ),
    );
    try {
      const body =
        planId === "__inherit__"
          ? { inherit_group_plan: true }
          : planId === "__none__"
            ? { no_plan: true }
            : { plan_id: Number(planId) };
      await api(`/api/admin/users/${userId}/plan`, { method: "PATCH", body: JSON.stringify(body) });
      await loadUsers();
    } catch (e) {
      setErr(String(e));
      await loadUsers();
    }
  }

  async function clearUserPlan(userId: number) {
    await api(`/api/admin/users/${userId}/plan`, { method: "PATCH", body: JSON.stringify({ no_plan: true }) });
    load();
  }

  async function budgetReset(userId: number) {
    await api(`/api/admin/users/${userId}/budget-reset`, { method: "POST" });
    setFlash(`Budget reset for user #${userId}`);
    load();
  }

  async function getApiKey(userId: number, email: string) {
    setKeyLoading(true);
    setCopied(false);
    setKeyModalOpen(true);
    setKeyModal({ email, apiKey: "Generating…", url: "" });
    try {
      const res = await api<{ api_key: string; url: string }>(`/api/admin/users/${userId}/api-keys`, { method: "POST" });
      setKeyModal({ email, apiKey: res.api_key, url: res.url });
    } catch (e) {
      setKeyModal({ email, apiKey: `Error: ${e}`, url: "" });
    } finally {
      setKeyLoading(false);
    }
  }

  function openEditUser(u: U) {
    setEditUser(u);
    setEditForm({
      display_name: u.display_name || "",
      email: u.email || "",
      department: u.department || "",
      office: u.office || "",
      job_title: u.job_title || "",
      reporting_to: u.reporting_to || "",
      new_password: "",
      confirm_password: "",
    });
  }

  async function saveEditUser(e: FormEvent) {
    e.preventDefault();
    if (!editUser) return;
    setEditSaving(true);
    setErr("");
    const isLocal = editUser.auth_provider === "local";
    const wantsPassword = isLocal && (editForm.new_password || editForm.confirm_password);
    if (wantsPassword) {
      if (editForm.new_password.length < 6) {
        setErr("Password must be at least 6 characters.");
        setEditSaving(false);
        return;
      }
      if (editForm.new_password !== editForm.confirm_password) {
        setErr("Passwords do not match.");
        setEditSaving(false);
        return;
      }
    }
    try {
      const updated = await api<U>(`/api/admin/users/${editUser.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          display_name: editForm.display_name,
          email: editForm.email,
          department: editForm.department,
          office: editForm.office,
          job_title: editForm.job_title,
          reporting_to: editForm.reporting_to,
        }),
      });
      if (wantsPassword) {
        await api(`/api/admin/users/${editUser.id}/reset-password`, {
          method: "POST",
          body: JSON.stringify({ password: editForm.new_password }),
        });
      }
      setUsers((list) =>
        list.map((u) =>
          u.id === editUser.id
            ? {
                ...u,
                ...updated,
                role: normalizeRole(updated.role),
              }
            : u,
        ),
      );
      setFlash(wantsPassword ? "User updated and password reset." : "User updated.");
      setEditUser(null);
      setEditForm(emptyEditForm);
      await loadUsers();
    } catch (err) {
      setErr(String(err));
    } finally {
      setEditSaving(false);
    }
  }

  async function setUserActive(u: U, active: boolean) {
    const verb = active ? "Active" : "Deactive";
    const ok = await confirm({
      title: `${verb} user`,
      message: active
        ? `Set "${u.username}" active? They will regain chat and API access.`
        : `Deactivate "${u.username}"? They can still sign in but only view their logs.`,
      confirmLabel: verb,
      cancelLabel: "Cancel",
      danger: !active,
    });
    if (!ok) return;
    setErr("");
    try {
      await api(`/api/admin/users/${u.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: active }),
      });
      setFlash(`User "${u.username}" ${active ? "activated" : "deactivated"}.`);
      await loadUsers();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function deleteLocalUser(u: U) {
    const ok = await confirm({
      title: "Move to Deleted Users",
      message: `Move "${u.username}" to Deleted Users? They will not be able to sign in. Account data stays on the server until permanently deleted from Deleted Users.`,
      confirmLabel: "Move to Deleted Users",
      cancelLabel: "No",
      danger: true,
    });
    if (!ok) return;
    setErr("");
    try {
      await api(`/api/admin/users/${u.id}`, { method: "DELETE" });
      if (editUser?.id === u.id) {
        setEditUser(null);
        setEditForm(emptyEditForm);
      }
      setFlash(`User "${u.username}" moved to Deleted Users.`);
      await loadUsers();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function copyKey() {
    if (!keyModal.apiKey || keyModal.apiKey.startsWith("Error")) return;
    try {
      await navigator.clipboard.writeText(keyModal.apiKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = keyModal.apiKey;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  const prov = (p: string) =>
    `badge badge-${p === "local" ? "local" : p === "ldap" ? "ldap" : p === "saml" ? "saml" : "keycloak"}`;

  function userRowActions(u: U): RowAction[] {
    const items: RowAction[] = [
      {
        label: USAGE_AND_ACTIVITY_LABEL,
        menuWrap: true,
        onClick: () => navigate(`/admin/users/${u.id}/activity`),
      },
      {
        label: "User Storage",
        onClick: () => navigate(`/admin/users/${u.id}/media`),
      },
      { label: "Edit user", onClick: () => openEditUser(u) },
      {
        label: u.is_active === false ? "Active" : "Deactive",
        onClick: () => void setUserActive(u, u.is_active === false),
        danger: u.is_active !== false,
      },
    ];
    if (u.auth_provider === "local") {
      items.push({ label: "Delete", onClick: () => void deleteLocalUser(u), danger: true });
    }
    items.push(
      { label: "Budget reset", onClick: () => budgetReset(u.id) },
      { label: "Get API key", onClick: () => getApiKey(u.id, u.email) },
    );
    return items;
  }

  const allVisibleSelected = useMemo(
    () => users.length > 0 && users.every((u) => selectedUserIds.includes(u.id)),
    [users, selectedUserIds],
  );

  function toggleUserSelection(userId: number) {
    setSelectedUserIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId],
    );
  }

  function toggleSelectAllVisible() {
    setSelectedUserIds((prev) => {
      if (allVisibleSelected) {
        return prev.filter((id) => !users.some((u) => u.id === id));
      }
      const merged = new Set(prev);
      for (const u of users) merged.add(u.id);
      return Array.from(merged);
    });
  }

  function openBulkEdit() {
    setBulkDepartment("");
    setBulkOffice("");
    setBulkPlanChoice("");
    setBulkGroupId("");
    setBulkGroupAction("");
    setBulkStatusAction("");
    setBulkOpen(true);
  }

  function setGroupFilter(groupId: string, groupName = "") {
    const next = new URLSearchParams(searchParams);
    if (groupId) {
      next.set("group_id", groupId);
      if (groupName) next.set("group_name", groupName);
      else next.delete("group_name");
    } else {
      next.delete("group_id");
      next.delete("group_name");
    }
    setSearchParams(next, { replace: true });
  }

  function clearFilters() {
    setFilterUser("");
    setFilterEmail("");
    setFilterDepartment("");
    setFilterJobTitle("");
    setFilterRole("");
    setStatusFilter("");
    setGroupFilter("");
  }

  async function saveBulkEdit(e: FormEvent) {
    e.preventDefault();
    if (!selectedUserIds.length) return;

    const hasGroup = bulkGroupId && bulkGroupAction;
    const hasStatus = bulkStatusAction === "enable" || bulkStatusAction === "disable";
    const hasDept = bulkDepartment.trim().length > 0;
    const hasOffice = bulkOffice.trim().length > 0;
    const hasPlan = Boolean(bulkPlanChoice);

    if (!hasGroup && !hasStatus && !hasDept && !hasOffice && !hasPlan) {
      setErr("Choose at least one bulk change (group, status, plan, department, or office).");
      return;
    }
    if (bulkGroupId && !bulkGroupAction) {
      setErr("Select Add to group or Remove from group.");
      return;
    }
    if (bulkGroupAction && !bulkGroupId) {
      setErr("Select a group for the membership change.");
      return;
    }

    setBulkSaving(true);
    setErr("");
    try {
      const body: Record<string, unknown> = { user_ids: selectedUserIds };
      if (hasStatus) body.is_active = bulkStatusAction === "enable";
      if (hasGroup) {
        body.group_id = Number(bulkGroupId);
        body.group_action = bulkGroupAction;
      }
      if (hasDept) body.department = bulkDepartment.trim();
      if (hasOffice) body.office = bulkOffice.trim();
      if (bulkPlanChoice === "__none__") body.no_plan = true;
      else if (bulkPlanChoice === "__inherit__") body.inherit_group_plan = true;
      else if (bulkPlanChoice) body.plan_id = Number(bulkPlanChoice);

      await api("/api/admin/users/bulk", { method: "POST", body: JSON.stringify(body) });
      setFlash(`Bulk edit applied to ${selectedUserIds.length} user(s).`);
      setBulkOpen(false);
      await loadUsers();
    } catch (e2) {
      setErr(String(e2));
    } finally {
      setBulkSaving(false);
    }
  }

  return (
    <AdminPage title="Users">
      {flash && <p className="alert alert-success">{flash}</p>}
      {err && <p className="alert alert-error">{err}</p>}
      {filterGroupId ? (
        <p className="alert card" style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
          <span>
            Showing members of{" "}
            <strong>{filterGroupName || groups.find((g) => String(g.id) === filterGroupId)?.name || `group #${filterGroupId}`}</strong>
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setGroupFilter("")}>
            Clear group filter
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigate("/admin/groups")}>
            Back to Groups
          </button>
        </p>
      ) : null}
      <div className="users-status-filters">
        <span className="muted-text" style={{ marginRight: "0.25rem" }}>
          Status:
        </span>
        <button
          type="button"
          className={`btn btn-ghost${statusFilter === "" ? " is-active" : ""}`}
          onClick={() => setStatusFilter("")}
        >
          All
        </button>
        <button
          type="button"
          className={`btn btn-ghost${statusFilter === "enabled" ? " is-active" : ""}`}
          onClick={() => setStatusFilter("enabled")}
        >
          Active Users
        </button>
        <button
          type="button"
          className={`btn btn-ghost${statusFilter === "disabled" ? " is-active" : ""}`}
          onClick={() => setStatusFilter("disabled")}
        >
          Deactive Users
        </button>
      </div>

      <div className="users-filter-panel card">
        <div>
          <label>User</label>
          <input
            placeholder="Username or display name"
            value={filterUser}
            onChange={(e) => setFilterUser(e.target.value)}
          />
        </div>
        <div>
          <label>Email</label>
          <input placeholder="Email" value={filterEmail} onChange={(e) => setFilterEmail(e.target.value)} />
        </div>
        <div>
          <label>Department</label>
          <input
            placeholder="Department"
            value={filterDepartment}
            onChange={(e) => setFilterDepartment(e.target.value)}
          />
        </div>
        <div>
          <label>Job title</label>
          <input
            placeholder="Job title"
            value={filterJobTitle}
            onChange={(e) => setFilterJobTitle(e.target.value)}
          />
        </div>
        <div>
          <label>Role</label>
          <select value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
            <option value="">All roles</option>
            {roleCatalog.map((role) => (
              <option key={role.slug} value={role.slug}>
                {role.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>Group</label>
          <select value={filterGroupId} onChange={(e) => setGroupFilter(e.target.value, groups.find((g) => String(g.id) === e.target.value)?.name || "")}>
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g.id} value={String(g.id)}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="search-bar">
        <button type="button" className="btn btn-ghost" onClick={clearFilters}>
          Clear filters
        </button>
        <button
          className="btn btn-ghost"
          type="button"
          onClick={openBulkEdit}
          disabled={selectedUserIds.length === 0}
          title={selectedUserIds.length ? `Edit ${selectedUserIds.length} selected users` : "Select users first"}
        >
          Bulk Edit ({selectedUserIds.length})
        </button>
        <button className="btn" type="button" onClick={() => setCreateOpen(true)}>
          + Local user
        </button>
      </div>

      <div className="table-wrap table-wrap--users">
        <table className="card data-table users-table">
          <thead>
            <tr>
              <th className="col-sm">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleSelectAllVisible}
                  aria-label="Select all users"
                />
              </th>
              <th className="col-user">User</th>
              <th className="col-md">Email</th>
              <th className="col-md">Group</th>
              <th className="col-lg">Department</th>
              <th className="col-lg">Office</th>
              <th className="col-lg">Job title</th>
              <th className="col-sm">Auth</th>
              <th className="col-role">Role</th>
              <th className="col-sm">User Plan</th>
              <th className="col-budget">Budget</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.is_active === false ? "row-disabled" : ""}>
                <td className="col-sm">
                  <input
                    type="checkbox"
                    checked={selectedUserIds.includes(u.id)}
                    onChange={() => toggleUserSelection(u.id)}
                    aria-label={`Select ${u.username}`}
                  />
                </td>
                <td className="col-user">
                  <div className="user-name-cell">
                    <span className="user-name-cell__line">
                      <span className="user-name-cell__username">{u.username}</span>
                      {u.is_active === false && (
                        <span className="user-deactivated-label">(Deactivated)</span>
                      )}
                    </span>
                  </div>
                </td>
                <td className="col-md">{u.email || "—"}</td>
                <td className="col-md">{(u.group_names ?? []).length ? (u.group_names ?? []).join(", ") : "—"}</td>
                <td className="col-lg">{u.department || "—"}</td>
                <td className="col-lg">{u.office || "—"}</td>
                <td className="col-lg">{u.job_title || "—"}</td>
                <td className="col-sm"><span className={prov(u.auth_provider)}>{u.auth_provider}</span></td>
                <td className="col-role">
                  <RoleMultiSelect
                    value={u.roles?.length ? u.roles : [u.role]}
                    roles={roleCatalog}
                    onChange={(roles) => void changeRoles(u.id, roles)}
                  />
                </td>
                <td className="col-sm">
                  <UserPlanSelect user={u} plans={plans} onAssign={assignPlan} />
                </td>
                <td className="col-budget">{formatBudgetRatio(u.budget_used_usd || 0, u.monthly_budget_usd || 0)}</td>
                <td className="col-actions">
                  <RowActionsMenu actions={userRowActions(u)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editUser} title="Edit User" onClose={() => setEditUser(null)}>
        {editUser && (
          <form onSubmit={saveEditUser}>
            <p className="muted-text">
              <strong>{editUser.username}</strong>
              {" · "}
              <span className={prov(editUser.auth_provider)}>{editUser.auth_provider}</span>
            </p>
            {editUser.auth_provider !== "local" && (
              <p className="muted-text" style={{ marginBottom: "0.75rem" }}>
                Profile fields sync from{" "}
                {editUser.auth_provider === "ldap" ? "LDAP" : editUser.auth_provider === "saml" ? "SAML" : "directory"} on
                login; you can override them here.
              </p>
            )}
            <label>Display name</label>
            <input
              className="input-block"
              value={editForm.display_name}
              onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })}
            />
            <label>Email</label>
            <input
              type="email"
              className="input-block"
              value={editForm.email}
              onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
            />
            <label>Department</label>
            <input
              className="input-block"
              value={editForm.department}
              onChange={(e) => setEditForm({ ...editForm, department: e.target.value })}
            />
            <label>Office</label>
            <input
              className="input-block"
              value={editForm.office}
              onChange={(e) => setEditForm({ ...editForm, office: e.target.value })}
            />
            <label>Job title</label>
            <input
              className="input-block"
              value={editForm.job_title}
              onChange={(e) => setEditForm({ ...editForm, job_title: e.target.value })}
            />
            <label>Reports to</label>
            <input
              className="input-block"
              value={editForm.reporting_to}
              onChange={(e) => setEditForm({ ...editForm, reporting_to: e.target.value })}
            />
            {editUser.auth_provider === "local" && (
              <>
                <h4 style={{ marginTop: "1.25rem" }}>Reset password</h4>
                <p className="muted-text">Leave blank to keep the current password.</p>
                <label>New password</label>
                <input
                  type="password"
                  className="input-block"
                  autoComplete="new-password"
                  value={editForm.new_password}
                  onChange={(e) => setEditForm({ ...editForm, new_password: e.target.value })}
                />
                <label>Confirm password</label>
                <input
                  type="password"
                  className="input-block"
                  autoComplete="new-password"
                  value={editForm.confirm_password}
                  onChange={(e) => setEditForm({ ...editForm, confirm_password: e.target.value })}
                />
              </>
            )}
            <div className="dialog-actions">
              <button type="submit" className="btn" disabled={editSaving}>
                {editSaving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                className="btn btn-ghost dialog-actions-cancel"
                onClick={() => setEditUser(null)}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </Modal>

      <Modal open={keyModalOpen} title="API Key" onClose={() => setKeyModalOpen(false)}>
        <p className="muted-text">User: <strong>{keyModal.email}</strong></p>
        <label>API Key</label>
        <input readOnly value={keyModal.apiKey} className="input-block mono" />
        {keyModal.url && (
          <>
            <label>Open WebUI URL</label>
            <input readOnly value={keyModal.url} className="input-block mono" />
          </>
        )}
        <p className="muted-text" style={{ marginTop: "0.75rem" }}>Store this key securely. It may not be shown again in full.</p>
        <div className="dialog-actions">
          <button
            type="button"
            className="btn"
            onClick={copyKey}
            disabled={keyLoading || keyModal.apiKey.startsWith("Error")}
          >
            {copied ? "Copied!" : "Copy"}
          </button>
          <button type="button" className="btn btn-ghost dialog-actions-cancel" onClick={() => setKeyModalOpen(false)}>
            Close
          </button>
        </div>
      </Modal>

      <Modal open={bulkOpen} title={`Bulk Edit (${selectedUserIds.length} users)`} onClose={() => setBulkOpen(false)}>
        <form onSubmit={saveBulkEdit}>
          <p className="muted-text">
            Apply one or more changes to the selected users. Use status filter (Active Users / Deactive Users) first to narrow the
            list, then select rows and apply bulk actions.
          </p>
          <label>Group</label>
          <select
            className="input-block"
            value={bulkGroupId}
            onChange={(e) => setBulkGroupId(e.target.value)}
          >
            <option value="">No group change</option>
            {groups.map((g) => (
              <option key={g.id} value={String(g.id)}>
                {g.name}
              </option>
            ))}
          </select>
          <label>Group membership</label>
          <select
            className="input-block"
            value={bulkGroupAction}
            onChange={(e) => setBulkGroupAction(e.target.value as BulkGroupAction)}
            disabled={!bulkGroupId}
          >
            <option value="">—</option>
            <option value="add">Add to group</option>
            <option value="remove">Remove from group</option>
          </select>
          <label>Account status</label>
          <select
            className="input-block"
            value={bulkStatusAction}
            onChange={(e) => setBulkStatusAction(e.target.value as BulkStatusAction)}
          >
            <option value="">No change</option>
            <option value="enable">Active</option>
            <option value="disable">Deactive</option>
          </select>
          <label>User Plan</label>
          <select
            className="input-block"
            value={bulkPlanChoice}
            onChange={(e) => setBulkPlanChoice(e.target.value)}
          >
            <option value="">No change</option>
            <option value="__inherit__">From group</option>
            <option value="__none__">No Plan</option>
            {plans.map((p) => (
              <option key={p.id} value={String(p.id)}>{p.name}</option>
            ))}
          </select>
          <label>Department</label>
          <input
            className="input-block"
            value={bulkDepartment}
            onChange={(e) => setBulkDepartment(e.target.value)}
            placeholder="No change"
          />
          <label>Office</label>
          <input
            className="input-block"
            value={bulkOffice}
            onChange={(e) => setBulkOffice(e.target.value)}
            placeholder="No change"
          />
          <div className="dialog-actions">
            <button type="submit" className="btn" disabled={bulkSaving || selectedUserIds.length === 0}>
              {bulkSaving ? "Applying…" : "Apply"}
            </button>
            <button
              type="button"
              className="btn btn-ghost dialog-actions-cancel"
              onClick={() => setBulkOpen(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      </Modal>

      <CreateLocalUserModal
        open={createOpen}
        roles={roleCatalog}
        plans={plans}
        onClose={() => setCreateOpen(false)}
        onSubmit={createLocalUser}
      />
    </AdminPage>
  );
}
