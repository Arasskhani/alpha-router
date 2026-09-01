import { jsxs as _jsxs, jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, authFetch, formatApiError, getCachedSession } from "../../api";
import { useDebounced } from "../../hooks/useDebounced";
import AdminPage from "../../components/AdminPage";
import CreateLocalUserModal from "../../components/users/CreateLocalUserModal";
import Modal from "../../components/Modal";
import RoleMultiSelect from "../../components/RoleMultiSelect";
import RowActionsMenu from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
import { PRESENCE_REFRESH_INTERVAL_MS, presenceAvailableFromUserRows, } from "../../lib/presence";
import { normalizeRole, roleLabel, userHasSuperAdminAccess } from "../../lib/rbac";
function userPlanSelectValue(u) {
    if (u.user_plan_mode === "none")
        return "__none__";
    if (u.user_plan_mode === "assigned" && u.user_plan_id)
        return String(u.user_plan_id);
    return "__inherit__";
}
function resolveUserPlanDisplay(u) {
    if (u.user_plan_mode === "assigned" && u.user_plan_name) {
        return { planName: u.user_plan_name, sourceTag: "up" };
    }
    if (u.user_plan_mode === "inherit" && u.inherited_plan_name) {
        return { planName: u.inherited_plan_name, sourceTag: "gp" };
    }
    return { planName: null, sourceTag: null };
}
function userPlanShowsSourceOverlay(u) {
    return resolveUserPlanDisplay(u).sourceTag !== null;
}
function userPlanSelectTitle(u) {
    const display = resolveUserPlanDisplay(u);
    if (display.sourceTag === "up" && display.planName) {
        return `(up) ${display.planName} — assigned directly to user`;
    }
    if (display.sourceTag === "gp" && display.planName) {
        const via = u.inherited_plan_source === "department" ? "department" : "group";
        return `(gp) ${display.planName} — inherited from ${via}`;
    }
    if (u.user_plan_mode === "none")
        return "No Plan — user blocked from inheriting group plan";
    return "No Plan";
}
function UserPlanSelect({ user, plans, onAssign, }) {
    const planDisplay = resolveUserPlanDisplay(user);
    const showOverlay = userPlanShowsSourceOverlay(user);
    return (_jsxs("div", { className: "user-plan-select-wrap", children: [showOverlay ? (_jsxs("span", { className: "user-plan-select-label", "aria-hidden": "true", children: [_jsxs("span", { className: "user-plan-source-tag", children: ["(", planDisplay.sourceTag, ")"] }), planDisplay.planName] })) : null, _jsxs("select", { className: showOverlay
                    ? "role-select user-plan-select user-plan-select--overlay"
                    : "role-select user-plan-select", value: userPlanSelectValue(user), onChange: (e) => {
                    onAssign(user.id, e.target.value);
                }, title: userPlanSelectTitle(user), children: [_jsx("option", { value: "__inherit__", children: "From group" }), _jsx("option", { value: "__none__", children: "No Plan" }), plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] })] }));
}
function formatBudgetRatio(used, total) {
    if (total <= 0)
        return "No Plan";
    const fmt = (value) => {
        const rounded = Math.round(value * 100) / 100;
        return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
    };
    return `${fmt(used)}/${fmt(total)} $`;
}
function userLabel(u) {
    if (!u)
        return "user";
    return (u.display_name || u.username || "").trim() || "user";
}
async function downloadUsersCsv(path) {
    const res = await authFetch(path);
    if (!res.ok) {
        let message = `Export failed (${res.status})`;
        try {
            const body = await res.json();
            if (body?.detail)
                message = String(body.detail);
        }
        catch {
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
const emptyEditForm = {
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
export default function Users() {
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const { confirm } = useConfirm();
    const filterGroupId = searchParams.get("group_id") || "";
    const filterGroupName = searchParams.get("group_name") || "";
    const [users, setUsers] = useState([]);
    const [plans, setPlans] = useState([]);
    const [groups, setGroups] = useState([]);
    const [filterUser, setFilterUser] = useState("");
    const [filterEmail, setFilterEmail] = useState("");
    const [filterDepartment, setFilterDepartment] = useState("");
    const [filterJobTitle, setFilterJobTitle] = useState("");
    const [filterRole, setFilterRole] = useState("");
    const [filterPlan, setFilterPlan] = useState("");
    const [statusFilter, setStatusFilter] = useState("");
    const [exporting, setExporting] = useState(false);
    const debouncedUser = useDebounced(filterUser, 280);
    const debouncedEmail = useDebounced(filterEmail, 280);
    const debouncedDepartment = useDebounced(filterDepartment, 280);
    const debouncedJobTitle = useDebounced(filterJobTitle, 280);
    const [createOpen, setCreateOpen] = useState(false);
    const [flash, setFlash] = useState("");
    const [err, setErr] = useState("");
    const [editUser, setEditUser] = useState(null);
    const [editForm, setEditForm] = useState(emptyEditForm);
    const [editSaving, setEditSaving] = useState(false);
    const [disable2faBusy, setDisable2faBusy] = useState(false);
    const [selectedUserIds, setSelectedUserIds] = useState([]);
    const [bulkOpen, setBulkOpen] = useState(false);
    const [bulkSaving, setBulkSaving] = useState(false);
    const [bulkDepartment, setBulkDepartment] = useState("");
    const [bulkOffice, setBulkOffice] = useState("");
    const [bulkPlanChoice, setBulkPlanChoice] = useState("");
    const [bulkGroupId, setBulkGroupId] = useState("");
    const [bulkGroupAction, setBulkGroupAction] = useState("");
    const [bulkStatusAction, setBulkStatusAction] = useState("");
    const [addToGroupUser, setAddToGroupUser] = useState(null);
    const [addToGroupId, setAddToGroupId] = useState("");
    const [addToGroupSaving, setAddToGroupSaving] = useState(false);
    const [roleCatalog, setRoleCatalog] = useState([]);
    const [presenceAvailable, setPresenceAvailable] = useState(true);
    const usersLoadSeq = useRef(0);
    function buildUsersQuery() {
        const params = new URLSearchParams();
        if (debouncedUser.trim())
            params.set("username", debouncedUser.trim());
        if (debouncedEmail.trim())
            params.set("email", debouncedEmail.trim());
        if (debouncedDepartment.trim())
            params.set("department", debouncedDepartment.trim());
        if (debouncedJobTitle.trim())
            params.set("job_title", debouncedJobTitle.trim());
        if (filterRole)
            params.set("role", filterRole);
        if (filterPlan === "__none__")
            params.set("no_plan", "true");
        else if (filterPlan)
            params.set("plan_id", filterPlan);
        if (statusFilter === "enabled")
            params.set("is_active", "true");
        if (statusFilter === "disabled")
            params.set("is_active", "false");
        if (statusFilter === "online") {
            params.set("online", "true");
            params.set("is_active", "true");
        }
        if (filterGroupId)
            params.set("group_id", filterGroupId);
        const qs = params.toString();
        return qs ? `?${qs}` : "";
    }
    async function loadUsers() {
        const seq = ++usersLoadSeq.current;
        try {
            const rows = await api(`/api/admin/users${buildUsersQuery()}`);
            if (seq !== usersLoadSeq.current)
                return;
            const nextUsers = rows.map((u) => {
                const roles = (u.roles?.length ? u.roles : [u.role]).map(normalizeRole);
                return { ...u, roles, role: normalizeRole(u.role) };
            });
            setUsers(nextUsers);
            setPresenceAvailable(presenceAvailableFromUserRows(nextUsers));
            setSelectedUserIds((prev) => prev.filter((id) => nextUsers.some((u) => u.id === id)));
        }
        catch (e) {
            if (seq !== usersLoadSeq.current)
                return;
            setErr(String(e));
        }
    }
    function load() {
        void loadUsers();
        api("/api/admin/plans").then(setPlans).catch(() => { });
        api("/api/admin/groups").then(setGroups).catch(() => { });
    }
    useEffect(() => {
        void loadUsers();
        api("/api/admin/plans").then(setPlans).catch(() => { });
        api("/api/admin/groups").then(setGroups).catch(() => { });
        api("/api/admin/roles").then(setRoleCatalog).catch(() => { });
    }, [debouncedUser, debouncedEmail, debouncedDepartment, debouncedJobTitle, filterRole, filterPlan, statusFilter, filterGroupId]);
    // Only the Online filter needs a live list: who is online changes by the
    // minute, and a snapshot from the moment the button was clicked goes stale.
    useEffect(() => {
        if (statusFilter !== "online")
            return;
        const timer = window.setInterval(() => {
            if (document.visibilityState === "visible")
                void loadUsers();
        }, PRESENCE_REFRESH_INTERVAL_MS);
        return () => window.clearInterval(timer);
    }, [statusFilter]);
    async function createLocalUser(values) {
        setErr("");
        const body = {
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
        }
        else if (values.budget_plan === "__none__") {
            body.no_plan = true;
        }
        else {
            body.plan_id = Number(values.budget_plan);
        }
        await api("/api/admin/users", {
            method: "POST",
            body: JSON.stringify(body),
        });
        setFlash(`User "${userLabel({ username: values.username, display_name: values.display_name })}" created.`);
        load();
    }
    async function changeRoles(userId, roles) {
        const next = roles.map(normalizeRole);
        const previousUser = users.find((u) => u.id === userId);
        const previous = (previousUser?.roles?.length ? previousUser.roles : [previousUser?.role || "user"]).map(normalizeRole);
        setUsers((list) => list.map((u) => u.id === userId ? { ...u, roles: next, role: next[0] || "user" } : u));
        setErr("");
        try {
            const updated = await api(`/api/admin/users/${userId}`, {
                method: "PATCH",
                body: JSON.stringify({ roles: next }),
            });
            const saved = (updated.roles?.length ? updated.roles : [updated.role]).map(normalizeRole);
            setUsers((list) => list.map((u) => u.id === userId ? { ...u, roles: saved, role: normalizeRole(updated.role) } : u));
            const label = saved.length === 1
                ? roleLabel(roleCatalog, saved[0])
                : `${saved.length} roles`;
            setFlash(`Roles updated for "${userLabel(previousUser)}" (${label}).`);
            await loadUsers();
        }
        catch (e) {
            setUsers((list) => list.map((u) => u.id === userId ? { ...u, roles: previous, role: previous[0] || "user" } : u));
            setErr(String(e));
        }
    }
    async function assignPlan(userId, planId) {
        setErr("");
        const optimisticMode = planId === "__none__" ? "none" : planId === "__inherit__" ? "inherit" : "assigned";
        const optimisticPlanId = planId === "__none__" || planId === "__inherit__" ? null : Number(planId);
        const selected = planId !== "__none__" && planId !== "__inherit__" ? plans.find((p) => p.id === Number(planId)) : null;
        setUsers((list) => list.map((u) => u.id === userId
            ? {
                ...u,
                user_plan_mode: optimisticMode,
                user_plan_id: optimisticPlanId,
                user_plan_name: selected?.name || null,
                inherited_plan_id: planId === "__inherit__" ? u.inherited_plan_id ?? null : null,
                inherited_plan_name: planId === "__inherit__" ? u.inherited_plan_name ?? null : null,
                inherited_plan_source: planId === "__inherit__" ? u.inherited_plan_source ?? null : null,
            }
            : u));
        try {
            const body = planId === "__inherit__"
                ? { inherit_group_plan: true }
                : planId === "__none__"
                    ? { no_plan: true }
                    : { plan_id: Number(planId) };
            await api(`/api/admin/users/${userId}/plan`, { method: "PATCH", body: JSON.stringify(body) });
            await loadUsers();
        }
        catch (e) {
            setErr(String(e));
            await loadUsers();
        }
    }
    async function clearUserPlan(userId) {
        await api(`/api/admin/users/${userId}/plan`, { method: "PATCH", body: JSON.stringify({ no_plan: true }) });
        load();
    }
    async function budgetReset(userId) {
        await api(`/api/admin/users/${userId}/budget-reset`, { method: "POST" });
        const target = users.find((u) => u.id === userId);
        setFlash(`Budget reset for "${userLabel(target)}".`);
        load();
    }
    function openEditUser(u) {
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
    async function saveEditUser(e) {
        e.preventDefault();
        if (!editUser)
            return;
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
            const updated = await api(`/api/admin/users/${editUser.id}`, {
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
            setUsers((list) => list.map((u) => u.id === editUser.id
                ? {
                    ...u,
                    ...updated,
                    role: normalizeRole(updated.role),
                }
                : u));
            setFlash(wantsPassword
                ? `User "${userLabel(editUser)}" updated and password reset.`
                : `User "${userLabel({ ...editUser, display_name: editForm.display_name })}" updated.`);
            setEditUser(null);
            setEditForm(emptyEditForm);
            await loadUsers();
        }
        catch (err) {
            setErr(String(err));
        }
        finally {
            setEditSaving(false);
        }
    }
    async function disableUser2fa() {
        if (!editUser)
            return;
        const ok = await confirm({
            title: "Disable two-factor authentication",
            message: `Disable 2FA for "${editUser.username}"? They can sign in with password only and re-enable 2FA from Settings. `
                + "Their current sessions will be signed out.",
            confirmLabel: "Disable 2FA",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        setDisable2faBusy(true);
        setErr("");
        try {
            await api(`/api/admin/users/${editUser.id}/disable-2fa`, { method: "POST" });
            setEditUser({ ...editUser, totp_enabled: false });
            setUsers((prev) => prev.map((u) => (u.id === editUser.id ? { ...u, totp_enabled: false } : u)));
            setFlash(`2FA disabled for "${editUser.username}".`);
        }
        catch (e) {
            setErr(String(e));
        }
        finally {
            setDisable2faBusy(false);
        }
    }
    async function setUserActive(u, active) {
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
        if (!ok)
            return;
        setErr("");
        try {
            await api(`/api/admin/users/${u.id}`, {
                method: "PATCH",
                body: JSON.stringify({ is_active: active }),
            });
            setFlash(`User "${u.username}" ${active ? "activated" : "deactivated"}.`);
            await loadUsers();
        }
        catch (e) {
            setErr(String(e));
        }
    }
    async function deleteLocalUser(u) {
        const ok = await confirm({
            title: "Move to Deleted Users",
            message: `Move "${u.username}" to Deleted Users? They will not be able to sign in. Account data stays on the server until permanently deleted from Deleted Users.`,
            confirmLabel: "Move to Deleted Users",
            cancelLabel: "No",
            danger: true,
        });
        if (!ok)
            return;
        setErr("");
        try {
            await api(`/api/admin/users/${u.id}`, { method: "DELETE" });
            if (editUser?.id === u.id) {
                setEditUser(null);
                setEditForm(emptyEditForm);
            }
            setFlash(`User "${u.username}" moved to Deleted Users.`);
            await loadUsers();
        }
        catch (e) {
            setErr(String(e));
        }
    }
    const prov = (p) => `badge badge-${p === "local" ? "local" : p === "ldap" ? "ldap" : p === "saml" ? "saml" : p === "oidc" ? "oidc" : "keycloak"}`;
    function userRowActions(u) {
        const items = [
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
        if (!addToGroupUser)
            return groups;
        const current = new Set((addToGroupUser.group_names ?? []).map((name) => name.toLowerCase()));
        return groups.filter((g) => !current.has(g.name.toLowerCase()));
    }, [addToGroupUser, groups]);
    async function saveAddUserToGroup(e) {
        e.preventDefault();
        if (!addToGroupUser)
            return;
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
            setFlash(group
                ? `Added ${addToGroupUser.username} to group "${group.name}".`
                : `Added ${addToGroupUser.username} to the selected group.`);
            setAddToGroupUser(null);
            setAddToGroupId("");
            await loadUsers();
        }
        catch (e2) {
            setErr(String(e2));
        }
        finally {
            setAddToGroupSaving(false);
        }
    }
    const allVisibleSelected = useMemo(() => users.length > 0 && users.every((u) => selectedUserIds.includes(u.id)), [users, selectedUserIds]);
    function toggleUserSelection(userId) {
        setSelectedUserIds((prev) => prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]);
    }
    function toggleSelectAllVisible() {
        setSelectedUserIds((prev) => {
            if (allVisibleSelected) {
                return prev.filter((id) => !users.some((u) => u.id === id));
            }
            const merged = new Set(prev);
            for (const u of users)
                merged.add(u.id);
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
    function setGroupFilter(groupId, groupName = "") {
        const next = new URLSearchParams(searchParams);
        if (groupId) {
            next.set("group_id", groupId);
            if (groupName)
                next.set("group_name", groupName);
            else
                next.delete("group_name");
        }
        else {
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
        }
        catch (e) {
            setErr(formatApiError(e));
        }
        finally {
            setExporting(false);
        }
    }
    async function saveBulkEdit(e) {
        e.preventDefault();
        if (!selectedUserIds.length)
            return;
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
            const body = { user_ids: selectedUserIds };
            if (hasStatus)
                body.is_active = bulkStatusAction === "enable";
            if (hasGroup) {
                body.group_id = Number(bulkGroupId);
                body.group_action = bulkGroupAction;
            }
            if (hasDept)
                body.department = bulkDepartment.trim();
            if (hasOffice)
                body.office = bulkOffice.trim();
            if (bulkPlanChoice === "__none__")
                body.no_plan = true;
            else if (bulkPlanChoice === "__inherit__")
                body.inherit_group_plan = true;
            else if (bulkPlanChoice)
                body.plan_id = Number(bulkPlanChoice);
            await api("/api/admin/users/bulk", { method: "POST", body: JSON.stringify(body) });
            setFlash(`Bulk edit applied to ${selectedUserIds.length} user(s).`);
            setBulkOpen(false);
            await loadUsers();
        }
        catch (e2) {
            setErr(String(e2));
        }
        finally {
            setBulkSaving(false);
        }
    }
    return (_jsxs(AdminPage, { title: "Users", children: [flash && _jsx("p", { className: "alert alert-success", children: flash }), err && _jsx("p", { className: "alert alert-error", children: err }), filterGroupId ? (_jsxs("p", { className: "alert card", style: { display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }, children: [_jsxs("span", { children: ["Showing members of", " ", _jsx("strong", { children: filterGroupName || groups.find((g) => String(g.id) === filterGroupId)?.name || `group #${filterGroupId}` })] }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => setGroupFilter(""), children: "Clear group filter" }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => navigate("/admin/groups"), children: "Back to Groups" })] })) : null, _jsxs("div", { className: "users-status-filters", children: [_jsx("span", { className: "muted-text", style: { marginRight: "0.25rem" }, children: "Status:" }), _jsx("button", { type: "button", className: `btn btn-ghost${statusFilter === "" ? " is-active" : ""}`, onClick: () => setStatusFilter(""), children: "All" }), _jsx("button", { type: "button", className: `btn btn-ghost${statusFilter === "enabled" ? " is-active" : ""}`, onClick: () => setStatusFilter("enabled"), children: "Active Users" }), _jsx("button", { type: "button", className: `btn btn-ghost${statusFilter === "disabled" ? " is-active" : ""}`, onClick: () => setStatusFilter("disabled"), children: "Deactive Users" }), _jsx("button", { type: "button", className: `btn btn-ghost${statusFilter === "online" ? " is-active" : ""}`, onClick: () => setStatusFilter("online"), title: "Signed in with an open tab right now \u2014 not the same as an enabled account", children: "Online Users" })] }), statusFilter === "online" && !presenceAvailable ? (_jsx("p", { className: "muted-text users-presence-note", children: "Online status is unavailable right now, so this list is not filtered by presence." })) : null, _jsxs("div", { className: "users-filter-panel card", children: [_jsxs("div", { children: [_jsx("label", { children: "User" }), _jsx("input", { placeholder: "Username or display name", value: filterUser, onChange: (e) => setFilterUser(e.target.value) })] }), _jsxs("div", { children: [_jsx("label", { children: "Email" }), _jsx("input", { placeholder: "Email", value: filterEmail, onChange: (e) => setFilterEmail(e.target.value) })] }), _jsxs("div", { children: [_jsx("label", { children: "Department" }), _jsx("input", { placeholder: "Department", value: filterDepartment, onChange: (e) => setFilterDepartment(e.target.value) })] }), _jsxs("div", { children: [_jsx("label", { children: "Job title" }), _jsx("input", { placeholder: "Job title", value: filterJobTitle, onChange: (e) => setFilterJobTitle(e.target.value) })] }), _jsxs("div", { children: [_jsx("label", { children: "Role" }), _jsxs("select", { value: filterRole, onChange: (e) => setFilterRole(e.target.value), children: [_jsx("option", { value: "", children: "All roles" }), roleCatalog.map((role) => (_jsx("option", { value: role.slug, children: role.name }, role.slug)))] })] }), _jsxs("div", { children: [_jsx("label", { children: "Group" }), _jsxs("select", { value: filterGroupId, onChange: (e) => setGroupFilter(e.target.value, groups.find((g) => String(g.id) === e.target.value)?.name || ""), children: [_jsx("option", { value: "", children: "All groups" }), groups.map((g) => (_jsx("option", { value: String(g.id), children: g.name }, g.id)))] })] }), _jsxs("div", { children: [_jsx("label", { children: "User Plan" }), _jsxs("select", { value: filterPlan, onChange: (e) => setFilterPlan(e.target.value), children: [_jsx("option", { value: "", children: "All plans" }), _jsx("option", { value: "__none__", children: "No Plan" }), plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] })] })] }), _jsxs("div", { className: "search-bar users-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: clearFilters, children: "Clear filters" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void exportFilteredUsers(), disabled: exporting, title: "Export the current filtered users as CSV", children: exporting ? "Exporting…" : "Export to CSV" }), _jsxs("button", { className: "btn btn-ghost", type: "button", onClick: openBulkEdit, disabled: selectedUserIds.length === 0, title: selectedUserIds.length ? `Edit ${selectedUserIds.length} selected users` : "Select users first", children: ["Bulk Edit (", selectedUserIds.length, ")"] }), _jsx("button", { className: "btn", type: "button", onClick: () => setCreateOpen(true), children: "+ Local user" })] }), _jsx("div", { className: "table-wrap table-wrap--users", children: _jsxs("table", { className: "card data-table users-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { className: "users-table__select", children: _jsx("input", { type: "checkbox", checked: allVisibleSelected, onChange: toggleSelectAllVisible, "aria-label": "Select all users" }) }), _jsx("th", { className: "col-user", children: "User" }), _jsx("th", { className: "users-table__email", children: "Email" }), _jsx("th", { className: "users-table__group", children: "Group" }), _jsx("th", { className: "users-table__department", children: "Department" }), _jsx("th", { className: "users-table__office", children: "Office" }), _jsx("th", { className: "users-table__job-title", children: "Job title" }), _jsx("th", { className: "users-table__auth", children: "Auth" }), _jsx("th", { className: "col-role", children: "Role" }), _jsx("th", { className: "users-table__plan", children: "User Plan" }), _jsx("th", { className: "col-budget", children: "Budget" }), _jsx("th", { className: "col-actions", children: "Actions" })] }) }), _jsx("tbody", { children: users.map((u) => (_jsxs("tr", { className: u.is_active === false ? "row-disabled" : "", children: [_jsx("td", { className: "users-table__select", children: _jsx("input", { type: "checkbox", checked: selectedUserIds.includes(u.id), onChange: () => toggleUserSelection(u.id), "aria-label": `Select ${u.username}` }) }), _jsx("td", { className: "col-user", children: _jsx("div", { className: "user-name-cell", children: _jsxs("span", { className: "user-name-cell__line", children: [_jsx("span", { className: "user-name-cell__username", children: u.username }), u.is_active === false && (_jsx("span", { className: "user-deactivated-label", children: "(Deactivated)" }))] }) }) }), _jsx("td", { className: "users-table__email", title: u.email || undefined, children: u.email || "—" }), _jsx("td", { className: "users-table__group", title: (u.group_names ?? []).join(", ") || undefined, children: (u.group_names ?? []).length ? (u.group_names ?? []).join(", ") : "—" }), _jsx("td", { className: "users-table__department", title: u.department || undefined, children: u.department || "—" }), _jsx("td", { className: "users-table__office", title: u.office || undefined, children: u.office || "—" }), _jsx("td", { className: "users-table__job-title", title: u.job_title || undefined, children: u.job_title || "—" }), _jsx("td", { className: "users-table__auth", children: _jsx("span", { className: prov(u.auth_provider), children: u.auth_provider }) }), _jsx("td", { className: "col-role", children: _jsx(RoleMultiSelect, { value: u.roles?.length ? u.roles : [u.role], roles: roleCatalog, onChange: (roles) => void changeRoles(u.id, roles) }) }), _jsx("td", { className: "users-table__plan", children: _jsx(UserPlanSelect, { user: u, plans: plans, onAssign: assignPlan }) }), _jsx("td", { className: "col-budget", children: formatBudgetRatio(u.budget_used_usd || 0, u.monthly_budget_usd || 0) }), _jsx("td", { className: "col-actions", children: _jsx(RowActionsMenu, { actions: userRowActions(u) }) })] }, u.id))) })] }) }), _jsx(Modal, { open: !!editUser, title: "Edit User", onClose: () => setEditUser(null), children: editUser && (_jsxs("form", { onSubmit: saveEditUser, children: [_jsxs("p", { className: "muted-text", children: [_jsx("strong", { children: editUser.username }), " · ", _jsx("span", { className: prov(editUser.auth_provider), children: editUser.auth_provider })] }), editUser.auth_provider !== "local" && (_jsxs("p", { className: "muted-text", style: { marginBottom: "0.75rem" }, children: ["Profile fields sync from", " ", editUser.auth_provider === "ldap"
                                    ? "LDAP"
                                    : editUser.auth_provider === "saml"
                                        ? "SAML"
                                        : editUser.auth_provider === "oidc"
                                            ? "OIDC"
                                            : "directory", " ", "on login; you can override them here."] })), _jsx("label", { children: "Display name" }), _jsx("input", { className: "input-block", value: editForm.display_name, onChange: (e) => setEditForm({ ...editForm, display_name: e.target.value }) }), _jsx("label", { children: "Email" }), _jsx("input", { type: "email", className: "input-block", value: editForm.email, onChange: (e) => setEditForm({ ...editForm, email: e.target.value }) }), _jsx("label", { children: "Company" }), _jsx("input", { className: "input-block", value: editForm.company, onChange: (e) => setEditForm({ ...editForm, company: e.target.value }) }), _jsx("label", { children: "Department" }), _jsx("input", { className: "input-block", value: editForm.department, onChange: (e) => setEditForm({ ...editForm, department: e.target.value }) }), _jsx("label", { children: "Office" }), _jsx("input", { className: "input-block", value: editForm.office, onChange: (e) => setEditForm({ ...editForm, office: e.target.value }) }), _jsx("label", { children: "Job title" }), _jsx("input", { className: "input-block", value: editForm.job_title, onChange: (e) => setEditForm({ ...editForm, job_title: e.target.value }) }), _jsx("label", { children: "Report to" }), _jsx("input", { className: "input-block", value: editForm.reporting_to, onChange: (e) => setEditForm({ ...editForm, reporting_to: e.target.value }) }), editUser.auth_provider === "local" && (_jsxs(_Fragment, { children: [_jsx("h4", { style: { marginTop: "1.25rem" }, children: "Reset password" }), _jsx("p", { className: "muted-text", children: "Leave blank to keep the current password." }), _jsx("label", { children: "New password" }), _jsx("input", { type: "password", className: "input-block", autoComplete: "new-password", value: editForm.new_password, onChange: (e) => setEditForm({ ...editForm, new_password: e.target.value }) }), _jsx("label", { children: "Confirm password" }), _jsx("input", { type: "password", className: "input-block", autoComplete: "new-password", value: editForm.confirm_password, onChange: (e) => setEditForm({ ...editForm, confirm_password: e.target.value }) })] })), (() => {
                            const session = getCachedSession();
                            const canDisable2fa = editUser.auth_provider === "local"
                                && !!editUser.totp_enabled
                                && userHasSuperAdminAccess(session?.roles, session?.role);
                            if (!canDisable2fa)
                                return null;
                            return (_jsxs(_Fragment, { children: [_jsx("h4", { style: { marginTop: "1.25rem" }, children: "Two-factor authentication" }), _jsx("p", { className: "muted-text", children: "2FA is enabled. Super Admin can disable it if the user lost their authenticator codes." }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: disable2faBusy || editSaving, onClick: () => void disableUser2fa(), children: disable2faBusy ? "Disabling…" : "Disable 2FA" })] }));
                        })(), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: editSaving, children: editSaving ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => setEditUser(null), children: "Cancel" })] })] })) }), _jsx(Modal, { open: !!addToGroupUser, title: addToGroupUser ? `Add ${addToGroupUser.username} to group` : "Add user to group", onClose: () => {
                    if (addToGroupSaving)
                        return;
                    setAddToGroupUser(null);
                    setAddToGroupId("");
                }, children: _jsxs("form", { onSubmit: (e) => void saveAddUserToGroup(e), children: [_jsx("p", { className: "muted-text", children: "Choose a group to add this user to. Groups they already belong to are hidden." }), _jsx("label", { children: "Group" }), _jsxs("select", { className: "input-block", value: addToGroupId, onChange: (e) => setAddToGroupId(e.target.value), required: true, disabled: addToGroupSaving || addToGroupChoices.length === 0, children: [_jsx("option", { value: "", children: "Select a group\u2026" }), addToGroupChoices.map((g) => (_jsx("option", { value: String(g.id), children: g.name }, g.id)))] }), addToGroupChoices.length === 0 ? (_jsx("p", { className: "muted-text", children: "This user is already a member of every available group." })) : null, _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: addToGroupSaving || !addToGroupId || addToGroupChoices.length === 0, children: addToGroupSaving ? "Adding…" : "Add to group" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", disabled: addToGroupSaving, onClick: () => {
                                        setAddToGroupUser(null);
                                        setAddToGroupId("");
                                    }, children: "Cancel" })] })] }) }), _jsx(Modal, { open: bulkOpen, title: `Bulk Edit (${selectedUserIds.length} users)`, onClose: () => setBulkOpen(false), children: _jsxs("form", { onSubmit: saveBulkEdit, children: [_jsx("p", { className: "muted-text", children: "Apply one or more changes to the selected users. Use status filter (Active Users / Deactive Users) first to narrow the list, then select rows and apply bulk actions." }), _jsx("label", { children: "Group" }), _jsxs("select", { className: "input-block", value: bulkGroupId, onChange: (e) => setBulkGroupId(e.target.value), children: [_jsx("option", { value: "", children: "No group change" }), groups.map((g) => (_jsx("option", { value: String(g.id), children: g.name }, g.id)))] }), _jsx("label", { children: "Group membership" }), _jsxs("select", { className: "input-block", value: bulkGroupAction, onChange: (e) => setBulkGroupAction(e.target.value), disabled: !bulkGroupId, children: [_jsx("option", { value: "", children: "\u2014" }), _jsx("option", { value: "add", children: "Add to group" }), _jsx("option", { value: "remove", children: "Remove from group" })] }), _jsx("label", { children: "Account status" }), _jsxs("select", { className: "input-block", value: bulkStatusAction, onChange: (e) => setBulkStatusAction(e.target.value), children: [_jsx("option", { value: "", children: "No change" }), _jsx("option", { value: "enable", children: "Active" }), _jsx("option", { value: "disable", children: "Deactive" })] }), _jsx("label", { children: "User Plan" }), _jsxs("select", { className: "input-block", value: bulkPlanChoice, onChange: (e) => setBulkPlanChoice(e.target.value), children: [_jsx("option", { value: "", children: "No change" }), _jsx("option", { value: "__inherit__", children: "From group" }), _jsx("option", { value: "__none__", children: "No Plan" }), plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] }), _jsx("label", { children: "Department" }), _jsx("input", { className: "input-block", value: bulkDepartment, onChange: (e) => setBulkDepartment(e.target.value), placeholder: "No change" }), _jsx("label", { children: "Office" }), _jsx("input", { className: "input-block", value: bulkOffice, onChange: (e) => setBulkOffice(e.target.value), placeholder: "No change" }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: bulkSaving || selectedUserIds.length === 0, children: bulkSaving ? "Applying…" : "Apply" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => setBulkOpen(false), children: "Cancel" })] })] }) }), _jsx(CreateLocalUserModal, { open: createOpen, roles: roleCatalog, plans: plans, onClose: () => setCreateOpen(false), onSubmit: createLocalUser })] }));
}
