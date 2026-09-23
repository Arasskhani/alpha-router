import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, apiList, authFetch, formatApiError, getCachedSession, NO_LIST_BOUNDS, type ListBounds } from "../../api";
import { useDebounced } from "../../hooks/useDebounced";
import AdminPage from "../../components/AdminPage";
import FilterPanel, { countActiveFilters } from "../../components/FilterPanel";
import CreateLocalUserModal, { type CreateLocalUserValues } from "../../components/users/CreateLocalUserModal";
import Modal from "../../components/Modal";
import RoleMultiSelect from "../../components/RoleMultiSelect";
import ListTruncatedBanner from "../../components/ListTruncatedBanner";
import RowActionsMenu, { RowAction } from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
import { signInActivityPathForUser } from "../../lib/signInActivity";
import {
  PRESENCE_REFRESH_INTERVAL_MS,
  presenceAvailableFromUserRows,
} from "../../lib/presence";
import { normalizeRole, roleLabel, userHasSuperAdminAccess, type RoleRecord } from "../../lib/rbac";
import { useTableCards } from "../../hooks/useTableCards";

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

function formatBudgetUsd(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

function formatBudgetRatio(used: number, total: number): string {
  if (total <= 0) return "No Plan";
  return `${formatBudgetUsd(used)}/${formatBudgetUsd(total)} $`;
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
  totp_enabled?: boolean;
  group_names?: string[];
  company?: string;
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
  budget_reserved_usd?: number;
  /** Reported online within the presence TTL. `null` when presence is unavailable. */
  online?: boolean | null;
};

function userLabel(u: { username?: string; display_name?: string } | null | undefined): string {
  if (!u) return "user";
  return (u.display_name || u.username || "").trim() || "user";
}

async function downloadUsersCsv(path: string): Promise<void> {
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
  a.download = match?.[1] ?? "alpharouter-users.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

type Plan = { id: number; name: string };
type GroupOption = { id: number; name: string };

type StatusFilter = "" | "enabled" | "disabled" | "online";
type BulkGroupAction = "" | "add" | "remove";
type BulkStatusAction = "" | "enable" | "disable";

type EditForm = {
  display_name: string;
  email: string;
  company: string;
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
  company: "",
  department: "",
  office: "",
  job_title: "",
  reporting_to: "",
  new_password: "",
  confirm_password: "",
};

/** Accounts per page. A screenful and a bit; the filters do the narrowing. */
const USERS_PAGE_SIZE = 100;

export default function Users() {
  // On a phone the table is drawn as a list of cards (styles.css).
  const tableCardsRef = useTableCards<HTMLTableElement>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { confirm } = useConfirm();
  const filterGroupId = searchParams.get("group_id") || "";
  const filterGroupName = searchParams.get("group_name") || "";
  const [users, setUsers] = useState<U[]>([]);
  const [usersBounds, setUsersBounds] = useState<ListBounds>(NO_LIST_BOUNDS);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [filterUser, setFilterUser] = useState("");
  const [filterEmail, setFilterEmail] = useState("");
  const [filterDepartment, setFilterDepartment] = useState("");
  const [filterJobTitle, setFilterJobTitle] = useState("");
  const [filterRole, setFilterRole] = useState("");
  const [filterPlan, setFilterPlan] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [exporting, setExporting] = useState(false);
  const debouncedUser = useDebounced(filterUser, 280);
  const debouncedEmail = useDebounced(filterEmail, 280);
  const debouncedDepartment = useDebounced(filterDepartment, 280);
  const debouncedJobTitle = useDebounced(filterJobTitle, 280);
  const [createOpen, setCreateOpen] = useState(false);
  const [flash, setFlash] = useState("");
  const [err, setErr] = useState("");
  const [editUser, setEditUser] = useState<U | null>(null);
  const [editForm, setEditForm] = useState<EditForm>(emptyEditForm);
  const [editSaving, setEditSaving] = useState(false);
  const [disable2faBusy, setDisable2faBusy] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [bulkDepartment, setBulkDepartment] = useState("");
  const [bulkOffice, setBulkOffice] = useState("");
  const [bulkPlanChoice, setBulkPlanChoice] = useState<string>("");
  const [bulkGroupId, setBulkGroupId] = useState("");
  const [bulkGroupAction, setBulkGroupAction] = useState<BulkGroupAction>("");
  const [bulkStatusAction, setBulkStatusAction] = useState<BulkStatusAction>("");
  const [addToGroupUser, setAddToGroupUser] = useState<U | null>(null);
  const [addToGroupId, setAddToGroupId] = useState("");
  const [addToGroupSaving, setAddToGroupSaving] = useState(false);
  const [roleCatalog, setRoleCatalog] = useState<RoleRecord[]>([]);
  const [presenceAvailable, setPresenceAvailable] = useState(true);
  // Paged in the database: one page of accounts at a time. Filters reset to
  // the first page; Previous/Next move through the filtered list.
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState<number | null>(null);
  const usersLoadSeq = useRef(0);

  function buildUsersQuery(): string {
    const params = new URLSearchParams();
    if (debouncedUser.trim()) params.set("username", debouncedUser.trim());
    if (debouncedEmail.trim()) params.set("email", debouncedEmail.trim());
    if (debouncedDepartment.trim()) params.set("department", debouncedDepartment.trim());
    if (debouncedJobTitle.trim()) params.set("job_title", debouncedJobTitle.trim());
    if (filterRole) params.set("role", filterRole);
    if (filterPlan === "__none__") params.set("no_plan", "true");
    else if (filterPlan) params.set("plan_id", filterPlan);
    if (statusFilter === "enabled") params.set("is_active", "true");
    if (statusFilter === "disabled") params.set("is_active", "false");
    if (statusFilter === "online") {
      params.set("online", "true");
      params.set("is_active", "true");
    }
    if (filterGroupId) params.set("group_id", filterGroupId);
    params.set("limit", String(USERS_PAGE_SIZE));
    params.set("offset", String(offset));
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }

  async function loadUsers() {
    const seq = ++usersLoadSeq.current;
    try {
      const { data: rows, bounds, page } = await apiList<U[]>(`/api/admin/users${buildUsersQuery()}`);
      if (seq !== usersLoadSeq.current) return;
      setUsersBounds(bounds);
      setHasMore(page.hasMore);
      setTotal(page.total);
      const nextUsers = rows.map((u) => {
        const roles = (u.roles?.length ? u.roles : [u.role]).map(normalizeRole);
        return { ...u, roles, role: normalizeRole(u.role) };
      });
      setUsers(nextUsers);
      setPresenceAvailable(presenceAvailableFromUserRows(nextUsers));
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
  }, [debouncedUser, debouncedEmail, debouncedDepartment, debouncedJobTitle, filterRole, filterPlan, statusFilter, filterGroupId, offset]);

  // A changed filter means a different list; start it from the first page.
  // State adjusted during render (React's documented pattern), not an effect,
  // so the first page is fetched once rather than after a page of the old
  // offset has already been requested.
  const filterKey = [debouncedUser, debouncedEmail, debouncedDepartment, debouncedJobTitle, filterRole, filterPlan, statusFilter, filterGroupId].join("\u0000");
  const [appliedFilterKey, setAppliedFilterKey] = useState(filterKey);
  if (appliedFilterKey !== filterKey) {
    setAppliedFilterKey(filterKey);
    if (offset !== 0) setOffset(0);
  }

  // Only the Online filter needs a live list: who is online changes by the
  // minute, and a snapshot from the moment the button was clicked goes stale.
  useEffect(() => {
    if (statusFilter !== "online") return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadUsers();
    }, PRESENCE_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [statusFilter]);

  async function createLocalUser(values: CreateLocalUserValues) {
    setErr("");
    const body: Record<string, unknown> = {
      username: values.username,
      email: values.email,
      password: values.password,
      role: values.role,
      display_name: values.display_name || undefined,
      company: values.company || undefined,
      department: values.department || undefined,
      office: values.office || undefined,
      job_title: values.job_title || undefined,
      reporting_to: values.reporting_to || undefined,
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
    setFlash(`User "${userLabel({ username: values.username, display_name: values.display_name })}" created.`);
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
      setFlash(`Roles updated for "${userLabel(previousUser)}" (${label}).`);
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

  async function budgetReset(userId: number) {
    await api(`/api/admin/users/${userId}/budget-reset`, { method: "POST" });
    const target = users.find((u) => u.id === userId);
    setFlash(`Budget reset for "${userLabel(target)}".`);
    load();
  }

  function openEditUser(u: U) {
    setEditUser(u);
    setEditForm({
      display_name: u.display_name || "",
      email: u.email || "",
      company: u.company || "",
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
          company: editForm.company,
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
      setFlash(
        wantsPassword
          ? `User "${userLabel(editUser)}" updated and password reset.`
          : `User "${userLabel({ ...editUser, display_name: editForm.display_name })}" updated.`,
      );
      setEditUser(null);
      setEditForm(emptyEditForm);
      await loadUsers();
    } catch (err) {
      setErr(String(err));
    } finally {
      setEditSaving(false);
    }
  }

  async function disableUser2fa() {
    if (!editUser) return;
    const ok = await confirm({
      title: "Disable two-factor authentication",
      message:
        `Disable 2FA for "${editUser.username}"? They can sign in with password only and re-enable 2FA from Settings. `
        + "Their current sessions will be signed out.",
      confirmLabel: "Disable 2FA",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    setDisable2faBusy(true);
    setErr("");
    try {
      await api(`/api/admin/users/${editUser.id}/disable-2fa`, { method: "POST" });
      setEditUser({ ...editUser, totp_enabled: false });
      setUsers((prev) =>
        prev.map((u) => (u.id === editUser.id ? { ...u, totp_enabled: false } : u)),
      );
      setFlash(`2FA disabled for "${editUser.username}".`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setDisable2faBusy(false);
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

  const prov = (p: string) =>
    `badge badge-${
      p === "local" ? "local" : p === "ldap" ? "ldap" : p === "saml" ? "saml" : p === "oidc" ? "oidc" : "keycloak"
    }`;

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
      {
        label: "Sign-in activity",
        onClick: () => navigate(signInActivityPathForUser(u.id)),
      },
      { label: "Edit user", onClick: () => openEditUser(u) },
      {
        label: "Add user to group",
        onClick: () => {
          setAddToGroupId("");
          setAddToGroupUser(u);
        },
      },
      {
        label: u.is_active === false ? "Active" : "Deactive",
        onClick: () => void setUserActive(u, u.is_active === false),
        danger: u.is_active !== false,
      },
    ];
    if (u.auth_provider === "local") {
      items.push({ label: "Delete", onClick: () => void deleteLocalUser(u), danger: true });
    }
    items.push({ label: "Budget reset", onClick: () => budgetReset(u.id) });
    return items;
  }

  const addToGroupChoices = useMemo(() => {
    if (!addToGroupUser) return groups;
    const current = new Set((addToGroupUser.group_names ?? []).map((name) => name.toLowerCase()));
    return groups.filter((g) => !current.has(g.name.toLowerCase()));
  }, [addToGroupUser, groups]);

  async function saveAddUserToGroup(e: FormEvent) {
    e.preventDefault();
    if (!addToGroupUser) return;
    if (!addToGroupId) {
      setErr("Select a group.");
      return;
    }
    setAddToGroupSaving(true);
    setErr("");
    try {
      const group = groups.find((g) => String(g.id) === addToGroupId);
      await api("/api/admin/users/bulk", {
        method: "POST",
        body: JSON.stringify({
          user_ids: [addToGroupUser.id],
          group_id: Number(addToGroupId),
          group_action: "add",
        }),
      });
      setFlash(
        group
          ? `Added ${addToGroupUser.username} to group "${group.name}".`
          : `Added ${addToGroupUser.username} to the selected group.`,
      );
      setAddToGroupUser(null);
      setAddToGroupId("");
      await loadUsers();
    } catch (e2) {
      setErr(String(e2));
    } finally {
      setAddToGroupSaving(false);
    }
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
    setFilterPlan("");
    setStatusFilter("");
    setGroupFilter("");
  }

  async function exportFilteredUsers() {
    setErr("");
    setExporting(true);
    try {
      await downloadUsersCsv(`/api/admin/users/export${buildUsersQuery()}`);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setExporting(false);
    }
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
      {err && <p className="alert alert-error" role="alert">{err}</p>}
      <ListTruncatedBanner bounds={usersBounds} noun="accounts" />
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
        <button
          type="button"
          className={`btn btn-ghost${statusFilter === "online" ? " is-active" : ""}`}
          onClick={() => setStatusFilter("online")}
          title="Signed in with an open tab right now — not the same as an enabled account"
        >
          Online Users
        </button>
      </div>
      {statusFilter === "online" && !presenceAvailable ? (
        <p className="muted-text users-presence-note">
          Online status is unavailable right now, so this list is not filtered by presence.
        </p>
      ) : null}

      <FilterPanel
        activeCount={countActiveFilters([
          filterUser,
          filterEmail,
          filterDepartment,
          filterJobTitle,
          filterRole,
          filterGroupId,
          filterPlan,
        ])}
      >
        <div className="users-filter-panel card">
          <div>
            <label htmlFor="users-user">User</label>
            <input id="users-user"
              placeholder="Username or display name"
              value={filterUser}
              onChange={(e) => setFilterUser(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="users-email">Email</label>
            <input id="users-email" placeholder="Email" value={filterEmail} onChange={(e) => setFilterEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="users-department">Department</label>
            <input id="users-department"
              placeholder="Department"
              value={filterDepartment}
              onChange={(e) => setFilterDepartment(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="users-job-title">Job title</label>
            <input id="users-job-title"
              placeholder="Job title"
              value={filterJobTitle}
              onChange={(e) => setFilterJobTitle(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="users-role">Role</label>
            <select id="users-role" value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
              <option value="">All roles</option>
              {roleCatalog.map((role) => (
                <option key={role.slug} value={role.slug}>
                  {role.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="users-group">Group</label>
            <select id="users-group" value={filterGroupId} onChange={(e) => setGroupFilter(e.target.value, groups.find((g) => String(g.id) === e.target.value)?.name || "")}>
              <option value="">All groups</option>
              {groups.map((g) => (
                <option key={g.id} value={String(g.id)}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="users-user-plan">User Plan</label>
            <select id="users-user-plan" value={filterPlan} onChange={(e) => setFilterPlan(e.target.value)}>
              <option value="">All plans</option>
              <option value="__none__">No Plan</option>
              {plans.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </FilterPanel>

      <div className="search-bar users-actions">
        <button type="button" className="btn btn-ghost" onClick={clearFilters}>
          Clear filters
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => void exportFilteredUsers()}
          disabled={exporting}
          title="Export the current filtered users as CSV"
        >
          {exporting ? "Exporting…" : "Export to CSV"}
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
        <table ref={tableCardsRef} className="card data-table data-table--cards users-table">
          <thead>
            <tr>
              <th className="users-table__select">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleSelectAllVisible}
                  aria-label="Select all users"
                />
              </th>
              <th className="col-user">User</th>
              <th className="users-table__email">Email</th>
              <th className="users-table__group">Group</th>
              <th className="users-table__department">Department</th>
              <th className="users-table__office">Office</th>
              <th className="users-table__job-title">Job title</th>
              <th className="users-table__auth">Auth</th>
              <th className="col-role">Role</th>
              <th className="users-table__plan">User Plan</th>
              <th className="col-budget">Budget</th>
              <th className="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.is_active === false ? "row-disabled" : ""}>
                <td className="users-table__select">
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
                <td className="users-table__email" title={u.email || undefined}>{u.email || "—"}</td>
                <td className="users-table__group" title={(u.group_names ?? []).join(", ") || undefined}>
                  {(u.group_names ?? []).length ? (u.group_names ?? []).join(", ") : "—"}
                </td>
                <td className="users-table__department" title={u.department || undefined}>{u.department || "—"}</td>
                <td className="users-table__office" title={u.office || undefined}>{u.office || "—"}</td>
                <td className="users-table__job-title" title={u.job_title || undefined}>{u.job_title || "—"}</td>
                <td className="users-table__auth"><span className={prov(u.auth_provider)}>{u.auth_provider}</span></td>
                <td className="col-role">
                  <RoleMultiSelect
                    value={u.roles?.length ? u.roles : [u.role]}
                    roles={roleCatalog}
                    onChange={(roles) => void changeRoles(u.id, roles)}
                  />
                </td>
                <td className="users-table__plan">
                  <UserPlanSelect user={u} plans={plans} onAssign={assignPlan} />
                </td>
                {/* The server blocks on used + reserved, so show that total —
                    reporting `used` alone made a blocked account look funded. */}
                <td
                  className="col-budget"
                  title={
                    (u.budget_reserved_usd || 0) > 0
                      ? `${formatBudgetUsd(u.budget_used_usd || 0)} settled + `
                        + `${formatBudgetUsd(u.budget_reserved_usd || 0)} held in flight`
                      : undefined
                  }
                >
                  {formatBudgetRatio(
                    (u.budget_used_usd || 0) + (u.budget_reserved_usd || 0),
                    u.monthly_budget_usd || 0,
                  )}
                </td>
                <td className="col-actions">
                  <RowActionsMenu onError={setErr} actions={userRowActions(u)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="users-pager">
        <span className="muted-text">
          {total === null
            ? ""
            : total === 0
              ? "No accounts match"
              : `${offset + 1}–${Math.min(offset + USERS_PAGE_SIZE, total)} of ${total.toLocaleString()}`}
        </span>
        <div className="users-pager__actions">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - USERS_PAGE_SIZE))}
          >
            Previous
          </button>
          <button type="button" className="btn btn-ghost" disabled={!hasMore} onClick={() => setOffset(offset + USERS_PAGE_SIZE)}>
            Next
          </button>
        </div>
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
                {editUser.auth_provider === "ldap"
                  ? "LDAP"
                  : editUser.auth_provider === "saml"
                    ? "SAML"
                    : editUser.auth_provider === "oidc"
                      ? "OIDC"
                      : "directory"}{" "}
                on
                login; you can override them here.
              </p>
            )}
            <label htmlFor="users-display-name">Display name</label>
            <input id="users-display-name"
              className="input-block"
              value={editForm.display_name}
              onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })}
            />
            <label htmlFor="users-email-2">Email</label>
            <input id="users-email-2"
              type="email"
              className="input-block"
              value={editForm.email}
              onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
            />
            <label htmlFor="users-company">Company</label>
            <input id="users-company"
              className="input-block"
              value={editForm.company}
              onChange={(e) => setEditForm({ ...editForm, company: e.target.value })}
            />
            <label htmlFor="users-department-2">Department</label>
            <input id="users-department-2"
              className="input-block"
              value={editForm.department}
              onChange={(e) => setEditForm({ ...editForm, department: e.target.value })}
            />
            <label htmlFor="users-office">Office</label>
            <input id="users-office"
              className="input-block"
              value={editForm.office}
              onChange={(e) => setEditForm({ ...editForm, office: e.target.value })}
            />
            <label htmlFor="users-job-title-2">Job title</label>
            <input id="users-job-title-2"
              className="input-block"
              value={editForm.job_title}
              onChange={(e) => setEditForm({ ...editForm, job_title: e.target.value })}
            />
            <label htmlFor="users-report-to">Report to</label>
            <input id="users-report-to"
              className="input-block"
              value={editForm.reporting_to}
              onChange={(e) => setEditForm({ ...editForm, reporting_to: e.target.value })}
            />
            {editUser.auth_provider === "local" && (
              <>
                <h4 style={{ marginTop: "1.25rem" }}>Reset password</h4>
                <p className="muted-text">Leave blank to keep the current password.</p>
                <label htmlFor="users-new-password">New password</label>
                <input id="users-new-password"
                  type="password"
                  className="input-block"
                  autoComplete="new-password"
                  value={editForm.new_password}
                  onChange={(e) => setEditForm({ ...editForm, new_password: e.target.value })}
                />
                <label htmlFor="users-confirm-password">Confirm password</label>
                <input id="users-confirm-password"
                  type="password"
                  className="input-block"
                  autoComplete="new-password"
                  value={editForm.confirm_password}
                  onChange={(e) => setEditForm({ ...editForm, confirm_password: e.target.value })}
                />
              </>
            )}
            {(() => {
              const session = getCachedSession();
              const canDisable2fa =
                editUser.auth_provider === "local"
                && !!editUser.totp_enabled
                && userHasSuperAdminAccess(session?.roles as string[] | undefined, session?.role);
              if (!canDisable2fa) return null;
              return (
                <>
                  <h4 style={{ marginTop: "1.25rem" }}>Two-factor authentication</h4>
                  <p className="muted-text">
                    2FA is enabled. Super Admin can disable it if the user lost their authenticator codes.
                  </p>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={disable2faBusy || editSaving}
                    onClick={() => void disableUser2fa()}
                  >
                    {disable2faBusy ? "Disabling…" : "Disable 2FA"}
                  </button>
                </>
              );
            })()}
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

      <Modal
        open={!!addToGroupUser}
        title={addToGroupUser ? `Add ${addToGroupUser.username} to group` : "Add user to group"}
        onClose={() => {
          if (addToGroupSaving) return;
          setAddToGroupUser(null);
          setAddToGroupId("");
        }}
      >
        <form onSubmit={(e) => void saveAddUserToGroup(e)}>
          <p className="muted-text">
            Choose a group to add this user to. Groups they already belong to are hidden.
          </p>
          <label htmlFor="users-group-2">Group</label>
          <select id="users-group-2"
            className="input-block"
            value={addToGroupId}
            onChange={(e) => setAddToGroupId(e.target.value)}
            required
            disabled={addToGroupSaving || addToGroupChoices.length === 0}
          >
            <option value="">Select a group…</option>
            {addToGroupChoices.map((g) => (
              <option key={g.id} value={String(g.id)}>
                {g.name}
              </option>
            ))}
          </select>
          {addToGroupChoices.length === 0 ? (
            <p className="muted-text">This user is already a member of every available group.</p>
          ) : null}
          <div className="dialog-actions">
            <button
              type="submit"
              className="btn"
              disabled={addToGroupSaving || !addToGroupId || addToGroupChoices.length === 0}
            >
              {addToGroupSaving ? "Adding…" : "Add to group"}
            </button>
            <button
              type="button"
              className="btn btn-ghost dialog-actions-cancel"
              disabled={addToGroupSaving}
              onClick={() => {
                setAddToGroupUser(null);
                setAddToGroupId("");
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      </Modal>

      <Modal open={bulkOpen} title={`Bulk Edit (${selectedUserIds.length} users)`} onClose={() => setBulkOpen(false)}>
        <form onSubmit={saveBulkEdit}>
          <p className="muted-text">
            Apply one or more changes to the selected users. Use status filter (Active Users / Deactive Users) first to narrow the
            list, then select rows and apply bulk actions.
          </p>
          <label htmlFor="users-group-3">Group</label>
          <select id="users-group-3"
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
          <label htmlFor="users-group-membership">Group membership</label>
          <select id="users-group-membership"
            className="input-block"
            value={bulkGroupAction}
            onChange={(e) => setBulkGroupAction(e.target.value as BulkGroupAction)}
            disabled={!bulkGroupId}
          >
            <option value="">—</option>
            <option value="add">Add to group</option>
            <option value="remove">Remove from group</option>
          </select>
          <label htmlFor="users-account-status">Account status</label>
          <select id="users-account-status"
            className="input-block"
            value={bulkStatusAction}
            onChange={(e) => setBulkStatusAction(e.target.value as BulkStatusAction)}
          >
            <option value="">No change</option>
            <option value="enable">Active</option>
            <option value="disable">Deactive</option>
          </select>
          <label htmlFor="users-user-plan-2">User Plan</label>
          <select id="users-user-plan-2"
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
          <label htmlFor="users-department-3">Department</label>
          <input id="users-department-3"
            className="input-block"
            value={bulkDepartment}
            onChange={(e) => setBulkDepartment(e.target.value)}
            placeholder="No change"
          />
          <label htmlFor="users-office-2">Office</label>
          <input id="users-office-2"
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
