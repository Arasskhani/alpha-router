import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import Modal from "../Modal";
import { knownConnectionBaseUrls, resolveConnectionProvider, suggestConnectionProviders, } from "../../lib/connectionProviders";
const defaultValues = {
    name: "",
    provider_type: "",
    api_key: "",
    base_url: "",
    sync_interval_hours: 6,
};
const KNOWN_BASE_URLS = knownConnectionBaseUrls();
export default function ConnectionFormModal({ open, title, initial, onClose, onSubmit }) {
    const [form, setForm] = useState(defaultValues);
    const [saving, setSaving] = useState(false);
    const [err, setErr] = useState("");
    const [providerOpen, setProviderOpen] = useState(false);
    const [activeSuggestion, setActiveSuggestion] = useState(0);
    const providerWrapRef = useRef(null);
    const lastAutoBaseUrlRef = useRef("");
    useEffect(() => {
        if (!open)
            return;
        setErr("");
        setProviderOpen(false);
        setActiveSuggestion(0);
        const next = {
            name: initial?.name ?? "",
            provider_type: initial?.provider_type ?? "",
            api_key: "",
            base_url: initial?.base_url ?? "",
            sync_interval_hours: initial?.sync_interval_hours ?? 6,
        };
        setForm(next);
        lastAutoBaseUrlRef.current = next.base_url && KNOWN_BASE_URLS.has(next.base_url) ? next.base_url : "";
    }, [open, initial]);
    useEffect(() => {
        if (!providerOpen)
            return;
        const onDoc = (e) => {
            if (providerWrapRef.current && !providerWrapRef.current.contains(e.target)) {
                setProviderOpen(false);
            }
        };
        document.addEventListener("mousedown", onDoc);
        return () => document.removeEventListener("mousedown", onDoc);
    }, [providerOpen]);
    const suggestions = useMemo(() => suggestConnectionProviders(form.provider_type, 8), [form.provider_type]);
    const matchedPreset = useMemo(() => resolveConnectionProvider(form.provider_type), [form.provider_type]);
    const baseHint = matchedPreset?.baseUrl ||
        suggestions[0]?.baseUrl ||
        "e.g. https://api.example.com/v1";
    function canAutofillBaseUrl(current) {
        const trimmed = current.trim();
        if (!trimmed)
            return true;
        if (trimmed === lastAutoBaseUrlRef.current)
            return true;
        if (KNOWN_BASE_URLS.has(trimmed))
            return true;
        return false;
    }
    function applyPreset(preset) {
        setForm((f) => {
            const nextBase = canAutofillBaseUrl(f.base_url) ? preset.baseUrl : f.base_url;
            if (canAutofillBaseUrl(f.base_url)) {
                lastAutoBaseUrlRef.current = preset.baseUrl;
            }
            return {
                ...f,
                provider_type: preset.id,
                base_url: nextBase,
                name: f.name.trim() ? f.name : preset.label,
            };
        });
        setProviderOpen(false);
        setActiveSuggestion(0);
    }
    function onProviderChange(raw) {
        const preset = resolveConnectionProvider(raw);
        setForm((f) => {
            if (!preset) {
                return { ...f, provider_type: raw };
            }
            const nextBase = canAutofillBaseUrl(f.base_url) ? preset.baseUrl : f.base_url;
            if (canAutofillBaseUrl(f.base_url)) {
                lastAutoBaseUrlRef.current = preset.baseUrl;
            }
            return {
                ...f,
                provider_type: raw,
                base_url: nextBase,
            };
        });
        setProviderOpen(true);
        setActiveSuggestion(0);
    }
    function onProviderKeyDown(e) {
        if (!providerOpen || suggestions.length === 0)
            return;
        if (e.key === "ArrowDown") {
            e.preventDefault();
            setActiveSuggestion((i) => (i + 1) % suggestions.length);
            return;
        }
        if (e.key === "ArrowUp") {
            e.preventDefault();
            setActiveSuggestion((i) => (i - 1 + suggestions.length) % suggestions.length);
            return;
        }
        if (e.key === "Enter" && providerOpen) {
            e.preventDefault();
            applyPreset(suggestions[activeSuggestion] ?? suggestions[0]);
            return;
        }
        if (e.key === "Escape") {
            setProviderOpen(false);
        }
    }
    async function handleSubmit(e) {
        e.preventDefault();
        if (!form.name.trim()) {
            setErr("Name is required.");
            return;
        }
        if (!form.provider_type.trim()) {
            setErr("Provider is required.");
            return;
        }
        if (!initial && !form.api_key.trim()) {
            setErr("API key is required.");
            return;
        }
        const resolved = resolveConnectionProvider(form.provider_type);
        setSaving(true);
        setErr("");
        try {
            await onSubmit({
                ...form,
                name: form.name.trim(),
                provider_type: (resolved?.id || form.provider_type).trim().toLowerCase(),
                base_url: form.base_url.trim(),
                api_key: form.api_key.trim(),
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
    return (_jsx(Modal, { open: open, title: title, onClose: onClose, children: _jsxs("form", { className: "connection-form", onSubmit: handleSubmit, children: [_jsxs("label", { className: "connection-form__label", children: ["Name", _jsx("input", { className: "input-block", value: form.name, onChange: (e) => setForm((f) => ({ ...f, name: e.target.value })), required: true })] }), _jsxs("label", { className: "connection-form__label", children: ["Provider", _jsxs("div", { className: "connection-provider-combobox", ref: providerWrapRef, children: [_jsx("input", { className: "input-block", value: form.provider_type, onChange: (e) => onProviderChange(e.target.value), onFocus: () => setProviderOpen(true), onKeyDown: onProviderKeyDown, placeholder: "Type or pick a provider (e.g. openrouter, openai)", autoComplete: "off", "aria-autocomplete": "list", "aria-expanded": providerOpen, role: "combobox", required: true }), providerOpen && suggestions.length > 0 ? (_jsx("div", { className: "connection-provider-combobox__panel card", role: "listbox", children: _jsx("ul", { className: "connection-provider-combobox__list", children: suggestions.map((preset, index) => (_jsx("li", { children: _jsxs("button", { type: "button", className: `connection-provider-combobox__item${index === activeSuggestion ? " connection-provider-combobox__item--active" : ""}`, onMouseDown: (e) => e.preventDefault(), onClick: () => applyPreset(preset), children: [_jsx("span", { className: "connection-provider-combobox__label", children: preset.label }), _jsxs("span", { className: "connection-provider-combobox__meta", children: [_jsx("code", { children: preset.id }), preset.baseUrl ? (_jsx("span", { className: "muted-text", children: preset.baseUrl })) : (_jsx("span", { className: "muted-text", children: "custom base URL" }))] })] }) }, preset.id))) }) })) : null] }), _jsx("span", { className: "muted-text connection-form__hint", children: "Suggestions autofill the provider id and default Base URL. Custom providers are still allowed." })] }), _jsxs("label", { className: "connection-form__label", children: ["Base URL", _jsx("input", { className: "input-block mono", value: form.base_url, onChange: (e) => {
                                const value = e.target.value;
                                setForm((f) => ({ ...f, base_url: value }));
                                if (value.trim() !== lastAutoBaseUrlRef.current) {
                                    lastAutoBaseUrlRef.current = "";
                                }
                            }, placeholder: baseHint }), _jsx("span", { className: "muted-text connection-form__hint", children: "Enter the API root for this use case (chat, embeddings, video, etc.). Sync uses this URL for model discovery. Leave empty to use the provider default when supported." })] }), _jsxs("label", { className: "connection-form__label", children: ["API key", initial?.api_key_masked ? (_jsxs("span", { className: "muted-text connection-form__hint", children: ["Current: ", initial.api_key_masked] })) : null, _jsx("input", { type: "password", className: "input-block", value: form.api_key, onChange: (e) => setForm((f) => ({ ...f, api_key: e.target.value })), placeholder: initial ? "Leave blank to keep current key" : "Provider API key", autoComplete: "off", required: !initial })] }), _jsxs("label", { className: "connection-form__label", children: ["Sync schedule (hours between auto-sync)", _jsx("input", { type: "number", min: 0, className: "input-block", value: form.sync_interval_hours, onChange: (e) => setForm((f) => ({ ...f, sync_interval_hours: Number(e.target.value) })) }), _jsx("span", { className: "muted-text connection-form__hint", children: "0 = manual sync only (Sync now in the table)" })] }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: saving, children: saving ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: onClose, children: "Cancel" })] })] }) }));
}
