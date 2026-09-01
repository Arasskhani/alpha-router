import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { api } from "../../api";
import UserOwnerSelect from "../apiKeys/UserOwnerSelect";
import Modal from "../Modal";
const DEPARTMENT_OTHER = "__other__";
export default function AssignPlanModal({ open, plans, groups, initialPlanId, onClose, onSubmit, }) {
    const [planId, setPlanId] = useState("");
    const [target, setTarget] = useState("group");
    const [groupId, setGroupId] = useState("");
    const [userId, setUserId] = useState(null);
    const [departmentKey, setDepartmentKey] = useState("");
    const [departmentOther, setDepartmentOther] = useState("");
    const [departments, setDepartments] = useState([]);
    const [departmentsLoading, setDepartmentsLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [err, setErr] = useState("");
    useEffect(() => {
        if (!open)
            return;
        setErr("");
        setTarget("group");
        setGroupId("");
        setUserId(null);
        setDepartmentKey("");
        setDepartmentOther("");
        setPlanId(initialPlanId ? String(initialPlanId) : "");
        setDepartmentsLoading(true);
        void api("/api/admin/plans/departments")
            .then(setDepartments)
            .catch(() => setDepartments([]))
            .finally(() => setDepartmentsLoading(false));
    }, [open, initialPlanId]);
    function resolvedDepartment() {
        if (departmentKey === DEPARTMENT_OTHER)
            return departmentOther.trim();
        return departmentKey.trim();
    }
    async function handleSubmit(e) {
        e.preventDefault();
        if (!planId) {
            setErr("Select a plan.");
            return;
        }
        if (target === "group" && !groupId) {
            setErr("Select a group.");
            return;
        }
        if (target === "user" && !userId) {
            setErr("Select a user.");
            return;
        }
        if (target === "department") {
            const dept = resolvedDepartment();
            if (!departmentKey) {
                setErr("Select a department.");
                return;
            }
            if (departmentKey === DEPARTMENT_OTHER && !dept) {
                setErr("Enter a department name.");
                return;
            }
        }
        setSaving(true);
        setErr("");
        try {
            await onSubmit({
                plan_id: Number(planId),
                target,
                group_id: target === "group" ? Number(groupId) : null,
                user_id: target === "user" ? userId : null,
                department: target === "department" ? resolvedDepartment() : "",
            });
            onClose();
        }
        catch (ex) {
            setErr(String(ex));
        }
        finally {
            setSaving(false);
        }
    }
    const selectedPlan = plans.find((p) => String(p.id) === planId);
    return (_jsx(Modal, { open: open, title: "Assign plan", onClose: onClose, children: _jsxs("form", { onSubmit: handleSubmit, children: [_jsx("label", { children: "Plan" }), _jsxs("select", { className: "input-block", value: planId, onChange: (e) => setPlanId(e.target.value), required: true, children: [_jsx("option", { value: "", children: "Select plan\u2026" }), plans.map((p) => (_jsxs("option", { value: String(p.id), children: [p.name, " ($", p.monthly_budget_usd, "/mo)"] }, p.id)))] }), selectedPlan ? (_jsxs("p", { className: "muted-text", style: { marginTop: "-0.35rem", marginBottom: "0.75rem" }, children: ["Monthly budget: $", selectedPlan.monthly_budget_usd] })) : null, _jsx("label", { children: "Assign to" }), _jsxs("select", { className: "input-block", value: target, onChange: (e) => setTarget(e.target.value), children: [_jsx("option", { value: "group", children: "Group" }), _jsx("option", { value: "user", children: "User" }), _jsx("option", { value: "department", children: "Department" })] }), target === "group" ? (_jsxs(_Fragment, { children: [_jsx("label", { children: "Group" }), _jsxs("select", { className: "input-block", value: groupId, onChange: (e) => setGroupId(e.target.value), children: [_jsx("option", { value: "", children: "Select group\u2026" }), groups.map((g) => (_jsxs("option", { value: String(g.id), children: [g.name, " (", g.source, ")"] }, g.id)))] }), _jsx("p", { className: "muted-text", style: { marginTop: "-0.35rem", marginBottom: "0.75rem" }, children: "Group members with \u00ABFrom group\u00BB budget inherit this plan unless they have a direct user plan." })] })) : null, target === "user" ? (_jsxs(_Fragment, { children: [_jsx("label", { children: "User" }), _jsx(UserOwnerSelect, { value: userId, onChange: (u) => setUserId(u?.id ?? null) }), _jsx("p", { className: "muted-text", style: { marginTop: "-0.35rem", marginBottom: "0.75rem" }, children: "Assigns the plan directly to the user, overriding group and department inheritance." })] })) : null, target === "department" ? (_jsxs(_Fragment, { children: [_jsx("label", { children: "Department" }), _jsxs("select", { className: "input-block", value: departmentKey, onChange: (e) => setDepartmentKey(e.target.value), disabled: departmentsLoading, children: [_jsx("option", { value: "", children: departmentsLoading ? "Loading departments…" : "Select department…" }), departments.map((d) => (_jsxs("option", { value: d.name, children: [d.name, d.user_count > 0
                                            ? ` (${d.user_count} user${d.user_count === 1 ? "" : "s"})`
                                            : " (assigned, no users)"] }, d.name))), _jsx("option", { value: DEPARTMENT_OTHER, children: "Other\u2026" })] }), departmentKey === DEPARTMENT_OTHER ? (_jsxs(_Fragment, { children: [_jsx("label", { children: "Department name" }), _jsx("input", { className: "input-block", value: departmentOther, onChange: (e) => setDepartmentOther(e.target.value), placeholder: "New department name" })] })) : null, _jsx("p", { className: "muted-text", style: { marginTop: "-0.35rem", marginBottom: "0.75rem" }, children: "Lists departments from user profiles and existing plan assignments. Matching is exact \u2014 it must match each user's Department field." })] })) : null, err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: saving, children: saving ? "Assigning…" : "Assign" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: onClose, children: "Cancel" })] })] }) }));
}
