import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import AssignPlanModal from "../../components/plans/AssignPlanModal";
import PlanFormModal from "../../components/plans/PlanFormModal";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
export default function Plans() {
    const { confirm } = useConfirm();
    const [plans, setPlans] = useState([]);
    const [groups, setGroups] = useState([]);
    const [err, setErr] = useState("");
    const [msg, setMsg] = useState("");
    const [createOpen, setCreateOpen] = useState(false);
    const [editPlan, setEditPlan] = useState(null);
    const [assignOpen, setAssignOpen] = useState(false);
    const [assignPlanId, setAssignPlanId] = useState(null);
    const [planSearch, setPlanSearch] = useState("");
    const [sortBy, setSortBy] = useState("name");
    const [sortDir, setSortDir] = useState("asc");
    const [page, setPage] = useState(1);
    const [membersPlan, setMembersPlan] = useState(null);
    const [membersData, setMembersData] = useState(null);
    const [membersLoading, setMembersLoading] = useState(false);
    const pageSize = 8;
    const load = async () => {
        try {
            const [p, g] = await Promise.all([
                api("/api/admin/plans"),
                api("/api/admin/groups"),
            ]);
            setPlans(p);
            setGroups(g);
        }
        catch (e) {
            setErr(String(e));
        }
    };
    useEffect(() => {
        void load();
    }, []);
    async function createPlan(values) {
        setErr("");
        await api("/api/admin/plans", {
            method: "POST",
            body: JSON.stringify(values),
        });
        setMsg(`Plan "${values.name}" created.`);
        await load();
    }
    async function updatePlan(values) {
        if (!editPlan)
            return;
        setErr("");
        await api(`/api/admin/plans/${editPlan.id}`, {
            method: "PATCH",
            body: JSON.stringify(values),
        });
        setMsg(`Plan "${values.name}" updated.`);
        await load();
    }
    async function assignPlan(values) {
        setErr("");
        if (values.target === "group" && values.group_id) {
            const g = groups.find((x) => x.id === values.group_id);
            const res = await api("/api/admin/plans/assign", {
                method: "POST",
                body: JSON.stringify({ plan_id: values.plan_id, group_id: values.group_id }),
            });
            setMsg(`Plan assigned to group "${g?.name ?? values.group_id}" and ${res.users_assigned ?? 0} member user(s).`);
        }
        else if (values.target === "user" && values.user_id) {
            await api("/api/admin/plans/assign", {
                method: "POST",
                body: JSON.stringify({ plan_id: values.plan_id, user_id: values.user_id }),
            });
            setMsg("Plan assigned to user.");
        }
        else if (values.target === "department") {
            await api("/api/admin/plans/assign-department", {
                method: "POST",
                body: JSON.stringify({ plan_id: values.plan_id, department: values.department }),
            });
            setMsg(`Plan assigned to department "${values.department}".`);
        }
        await load();
    }
    function openAssign(planId) {
        setAssignPlanId(planId ?? null);
        setAssignOpen(true);
    }
    function openEdit(plan) {
        setEditPlan({
            id: plan.id,
            name: plan.name,
            monthly_budget_usd: plan.monthly_budget_usd,
        });
    }
    async function deletePlan(plan) {
        const ok = await confirm({
            title: "Delete plan",
            message: `Delete plan "${plan.name}"? Its assignments will be removed.`,
            confirmLabel: "Delete",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        setErr("");
        try {
            await api(`/api/admin/plans/${plan.id}`, { method: "DELETE" });
            setMsg(`Plan "${plan.name}" deleted.`);
            await load();
        }
        catch (e2) {
            setErr(String(e2));
        }
    }
    async function showMembers(plan) {
        setMembersPlan(plan);
        setMembersData(null);
        setMembersLoading(true);
        try {
            const data = await api(`/api/admin/plans/${plan.id}/members`);
            setMembersData(data);
        }
        catch (e) {
            setErr(String(e));
            setMembersPlan(null);
        }
        finally {
            setMembersLoading(false);
        }
    }
    const visiblePlans = plans
        .filter((p) => {
        const q = planSearch.trim().toLowerCase();
        if (!q)
            return true;
        return p.name.toLowerCase().includes(q);
    })
        .sort((a, b) => {
        const dir = sortDir === "asc" ? 1 : -1;
        if (sortBy === "name")
            return a.name.localeCompare(b.name) * dir;
        return (a.monthly_budget_usd - b.monthly_budget_usd) * dir;
    });
    const totalPages = Math.max(1, Math.ceil(visiblePlans.length / pageSize));
    const safePage = Math.min(page, totalPages);
    const pagedPlans = visiblePlans.slice((safePage - 1) * pageSize, safePage * pageSize);
    function setSort(next) {
        if (sortBy === next)
            setSortDir((d) => (d === "asc" ? "desc" : "asc"));
        else {
            setSortBy(next);
            setSortDir("asc");
        }
    }
    return (_jsxs(AdminPage, { title: "Plans", children: [msg && _jsx("p", { className: "alert alert-success", children: msg }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "search-bar", children: [_jsx("input", { placeholder: "Search plan name\u2026", value: planSearch, onChange: (e) => {
                            setPlanSearch(e.target.value);
                            setPage(1);
                        } }), _jsxs("select", { value: sortBy, onChange: (e) => setSort(e.target.value), children: [_jsx("option", { value: "name", children: "Sort: Name" }), _jsx("option", { value: "budget", children: "Sort: Budget" })] }), _jsx("button", { className: "btn btn-ghost", type: "button", onClick: () => setSort(sortBy), children: sortDir === "asc" ? "Asc" : "Desc" }), _jsx("button", { className: "btn btn-ghost", type: "button", onClick: () => openAssign(), disabled: plans.length === 0, children: "Assign plan" }), _jsx("button", { className: "btn", type: "button", onClick: () => setCreateOpen(true), children: "+ New plan" })] }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "card data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Name" }), _jsx("th", { children: "Monthly budget" }), _jsx("th", { className: "col-actions", children: "Actions" })] }) }), _jsx("tbody", { children: pagedPlans.map((p) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("strong", { children: p.name }) }), _jsxs("td", { children: ["$", p.monthly_budget_usd] }), _jsx("td", { className: "col-actions", children: _jsx(RowActionsMenu, { label: "Actions", actions: [
                                                { label: "Show Members", onClick: () => void showMembers(p) },
                                                { label: "Assign plan", onClick: () => openAssign(p.id) },
                                                { label: "Edit", onClick: () => openEdit(p) },
                                                { label: "Delete", onClick: () => void deletePlan(p), danger: true },
                                            ] }) })] }, p.id))) })] }) }), _jsxs("div", { className: "card", style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }, children: [_jsxs("span", { className: "muted-text", children: [visiblePlans.length, " plan(s) \u00B7 page ", safePage, " / ", totalPages] }), _jsxs("div", { style: { display: "flex", gap: 8 }, children: [_jsx("button", { className: "btn btn-ghost", type: "button", disabled: safePage <= 1, onClick: () => setPage((p) => Math.max(1, p - 1)), children: "Prev" }), _jsx("button", { className: "btn btn-ghost", type: "button", disabled: safePage >= totalPages, onClick: () => setPage((p) => Math.min(totalPages, p + 1)), children: "Next" })] })] }), _jsx(PlanFormModal, { open: createOpen, mode: "create", onClose: () => setCreateOpen(false), onSubmit: createPlan }), _jsx(PlanFormModal, { open: !!editPlan, mode: "edit", initial: editPlan, onClose: () => setEditPlan(null), onSubmit: updatePlan }), _jsx(AssignPlanModal, { open: assignOpen, plans: plans, groups: groups, initialPlanId: assignPlanId, onClose: () => {
                    setAssignOpen(false);
                    setAssignPlanId(null);
                }, onSubmit: assignPlan }), _jsxs(Modal, { open: !!membersPlan, title: membersPlan ? `Show Members — ${membersPlan.name}` : "Show Members", onClose: () => setMembersPlan(null), children: [membersLoading && _jsx("p", { className: "muted-text", children: "Loading\u2026" }), !membersLoading && membersData && (_jsxs(_Fragment, { children: [_jsx("h4", { style: { marginTop: 0 }, children: "Users" }), membersData.users.length === 0 ? (_jsx("p", { className: "muted-text", children: "No users assigned directly." })) : (_jsx("ul", { style: { marginTop: 0 }, children: membersData.users.map((u) => (_jsxs("li", { children: [u.display_name || u.username, _jsxs("span", { className: "muted-text", children: [" \u00B7 ", u.username, u.email ? ` · ${u.email}` : ""] })] }, u.id))) })), _jsx("h4", { children: "Groups" }), membersData.groups.length === 0 ? (_jsx("p", { className: "muted-text", children: "No groups assigned." })) : (_jsx("ul", { style: { marginTop: 0 }, children: membersData.groups.map((g) => (_jsxs("li", { children: [g.name, _jsxs("span", { className: "muted-text", children: [" \u00B7 ", g.source, " \u00B7 ", g.member_count, " member(s)"] })] }, g.id))) })), membersData.departments.length > 0 && (_jsxs(_Fragment, { children: [_jsx("h4", { children: "Departments" }), _jsx("ul", { style: { marginTop: 0 }, children: membersData.departments.map((d) => (_jsx("li", { children: d }, d))) })] }))] }))] })] }));
}
