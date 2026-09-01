import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import Modal from "../Modal";
const emptyValues = {
    name: "",
    description: "",
    budget_plan: "__none__",
};
function toFormValues(initial) {
    if (!initial)
        return emptyValues;
    return {
        name: initial.name,
        description: initial.description ?? "",
        budget_plan: initial.plan_id ? String(initial.plan_id) : "__none__",
    };
}
export default function LocalGroupFormModal({ open, mode, initial, plans, onClose, onSubmit }) {
    const [form, setForm] = useState(emptyValues);
    const [saving, setSaving] = useState(false);
    const [err, setErr] = useState("");
    useEffect(() => {
        if (!open)
            return;
        setErr("");
        setForm(toFormValues(mode === "edit" ? initial : null));
    }, [open, mode, initial]);
    async function handleSubmit(e) {
        e.preventDefault();
        if (!form.name.trim()) {
            setErr("Name is required.");
            return;
        }
        setSaving(true);
        setErr("");
        try {
            await onSubmit({
                name: form.name.trim(),
                description: form.description.trim(),
                budget_plan: form.budget_plan,
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
    const title = mode === "create" ? "Create local group" : "Edit local group";
    const submitLabel = mode === "create" ? "Create" : "Save";
    const savingLabel = mode === "create" ? "Creating…" : "Saving…";
    return (_jsx(Modal, { open: open, title: title, onClose: onClose, children: _jsxs("form", { onSubmit: handleSubmit, children: [mode === "edit" && initial ? (_jsxs("p", { className: "muted-text", style: { marginTop: 0 }, children: ["Local group \u00B7 ", _jsx("strong", { children: initial.name })] })) : null, _jsx("label", { children: "Name" }), _jsx("input", { className: "input-block", value: form.name, onChange: (e) => setForm((f) => ({ ...f, name: e.target.value })), required: true }), _jsx("label", { children: "Description" }), _jsx("textarea", { className: "input-block", rows: 3, value: form.description, onChange: (e) => setForm((f) => ({ ...f, description: e.target.value })) }), _jsx("label", { children: "Budget plan" }), _jsxs("select", { className: "input-block", value: form.budget_plan, onChange: (e) => setForm((f) => ({ ...f, budget_plan: e.target.value })), children: [_jsx("option", { value: "__none__", children: "No plan" }), plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] }), _jsx("p", { className: "muted-text", style: { marginTop: "-0.35rem", marginBottom: "0.75rem" }, children: "Members with \u00ABFrom group\u00BB budget inherit this plan when assigned to the group." }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: saving, children: saving ? savingLabel : submitLabel }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: onClose, children: "Cancel" })] })] }) }));
}
