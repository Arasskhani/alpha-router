import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import Modal from "../Modal";
import ConnectionAllowlistField from "./ConnectionAllowlistField";
import ModelAllowlistField from "./ModelAllowlistField";
import UserOwnerSelect from "./UserOwnerSelect";
const defaultValues = {
    name: "",
    owner_user_id: 0,
    credit_limit_usd: null,
    reset_period: "monthly",
    expiration_days: null,
    expiration_never: false,
    restrict_connections: false,
    allowed_connection_ids: [],
    restrict_models: false,
    allowed_model_ids: [],
};
export default function ApiKeyFormModal({ open, title, initial, onClose, onSubmit, headerActions }) {
    const [form, setForm] = useState(defaultValues);
    const [saving, setSaving] = useState(false);
    const [err, setErr] = useState("");
    useEffect(() => {
        if (!open)
            return;
        setErr("");
        setForm({
            name: initial?.name ?? "",
            owner_user_id: initial?.owner_user_id ?? 0,
            credit_limit_usd: initial?.credit_limit_usd ?? null,
            reset_period: initial?.reset_period ?? "monthly",
            expiration_days: initial?.expiration_days ?? null,
            expiration_never: initial?.expiration_never ?? false,
            restrict_connections: initial?.restrict_connections ?? false,
            allowed_connection_ids: initial?.allowed_connection_ids ?? [],
            restrict_models: initial?.restrict_models ?? false,
            allowed_model_ids: initial?.allowed_model_ids ?? [],
        });
    }, [open, initial]);
    async function handleSubmit(e) {
        e.preventDefault();
        if (!form.owner_user_id) {
            setErr("Select an owner.");
            return;
        }
        if (!form.name.trim()) {
            setErr("Name is required.");
            return;
        }
        if (!form.expiration_never && (form.expiration_days == null || form.expiration_days < 1)) {
            setErr("Enter expiration days or choose Never.");
            return;
        }
        setSaving(true);
        setErr("");
        try {
            await onSubmit(form);
            onClose();
        }
        catch (ex) {
            setErr(String(ex));
        }
        finally {
            setSaving(false);
        }
    }
    return (_jsx(Modal, { open: open, title: title, onClose: onClose, headerActions: headerActions, children: _jsxs("form", { className: "api-key-form", onSubmit: handleSubmit, children: [_jsxs("label", { className: "api-key-form__label", children: ["Owner", _jsx(UserOwnerSelect, { value: form.owner_user_id || null, onChange: (u) => setForm((f) => ({ ...f, owner_user_id: u?.id ?? 0 })), disabled: saving })] }), _jsxs("label", { className: "api-key-form__label", children: ["Name", _jsx("input", { className: "input-block", value: form.name, onChange: (e) => setForm((f) => ({ ...f, name: e.target.value })), required: true })] }), _jsxs("label", { className: "api-key-form__label", children: ["Credit limit (USD, optional)", _jsx("input", { type: "number", min: 0, step: 0.01, className: "input-block", value: form.credit_limit_usd ?? "", onChange: (e) => setForm((f) => ({
                                ...f,
                                credit_limit_usd: e.target.value === "" ? null : Number(e.target.value),
                            })) }), _jsx("span", { className: "muted-text api-key-form__hint", children: "Leave empty for no cap; 0 also means no cap" })] }), _jsxs("label", { className: "api-key-form__label", children: ["Reset limit every\u2026", _jsxs("select", { className: "input-block", value: form.reset_period, onChange: (e) => setForm((f) => ({
                                ...f,
                                reset_period: e.target.value,
                            })), children: [_jsx("option", { value: "daily", children: "Daily" }), _jsx("option", { value: "weekly", children: "Weekly" }), _jsx("option", { value: "monthly", children: "Monthly" })] })] }), _jsxs("label", { className: "api-key-form__label", children: ["Expiration", _jsxs("div", { className: "api-key-form__expiration", children: [_jsxs("label", { className: "api-key-form__never", children: [_jsx("input", { type: "checkbox", checked: form.expiration_never, onChange: (e) => setForm((f) => ({
                                                ...f,
                                                expiration_never: e.target.checked,
                                                expiration_days: e.target.checked ? null : f.expiration_days,
                                            })) }), "Never"] }), !form.expiration_never ? (_jsx("input", { type: "number", min: 1, className: "input-block", placeholder: "Days active", value: form.expiration_days ?? "", onChange: (e) => setForm((f) => ({
                                        ...f,
                                        expiration_days: e.target.value ? Number(e.target.value) : null,
                                    })) })) : null] }), _jsx("span", { className: "muted-text api-key-form__hint", children: "After N days the key is deactivated automatically" })] }), _jsxs("fieldset", { className: "api-key-form__connections", children: [_jsx("legend", { className: "api-key-form__label", children: "Allowed connections" }), _jsxs("label", { className: "api-key-form__never", children: [_jsx("input", { type: "checkbox", checked: form.restrict_connections, onChange: (e) => setForm((f) => ({
                                        ...f,
                                        restrict_connections: e.target.checked,
                                    })), disabled: saving }), "Limit this key to specific connections"] }), form.restrict_connections ? (_jsx(ConnectionAllowlistField, { selectedIds: form.allowed_connection_ids, onChange: (ids) => setForm((f) => ({ ...f, allowed_connection_ids: ids })), disabled: saving })) : (_jsx("span", { className: "muted-text api-key-form__hint", children: "Unchecked: the key can use models from all active connections (still subject to model access)." }))] }), _jsxs("fieldset", { className: "api-key-form__connections", children: [_jsx("legend", { className: "api-key-form__label", children: "Allowed models" }), _jsxs("label", { className: "api-key-form__never", children: [_jsx("input", { type: "checkbox", checked: form.restrict_models, onChange: (e) => setForm((f) => ({
                                        ...f,
                                        restrict_models: e.target.checked,
                                    })), disabled: saving }), "Limit this key to specific models"] }), form.restrict_models ? (_jsx(ModelAllowlistField, { ownerUserId: form.owner_user_id, connectionIds: form.restrict_connections ? form.allowed_connection_ids : [], restrictConnections: form.restrict_connections, selectedIds: form.allowed_model_ids, onChange: (ids) => setForm((f) => ({ ...f, allowed_model_ids: ids })), disabled: saving })) : (_jsx("span", { className: "muted-text api-key-form__hint", children: "Unchecked: all models allowed by connection policy and the owner's catalog access." }))] }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: saving, children: saving ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: onClose, children: "Cancel" })] })] }) }));
}
