import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import Modal from "../Modal";
const defaultValues = {
    username: "",
    email: "",
    password: "",
    display_name: "",
    company: "",
    department: "",
    office: "",
    job_title: "",
    reporting_to: "",
    role: "user",
    group_id: null,
    budget_plan: "__inherit__",
};
export default function CreateLocalUserModal({ open, roles, plans, onClose, onSubmit }) {
    const [form, setForm] = useState(defaultValues);
    const [localGroups, setLocalGroups] = useState([]);
    const [saving, setSaving] = useState(false);
    const [err, setErr] = useState("");
    useEffect(() => {
        if (!open)
            return;
        setErr("");
        setForm(defaultValues);
        void api("/api/admin/groups?source=local")
            .then(setLocalGroups)
            .catch(() => setLocalGroups([]));
    }, [open]);
    const roleOptions = useMemo(() => [...roles]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((role) => (_jsx("option", { value: role.slug, children: role.name }, role.slug))), [roles]);
    async function handleSubmit(e) {
        e.preventDefault();
        if (!form.username.trim()) {
            setErr("Username is required.");
            return;
        }
        if (!form.email.trim()) {
            setErr("Email is required.");
            return;
        }
        if (!form.password) {
            setErr("Password is required.");
            return;
        }
        setSaving(true);
        setErr("");
        try {
            await onSubmit({
                ...form,
                username: form.username.trim(),
                email: form.email.trim(),
                display_name: form.display_name.trim(),
                company: form.company.trim(),
                department: form.department.trim(),
                office: form.office.trim(),
                job_title: form.job_title.trim(),
                reporting_to: form.reporting_to.trim(),
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
    return (_jsx(Modal, { open: open, title: "Create local user", onClose: onClose, children: _jsxs("form", { onSubmit: handleSubmit, children: [_jsx("label", { children: "Username" }), _jsx("input", { className: "input-block", value: form.username, onChange: (e) => setForm((f) => ({ ...f, username: e.target.value })), autoComplete: "off", required: true }), _jsx("label", { children: "Email" }), _jsx("input", { type: "email", className: "input-block", value: form.email, onChange: (e) => setForm((f) => ({ ...f, email: e.target.value })), autoComplete: "off", required: true }), _jsx("label", { children: "Password" }), _jsx("input", { type: "password", className: "input-block", value: form.password, onChange: (e) => setForm((f) => ({ ...f, password: e.target.value })), autoComplete: "new-password", required: true }), _jsx("label", { children: "Display name" }), _jsx("input", { className: "input-block", value: form.display_name, onChange: (e) => setForm((f) => ({ ...f, display_name: e.target.value })) }), _jsx("label", { children: "Company" }), _jsx("input", { className: "input-block", value: form.company, onChange: (e) => setForm((f) => ({ ...f, company: e.target.value })) }), _jsx("label", { children: "Department" }), _jsx("input", { className: "input-block", value: form.department, onChange: (e) => setForm((f) => ({ ...f, department: e.target.value })) }), _jsx("label", { children: "Office" }), _jsx("input", { className: "input-block", value: form.office, onChange: (e) => setForm((f) => ({ ...f, office: e.target.value })) }), _jsx("label", { children: "Job title" }), _jsx("input", { className: "input-block", value: form.job_title, onChange: (e) => setForm((f) => ({ ...f, job_title: e.target.value })) }), _jsx("label", { children: "Report to" }), _jsx("input", { className: "input-block", value: form.reporting_to, onChange: (e) => setForm((f) => ({ ...f, reporting_to: e.target.value })) }), _jsx("label", { children: "Role" }), _jsx("select", { className: "input-block", value: form.role, onChange: (e) => setForm((f) => ({ ...f, role: e.target.value })), children: roleOptions }), _jsx("label", { children: "Group" }), _jsxs("select", { className: "input-block", value: form.group_id ?? "", onChange: (e) => setForm((f) => ({
                        ...f,
                        group_id: e.target.value ? Number(e.target.value) : null,
                    })), children: [_jsx("option", { value: "", children: "No group" }), localGroups.map((g) => (_jsx("option", { value: String(g.id), children: g.name }, g.id)))] }), localGroups.length === 0 ? (_jsxs("p", { className: "muted-text", style: { marginTop: "-0.35rem", marginBottom: "0.75rem" }, children: ["No local groups yet.", " ", _jsx(Link, { to: "/admin/groups", onClick: onClose, children: "Create one on Groups" }), "."] })) : (_jsx("p", { className: "muted-text", style: { marginTop: "-0.35rem", marginBottom: "0.75rem" }, children: "Only local groups are listed. LDAP membership is managed by directory sync; SAML users are provisioned on login." })), _jsx("label", { children: "Budget plan" }), _jsxs("select", { className: "input-block", value: form.budget_plan, onChange: (e) => setForm((f) => ({ ...f, budget_plan: e.target.value })), children: [_jsx("option", { value: "__inherit__", children: "From group" }), _jsx("option", { value: "__none__", children: "No Plan" }), plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] }), err && _jsx("p", { className: "error", children: err }), _jsxs("div", { className: "modal-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: onClose, disabled: saving, children: "Cancel" }), _jsx("button", { type: "submit", className: "btn", disabled: saving, children: saving ? "Creating…" : "Create user" })] })] }) }));
}
