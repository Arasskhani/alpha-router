import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import Modal from "../Modal";
const emptyValues = {
    name: "",
    monthly_budget_usd: 5,
};
function toFormValues(initial) {
    if (!initial)
        return emptyValues;
    return {
        name: initial.name,
        monthly_budget_usd: initial.monthly_budget_usd,
    };
}
export default function PlanFormModal({ open, mode, initial, onClose, onSubmit }) {
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
            setErr("Plan name is required.");
            return;
        }
        if (!Number.isFinite(form.monthly_budget_usd) || form.monthly_budget_usd < 0) {
            setErr("Monthly budget must be zero or greater.");
            return;
        }
        setSaving(true);
        setErr("");
        try {
            await onSubmit({
                name: form.name.trim(),
                monthly_budget_usd: form.monthly_budget_usd,
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
    const title = mode === "create" ? "New plan" : "Edit plan";
    const submitLabel = mode === "create" ? "Create" : "Save";
    const savingLabel = mode === "create" ? "Creating…" : "Saving…";
    return (_jsx(Modal, { open: open, title: title, onClose: onClose, children: _jsxs("form", { onSubmit: handleSubmit, children: [mode === "edit" && initial ? (_jsxs("p", { className: "muted-text", style: { marginTop: 0 }, children: ["Plan \u00B7 ", _jsx("strong", { children: initial.name })] })) : null, _jsx("label", { children: "Plan name" }), _jsx("input", { className: "input-block", value: form.name, onChange: (e) => setForm((f) => ({ ...f, name: e.target.value })), required: true }), _jsx("label", { children: "Monthly budget (USD)" }), _jsx("input", { type: "number", step: "0.01", min: 0, className: "input-block", value: form.monthly_budget_usd, onChange: (e) => setForm((f) => ({ ...f, monthly_budget_usd: Number(e.target.value) })), required: true }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: saving, children: saving ? savingLabel : submitLabel }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: onClose, children: "Cancel" })] })] }) }));
}
