import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "../api";
import { useConfirm } from "../context/ConfirmContext";
import Modal from "./Modal";
function formatWhen(iso) {
    if (!iso)
        return "—";
    try {
        return new Date(iso).toLocaleString();
    }
    catch {
        return iso;
    }
}
async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    }
    catch {
        try {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            return true;
        }
        catch {
            return false;
        }
    }
}
function CopyIcon() {
    return (_jsxs("svg", { viewBox: "0 0 24 24", width: "14", height: "14", fill: "none", stroke: "currentColor", strokeWidth: "2", "aria-hidden": true, children: [_jsx("rect", { x: "9", y: "9", width: "13", height: "13", rx: "2" }), _jsx("path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" })] }));
}
function CopyButton({ value, label }) {
    const [copied, setCopied] = useState(false);
    async function handleCopy() {
        const ok = await copyText(value);
        if (ok) {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
        }
    }
    return (_jsx("button", { type: "button", className: "btn btn-sm btn-ghost personal-api-key-field__copy", onClick: () => void handleCopy(), title: label, "aria-label": label, children: copied ? "✓" : _jsx(CopyIcon, {}) }));
}
function SecretField({ label, value, showCopy = true, }) {
    return (_jsxs("label", { className: "settings-field personal-api-key-field", children: [_jsx("span", { className: "settings-label", children: label }), _jsxs("div", { className: "personal-api-key-field__row", children: [_jsx("input", { readOnly: true, value: value, className: "settings-row__control mono personal-api-key-field__input", "aria-label": label }), showCopy ? _jsx(CopyButton, { value: value, label: `Copy ${label}` }) : null] })] }));
}
export default function PersonalApiKeyPanel() {
    const { confirm } = useConfirm();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");
    const [keys, setKeys] = useState([]);
    const [budget, setBudget] = useState(null);
    const [name, setName] = useState("Personal API Key");
    const [created, setCreated] = useState(null);
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const [keyRows, budgetRow] = await Promise.all([
                api("/api/user/api-keys/list"),
                api("/api/user/budget"),
            ]);
            setKeys(keyRows);
            setBudget(budgetRow);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setLoading(false);
        }
    }, []);
    useEffect(() => {
        void load();
    }, [load]);
    async function onCreate(e) {
        e.preventDefault();
        setSaving(true);
        setError("");
        setMessage("");
        try {
            const row = await api("/api/user/api-keys", {
                method: "POST",
                body: JSON.stringify({ name: name.trim() || "Personal API Key" }),
            });
            setCreated(row);
            setMessage("Copy your API key now. It will not be shown again.");
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setSaving(false);
        }
    }
    async function onRevoke(key) {
        const ok = await confirm({
            title: "Revoke personal API key?",
            message: `Permanently delete "${key.name}"? External tools using this key will stop working immediately.`,
            confirmLabel: "Revoke",
            danger: true,
        });
        if (!ok)
            return;
        setSaving(true);
        setError("");
        setMessage("");
        try {
            await api(`/api/user/api-keys/${key.id}`, { method: "DELETE" });
            setMessage("API key revoked.");
            setCreated(null);
            await load();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setSaving(false);
        }
    }
    const activeKey = keys[0] ?? null;
    const hasBudget = (budget?.monthly_budget_usd ?? 0) > 0;
    if (loading)
        return _jsx("p", { className: "muted", children: "Loading API key settings\u2026" });
    return (_jsxs("div", { className: "settings-section personal-api-key-panel", children: [_jsx("h2", { children: "Personal API Key" }), _jsx("p", { className: "settings-section-desc", children: "Use one personal key with OpenAI-compatible clients (scripts, IDEs, Kilo Code). Usage debits your monthly budget \u2014 the same pool as Chat." }), budget && (_jsxs("div", { className: "docs-callout docs-callout-info personal-api-key-panel__budget", children: ["Monthly budget:", " ", _jsxs("strong", { children: ["$", budget.used_usd.toFixed(2)] }), " used", budget.remaining_usd != null ? (_jsxs(_Fragment, { children: [" ", "\u00B7 ", _jsxs("strong", { children: ["$", budget.remaining_usd.toFixed(2)] }), " remaining"] })) : (_jsx(_Fragment, { children: " \u00B7 no plan assigned" }))] })), error && _jsx("p", { className: "settings-error", children: error }), message && _jsx("p", { className: "settings-success", children: message }), activeKey ? (_jsx("div", { className: "settings-list", children: _jsxs("div", { className: "settings-row-block settings-row-block--open", children: [_jsxs("div", { className: "settings-row", children: [_jsxs("div", { className: "settings-row__meta", children: [_jsx("span", { className: "settings-row__title", children: activeKey.name }), _jsxs("span", { className: "settings-row__hint mono", children: [activeKey.prefix, "\u2026"] }), _jsxs("span", { className: "settings-row__hint", children: ["Created ", formatWhen(activeKey.created_at), activeKey.last_used_at ? _jsxs(_Fragment, { children: [" \u00B7 Last used ", formatWhen(activeKey.last_used_at)] }) : null] })] }), _jsx("div", { className: "settings-row__trail", children: _jsx("button", { type: "button", className: "settings-row__action settings-row__action--danger", disabled: saving, onClick: () => void onRevoke(activeKey), children: "Revoke" }) })] }), _jsx("div", { className: "settings-row__detail", children: _jsx(SecretField, { label: "Base URL", value: activeKey.url, showCopy: false }) })] }) })) : (_jsx("div", { className: "settings-list", children: _jsx("div", { className: "settings-row-block", children: _jsxs("form", { className: "settings-inline-form personal-api-key-create", onSubmit: onCreate, children: [_jsxs("label", { className: "settings-field", children: [_jsx("span", { className: "settings-label", children: "Key name" }), _jsx("input", { className: "settings-row__control", value: name, onChange: (e) => setName(e.target.value), maxLength: 128, disabled: !hasBudget || saving })] }), !hasBudget && (_jsx("p", { className: "settings-hint", children: "Ask an administrator to assign a monthly budget plan before creating a key." })), _jsx("button", { type: "submit", className: "btn btn-sm btn-primary", disabled: !hasBudget || saving, children: saving ? "Creating…" : "Create API key" })] }) }) })), _jsx(Modal, { open: !!created, title: "Your personal API key", onClose: () => setCreated(null), panelClassName: "modal-panel--settings", bodyClassName: "personal-api-key-created-body", children: created && (_jsxs("div", { className: "personal-api-key-created", children: [_jsx("p", { className: "settings-hint", children: "Copy this key now. You will not be able to view it again." }), _jsx(SecretField, { label: "API key", value: created.api_key }), _jsx(SecretField, { label: "Base URL", value: created.url }), _jsxs("p", { className: "settings-hint mono personal-api-key-created__curl", children: ["curl ", created.url, "/models -H \"Authorization: Bearer ", created.api_key.slice(0, 12), "\u2026\""] }), _jsx("div", { className: "settings-actions", children: _jsx("button", { type: "button", className: "btn btn-sm btn-ghost", onClick: () => setCreated(null), children: "Done" }) })] })) })] }));
}
