import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import LocalGroupFormModal from "../../components/groups/LocalGroupFormModal";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { api } from "../../api";
import { useDebounced } from "../../hooks/useDebounced";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
function buildPlanBody(budgetPlan) {
    if (budgetPlan === "__none__")
        return { clear_plan: true };
    return { plan_id: Number(budgetPlan) };
}
export default function Groups() {
    const navigate = useNavigate();
    const { confirm } = useConfirm();
    const [groups, setGroups] = useState([]);
    const [plans, setPlans] = useState([]);
    const [search, setSearch] = useState("");
    const debounced = useDebounced(search, 280);
    const [source, setSource] = useState("");
    const [flash, setFlash] = useState("");
    const [err, setErr] = useState("");
    const [createOpen, setCreateOpen] = useState(false);
    const [editGroup, setEditGroup] = useState(null);
    const [budgetGroup, setBudgetGroup] = useState(null);
    const [budgetPlanId, setBudgetPlanId] = useState("");
    const [budgetSaving, setBudgetSaving] = useState(false);
    const [selectedIds, setSelectedIds] = useState([]);
    const [bulkOpen, setBulkOpen] = useState(false);
    const [bulkBusy, setBulkBusy] = useState(false);
    const [bulkPlanId, setBulkPlanId] = useState("");
    const load = () => {
        const q = new URLSearchParams();
        if (debounced.trim())
            q.set("q", debounced.trim());
        if (source)
            q.set("source", source);
        api(`/api/admin/groups?${q}`).then(setGroups).catch((e) => setErr(String(e)));
        api("/api/admin/plans").then((p) => setPlans(p.map((x) => ({ id: x.id, name: x.name })))).catch(() => { });
    };
    useEffect(() => {
        load();
    }, [debounced, source]);
    async function createLocalGroup(values) {
        setErr("");
        const body = {
            name: values.name,
            description: values.description || undefined,
        };
        if (values.budget_plan !== "__none__") {
            body.plan_id = Number(values.budget_plan);
        }
        await api("/api/admin/groups", {
            method: "POST",
            body: JSON.stringify(body),
        });
        setFlash("Group created.");
        load();
    }
    async function updateLocalGroup(values) {
        if (!editGroup)
            return;
        setErr("");
        await api(`/api/admin/groups/${editGroup.id}`, {
            method: "PATCH",
            body: JSON.stringify({
                name: values.name,
                description: values.description,
                ...buildPlanBody(values.budget_plan),
            }),
        });
        setFlash("Group updated.");
        load();
    }
    async function syncLdap() {
        await api("/api/admin/groups/sync/ldap", { method: "POST" });
        setFlash("LDAP groups synced.");
        load();
    }
    async function assignPlan(groupId, planId) {
        setErr("");
        try {
            const body = planId ? { plan_id: Number(planId) } : { clear_plan: true };
            const res = await api(`/api/admin/groups/${groupId}/plan`, {
                method: "PATCH",
                body: JSON.stringify(body),
            });
            const g = groups.find((x) => x.id === groupId);
            setFlash(planId
                ? `Budget plan assigned to "${g?.name ?? groupId}" and ${res.users_assigned ?? 0} member(s).`
                : `Budget plan removed from "${g?.name ?? groupId}".`);
            load();
        }
        catch (e) {
            setErr(String(e));
        }
    }
    function openAssignBudget(g) {
        setBudgetGroup(g);
        setBudgetPlanId(g.plan_id ? String(g.plan_id) : "");
    }
    async function saveAssignBudget(e) {
        e.preventDefault();
        if (!budgetGroup)
            return;
        setBudgetSaving(true);
        try {
            await assignPlan(budgetGroup.id, budgetPlanId);
            setBudgetGroup(null);
        }
        finally {
            setBudgetSaving(false);
        }
    }
    async function deleteGroup(g) {
        const ok = await confirm({
            title: "Delete group",
            message: `Delete group "${g.name}"? Members stay in Users; only membership and group plan assignment are removed.`,
            confirmLabel: "Delete",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        setErr("");
        try {
            await api(`/api/admin/groups/${g.id}`, { method: "DELETE" });
            setFlash(`Group "${g.name}" deleted.`);
            load();
        }
        catch (e) {
            setErr(String(e));
        }
    }
    async function deactiveGroupMembers(g) {
        const ok = await confirm({
            title: "Deactive all members",
            message: `Set all non-admin members of "${g.name}" to Deactive? They can still sign in and browse chat history and media, but cannot send new messages.`,
            confirmLabel: "Deactive all members",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        setErr("");
        try {
            const res = await api(`/api/admin/groups/${g.id}/disable-members`, { method: "POST" });
            setFlash(`Deactivated ${res.disabled ?? 0} user(s) in "${g.name}"` +
                (res.skipped_admins ? ` (${res.skipped_admins} admin(s) skipped).` : "."));
        }
        catch (e) {
            setErr(String(e));
        }
    }
    function showGroupMembers(g) {
        navigate(`/admin/users?group_id=${g.id}&group_name=${encodeURIComponent(g.name)}`);
    }
    function openEditGroup(g) {
        setEditGroup({
            id: g.id,
            name: g.name,
            description: g.description,
            plan_id: g.plan_id,
        });
    }
    function groupRowActions(g) {
        const actions = [
            {
                label: USAGE_AND_ACTIVITY_LABEL,
                menuWrap: true,
                onClick: () => navigate(`/admin/groups/${g.id}/activity`),
            },
            { label: "Show Members", onClick: () => showGroupMembers(g) },
        ];
        if (g.source === "local") {
            actions.push({ label: "Edit group", onClick: () => openEditGroup(g) });
        }
        else {
            actions.push({ label: "Budget plan", onClick: () => openAssignBudget(g) });
        }
        actions.push({ label: "Deactive all Members", onClick: () => void deactiveGroupMembers(g), danger: true }, { label: "Delete Group", onClick: () => void deleteGroup(g), danger: true });
        return actions;
    }
    const allVisibleSelected = useMemo(() => groups.length > 0 && groups.every((g) => selectedIds.includes(g.id)), [groups, selectedIds]);
    function toggleSelection(groupId) {
        setSelectedIds((prev) => prev.includes(groupId) ? prev.filter((id) => id !== groupId) : [...prev, groupId]);
    }
    function toggleSelectAllVisible() {
        setSelectedIds((prev) => {
            if (allVisibleSelected) {
                return prev.filter((id) => !groups.some((g) => g.id === id));
            }
            const merged = new Set(prev);
            for (const g of groups)
                merged.add(g.id);
            return Array.from(merged);
        });
    }
    async function runBulk(action) {
        if (!selectedIds.length)
            return;
        if (action === "delete") {
            const ok = await confirm({
                title: "Delete groups",
                message: `Delete ${selectedIds.length} selected group(s)? Members stay in Users; group plan assignments are removed.`,
                confirmLabel: "Delete Group",
                cancelLabel: "Cancel",
                danger: true,
            });
            if (!ok)
                return;
        }
        if (action === "disable_members") {
            const ok = await confirm({
                title: "Deactive all Members",
                message: `Set all non-admin members in ${selectedIds.length} selected group(s) to Deactive?`,
                confirmLabel: "Deactive all Members",
                cancelLabel: "Cancel",
                danger: true,
            });
            if (!ok)
                return;
        }
        if (action === "assign_plan" && !bulkPlanId) {
            setErr("Select a plan for bulk assign.");
            return;
        }
        setBulkBusy(true);
        setErr("");
        try {
            const res = await api("/api/admin/groups/bulk", {
                method: "POST",
                body: JSON.stringify({
                    group_ids: selectedIds,
                    action: action === "assign_plan" ? "assign_plan" : action === "delete" ? "delete" : "disable_members",
                    plan_id: action === "assign_plan" ? Number(bulkPlanId) : undefined,
                }),
            });
            if (action === "delete")
                setFlash(`Deleted ${res.deleted ?? 0} group(s).`);
            else if (action === "disable_members")
                setFlash(`Deactivated ${res.disabled ?? 0} member(s) across selected groups.`);
            else
                setFlash(`Assigned budget plan to ${res.groups ?? 0} group(s).`);
            setBulkOpen(false);
            setSelectedIds([]);
            load();
        }
        catch (e) {
            setErr(String(e));
        }
        finally {
            setBulkBusy(false);
        }
    }
    const badge = (s) => `badge badge-${s}`;
    const planName = (planId) => plans.find((p) => p.id === planId)?.name;
    return (_jsxs(AdminPage, { title: "Groups", children: [flash && _jsx("p", { className: "alert alert-success", children: flash }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "search-bar", children: [_jsx("input", { placeholder: "Search groups\u2026", value: search, onChange: (e) => setSearch(e.target.value) }), _jsxs("select", { value: source, onChange: (e) => setSource(e.target.value), children: [_jsx("option", { value: "", children: "All sources" }), _jsx("option", { value: "local", children: "Local" }), _jsx("option", { value: "ldap", children: "LDAP" }), _jsx("option", { value: "saml", children: "SAML" })] }), _jsx("button", { className: "btn btn-ghost", type: "button", onClick: syncLdap, children: "Sync LDAP" }), _jsxs("button", { className: "btn btn-ghost", type: "button", disabled: selectedIds.length === 0, onClick: () => {
                            setBulkPlanId("");
                            setBulkOpen(true);
                        }, children: ["Bulk Edit", selectedIds.length > 0 ? ` (${selectedIds.length})` : ""] }), _jsx("button", { className: "btn", type: "button", onClick: () => setCreateOpen(true), children: "+ Local group" })] }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "card data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { style: { width: 36 }, children: _jsx("input", { type: "checkbox", checked: allVisibleSelected, onChange: toggleSelectAllVisible, "aria-label": "Select all" }) }), _jsx("th", { children: "Name" }), _jsx("th", { children: "Source" }), _jsx("th", { children: "Budget plan" }), _jsx("th", { className: "col-actions", children: "Actions" })] }) }), _jsx("tbody", { children: groups.map((g) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("input", { type: "checkbox", checked: selectedIds.includes(g.id), onChange: () => toggleSelection(g.id), "aria-label": `Select ${g.name}` }) }), _jsxs("td", { children: [g.name, _jsx("br", {}), _jsx("small", { children: g.description })] }), _jsx("td", { children: _jsx("span", { className: badge(g.source), children: g.source }) }), _jsxs("td", { children: [_jsxs("select", { value: g.plan_id ? String(g.plan_id) : "", onChange: (e) => void assignPlan(g.id, e.target.value), title: "Synced with Plans page", children: [_jsx("option", { value: "", children: "No plan" }), plans.map((p) => (_jsx("option", { value: p.id, children: p.name }, p.id)))] }), g.plan_id ? _jsxs("small", { className: "muted-text", children: [" \u00B7 ", planName(g.plan_id)] }) : null] }), _jsx("td", { className: "col-actions", children: _jsx(RowActionsMenu, { actions: groupRowActions(g) }) })] }, g.id))) })] }) }), _jsx(LocalGroupFormModal, { open: createOpen, mode: "create", plans: plans, onClose: () => setCreateOpen(false), onSubmit: createLocalGroup }), _jsx(LocalGroupFormModal, { open: !!editGroup, mode: "edit", initial: editGroup, plans: plans, onClose: () => setEditGroup(null), onSubmit: updateLocalGroup }), _jsx(Modal, { open: !!budgetGroup, title: "Budget plan", onClose: () => setBudgetGroup(null), children: budgetGroup && (_jsxs("form", { onSubmit: saveAssignBudget, children: [_jsxs("p", { className: "muted-text", children: ["Assign a budget plan to ", _jsx("strong", { children: budgetGroup.name }), ". Updates Plans assignments for this group and all members."] }), _jsx("label", { children: "Budget plan" }), _jsxs("select", { className: "input-block", value: budgetPlanId, onChange: (e) => setBudgetPlanId(e.target.value), children: [_jsx("option", { value: "", children: "No plan" }), plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: budgetSaving, children: budgetSaving ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => setBudgetGroup(null), children: "Cancel" })] })] })) }), _jsxs(Modal, { open: bulkOpen, title: `Bulk Edit (${selectedIds.length} groups)`, onClose: () => !bulkBusy && setBulkOpen(false), children: [_jsx("p", { className: "muted-text", children: "Apply an action to all selected groups." }), _jsx("label", { children: "Budget plan (optional)" }), _jsxs("select", { className: "input-block", value: bulkPlanId, onChange: (e) => setBulkPlanId(e.target.value), children: [_jsx("option", { value: "", children: "Select plan for bulk assign\u2026" }), plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] }), _jsxs("div", { className: "dialog-actions dialog-actions-grid", style: { marginTop: 12 }, children: [_jsx("button", { type: "button", className: "btn", disabled: bulkBusy || !bulkPlanId, onClick: () => void runBulk("assign_plan"), children: "Assign budget plan" }), _jsx("button", { type: "button", className: "btn btn-danger", disabled: bulkBusy, onClick: () => void runBulk("delete"), children: "Delete Group" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => void runBulk("disable_members"), children: "Deactive all Members" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", disabled: bulkBusy, onClick: () => setBulkOpen(false), children: "Cancel" })] })] })] }));
}
