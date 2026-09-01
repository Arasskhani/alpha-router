import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import ApiKeyFormModal from "../../components/apiKeys/ApiKeyFormModal";
import ApiKeyCreatedModal from "../../components/apiKeys/ApiKeyCreatedModal";
import ApiKeyInspectButtons from "../../components/apiKeys/ApiKeyInspectButtons";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import { formatLocalDate, formatLocalDateTime } from "../../lib/dateTime";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
function formatExpire(k) {
    if (k.expiration_never || !k.expires_at)
        return "Never";
    return formatLocalDate(k.expires_at);
}
function formatConnections(k) {
    if (!k.restrict_connections)
        return "All";
    const names = (k.allowed_connections || []).map((c) => c.name);
    if (names.length === 0)
        return "None";
    if (names.length <= 2)
        return names.join(", ");
    return `${names[0]}, ${names[1]} +${names.length - 2}`;
}
function formatModels(k) {
    if (!k.restrict_models)
        return "All";
    const labels = (k.allowed_models || []).map((m) => m.display_name || m.external_id);
    if (labels.length === 0)
        return "None";
    if (labels.length <= 2)
        return labels.join(", ");
    return `${labels[0]}, ${labels[1]} +${labels.length - 2}`;
}
function formatDateTime(iso) {
    return formatLocalDateTime(iso);
}
const PAGE_SIZE_OPTIONS = [10, 20, 30, 50];
function formatUsd(v) {
    if (v >= 1)
        return `$${v.toFixed(2)}`;
    if (v > 0)
        return `$${v.toFixed(4)}`;
    return "$0";
}
export default function AdminApiKeys() {
    const { confirm } = useConfirm();
    const navigate = useNavigate();
    const [keys, setKeys] = useState([]);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [total, setTotal] = useState(0);
    const [totalPages, setTotalPages] = useState(1);
    const [searchName, setSearchName] = useState("");
    const [searchOwner, setSearchOwner] = useState("");
    const [msg, setMsg] = useState("");
    const [err, setErr] = useState("");
    const [createOpen, setCreateOpen] = useState(false);
    const [editKey, setEditKey] = useState(null);
    const [created, setCreated] = useState(null);
    const [selectedIds, setSelectedIds] = useState([]);
    const [bulkOpen, setBulkOpen] = useState(false);
    const [bulkBusy, setBulkBusy] = useState(false);
    const load = useCallback(() => {
        const qs = new URLSearchParams();
        qs.set("page", String(page));
        qs.set("page_size", String(pageSize));
        if (searchName.trim())
            qs.set("q", searchName.trim());
        if (searchOwner.trim())
            qs.set("owner", searchOwner.trim());
        api(`/api/admin/api-keys?${qs}`)
            .then((res) => {
            setKeys(res.items);
            setTotal(res.total);
            setPage(res.page);
            setTotalPages(res.total_pages);
            setSelectedIds([]);
        })
            .catch((e) => setErr(String(e)));
    }, [searchName, searchOwner, page, pageSize]);
    const visibleIds = useMemo(() => keys.map((k) => k.id), [keys]);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
    function toggleSelectAllVisible() {
        if (allVisibleSelected) {
            setSelectedIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
        }
        else {
            setSelectedIds((prev) => [...new Set([...prev, ...visibleIds])]);
        }
    }
    function toggleRowSelection(id) {
        setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    }
    useEffect(() => {
        const t = window.setTimeout(load, 250);
        return () => window.clearTimeout(t);
    }, [load]);
    useEffect(() => {
        setPage(1);
    }, [searchName, searchOwner, pageSize]);
    async function createKey(values) {
        const res = await api("/api/admin/api-keys", {
            method: "POST",
            body: JSON.stringify({
                name: values.name,
                owner_user_id: values.owner_user_id,
                credit_limit_usd: values.credit_limit_usd ?? 0,
                reset_period: values.reset_period,
                expiration_days: values.expiration_never ? null : values.expiration_days,
                restrict_connections: values.restrict_connections,
                allowed_connection_ids: values.restrict_connections ? values.allowed_connection_ids : [],
                restrict_models: values.restrict_models,
                allowed_model_ids: values.restrict_models ? values.allowed_model_ids : [],
            }),
        });
        setCreated({
            api_key: res.api_key,
            url: res.url,
            name: res.name,
            owner_user_id: res.owner_user_id,
            owner_email: res.owner_email,
        });
        setMsg("Gateway key created.");
        load();
    }
    async function updateKey(values) {
        if (!editKey)
            return;
        await api(`/api/admin/api-keys/${editKey.id}`, {
            method: "PATCH",
            body: JSON.stringify({
                name: values.name,
                owner_user_id: values.owner_user_id,
                credit_limit_usd: values.credit_limit_usd ?? 0,
                reset_period: values.reset_period,
                expiration_days: values.expiration_never ? null : values.expiration_days,
                expiration_never: values.expiration_never,
                restrict_connections: values.restrict_connections,
                allowed_connection_ids: values.restrict_connections ? values.allowed_connection_ids : [],
                restrict_models: values.restrict_models,
                allowed_model_ids: values.restrict_models ? values.allowed_model_ids : [],
            }),
        });
        setMsg("API key updated.");
        load();
    }
    async function toggleKey(k) {
        await api(`/api/admin/api-keys/${k.id}/toggle?enabled=${!k.is_active}`, { method: "PATCH" });
        setMsg(k.is_active ? "Key disabled." : "Key enabled.");
        load();
    }
    async function deleteKey(k) {
        const ok = await confirm({
            title: "Delete API key",
            message: `Delete "${k.name}" permanently?`,
            danger: true,
        });
        if (!ok)
            return;
        await api(`/api/admin/api-keys/${k.id}`, { method: "DELETE" });
        setMsg("API key deleted.");
        load();
    }
    async function runBulk(action) {
        if (!selectedIds.length)
            return;
        if (action === "delete") {
            const ok = await confirm({
                title: "Delete API keys",
                message: `Delete ${selectedIds.length} selected key(s) permanently?`,
                confirmLabel: "Delete",
                danger: true,
            });
            if (!ok)
                return;
        }
        setBulkBusy(true);
        setErr("");
        try {
            const r = await api(`/api/admin/api-keys/bulk?action=${action}`, {
                method: "POST",
                body: JSON.stringify({ ids: selectedIds }),
            });
            setMsg(action === "delete"
                ? `Deleted ${r.count} key(s).`
                : `${action === "on" ? "Enabled" : "Disabled"} ${r.count} key(s).`);
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
    return (_jsxs(AdminPage, { title: "API Keys", actions: _jsx("button", { type: "button", className: "btn api-keys-new-btn", onClick: () => setCreateOpen(true), children: "+ New Key" }), children: [_jsx("p", { className: "muted-text api-keys-lead", children: "Admin gateway keys for products and services (Open WebUI, integrations). Per-user keys are managed from Users." }), msg && _jsx("p", { className: "alert alert-success", children: msg }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("div", { className: "api-keys-toolbar card", children: [_jsx("input", { type: "search", className: "input-block api-keys-search", placeholder: "Search by name\u2026", value: searchName, onChange: (e) => setSearchName(e.target.value) }), _jsx("input", { type: "search", className: "input-block api-keys-search", placeholder: "Filter by owner\u2026", value: searchOwner, onChange: (e) => setSearchOwner(e.target.value) }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: selectedIds.length === 0, onClick: () => setBulkOpen(true), title: selectedIds.length ? `${selectedIds.length} selected` : "Select keys first", children: "Bulk Edit" })] }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "card data-table api-keys-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { className: "col-sm", children: _jsx("input", { type: "checkbox", checked: allVisibleSelected, onChange: toggleSelectAllVisible, "aria-label": "Select all keys on this page" }) }), _jsx("th", { children: "Name" }), _jsx("th", { className: "col-md", children: "Connections" }), _jsx("th", { className: "col-md", children: "Models" }), _jsx("th", { className: "col-lg", children: "Date Created" }), _jsx("th", { className: "col-lg", children: "Date Modified" }), _jsx("th", { className: "col-md", children: "Expire" }), _jsx("th", { className: "col-lg", children: "Last used" }), _jsx("th", { className: "col-sm", children: "Usage" }), _jsx("th", { className: "col-md", children: "Limit" }), _jsx("th", { className: "col-actions", children: "Actions" })] }) }), _jsxs("tbody", { children: [keys.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 11, className: "muted-text", children: "No gateway keys yet. Create one with + New Key." }) })), keys.map((k) => {
                                    const limit = k.credit_limit_usd;
                                    const periodPct = limit > 0 ? Math.min(100, (k.period_used_usd / limit) * 100) : 0;
                                    return (_jsxs("tr", { className: k.is_active ? "" : "api-keys-row--disabled", children: [_jsx("td", { className: "col-sm", children: _jsx("input", { type: "checkbox", checked: selectedIds.includes(k.id), onChange: () => toggleRowSelection(k.id), "aria-label": `Select ${k.name}` }) }), _jsx("td", { children: _jsxs("div", { className: "api-keys-name-cell", children: [_jsx("strong", { children: k.name }), k.owner_email || k.owner_username ? (_jsxs("span", { className: "muted-text api-keys-owner", children: [k.owner_display_name || k.owner_username, " \u00B7 ", k.owner_email] })) : null] }) }), _jsx("td", { className: "col-md", title: formatConnections(k), children: formatConnections(k) }), _jsx("td", { className: "col-md", title: formatModels(k), children: formatModels(k) }), _jsx("td", { className: "col-lg", children: formatDateTime(k.created_at) }), _jsx("td", { className: "col-lg", children: formatDateTime(k.updated_at) }), _jsx("td", { className: "col-md", children: formatExpire(k) }), _jsx("td", { className: "col-lg", children: k.last_used_at ? formatDateTime(k.last_used_at) : "Never" }), _jsx("td", { className: "col-sm", children: formatUsd(k.total_used_usd) }), _jsx("td", { className: "col-md", children: _jsxs("div", { className: "api-keys-limit", children: [_jsx("span", { children: limit > 0 ? formatUsd(limit) : "—" }), limit > 0 ? (_jsx("div", { className: "api-keys-limit-bar", "aria-hidden": true, children: _jsx("div", { className: "api-keys-limit-fill", style: { width: `${periodPct}%` } }) })) : null, _jsxs("span", { className: "muted-text api-keys-limit-period", children: [k.reset_period, " \u00B7 period ", formatUsd(k.period_used_usd)] })] }) }), _jsx("td", { className: "col-actions", children: _jsx(RowActionsMenu, { actions: [
                                                        {
                                                            label: "Edit",
                                                            onClick: () => setEditKey(k),
                                                        },
                                                        {
                                                            label: USAGE_AND_ACTIVITY_LABEL,
                                                            menuWrap: true,
                                                            onClick: () => navigate(`/admin/api-keys/${k.id}/activity`),
                                                        },
                                                        {
                                                            label: "Logs",
                                                            onClick: () => navigate(`/admin/api-keys/${k.id}/logs`),
                                                        },
                                                        {
                                                            label: k.is_active ? "Disable" : "Enable",
                                                            onClick: () => toggleKey(k),
                                                        },
                                                        { label: "Delete", onClick: () => deleteKey(k), danger: true },
                                                    ] }) })] }, k.id));
                                })] })] }) }), _jsxs("div", { className: "api-keys-footer-bar", children: [_jsxs("p", { className: "muted-text api-keys-footer", children: [total, " key", total === 1 ? "" : "s", total > 0 ? ` · page ${page} of ${totalPages}` : "", selectedIds.length > 0 ? ` · ${selectedIds.length} selected` : ""] }), _jsxs("div", { className: "api-keys-footer-controls", children: [_jsxs("label", { className: "api-keys-page-size", children: [_jsx("span", { className: "muted-text", children: "Per page" }), _jsx("select", { className: "input-block", value: pageSize, onChange: (e) => setPageSize(Number(e.target.value)), children: PAGE_SIZE_OPTIONS.map((n) => (_jsx("option", { value: n, children: n }, n))) })] }), _jsxs("div", { className: "api-keys-pager", children: [_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", disabled: page <= 1, onClick: () => setPage((p) => Math.max(1, p - 1)), children: "\u2039 Prev" }), _jsxs("span", { className: "api-keys-pager__status", children: [page, " / ", totalPages] }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", disabled: page >= totalPages, onClick: () => setPage((p) => Math.min(totalPages, p + 1)), children: "Next \u203A" })] })] })] }), _jsx(ApiKeyFormModal, { open: createOpen, title: "Create API Key", onClose: () => setCreateOpen(false), onSubmit: createKey }), _jsx(ApiKeyFormModal, { open: !!editKey, title: "Edit API Key", headerActions: editKey ? _jsx(ApiKeyInspectButtons, { keyId: editKey.id }) : undefined, initial: editKey
                    ? {
                        name: editKey.name,
                        owner_user_id: editKey.owner_user_id ?? undefined,
                        credit_limit_usd: editKey.credit_limit_usd,
                        reset_period: editKey.reset_period,
                        expiration_never: editKey.expiration_never,
                        expiration_days: editKey.expiration_never
                            ? null
                            : editKey.expires_at && editKey.created_at
                                ? Math.max(1, Math.round((new Date(editKey.expires_at).getTime() - new Date(editKey.created_at).getTime()) /
                                    86400000))
                                : 60,
                        restrict_connections: editKey.restrict_connections,
                        allowed_connection_ids: (editKey.allowed_connections || []).map((c) => c.id),
                        restrict_models: editKey.restrict_models,
                        allowed_model_ids: (editKey.allowed_models || []).map((m) => m.id),
                    }
                    : undefined, onClose: () => setEditKey(null), onSubmit: updateKey }), _jsxs(Modal, { open: bulkOpen, title: `Bulk Edit (${selectedIds.length} keys)`, onClose: () => !bulkBusy && setBulkOpen(false), children: [_jsx("p", { className: "muted-text", children: "Apply an action to all selected API keys on this page and other pages." }), _jsxs("div", { className: "dialog-actions", style: { flexWrap: "wrap", gap: "0.5rem" }, children: [_jsx("button", { type: "button", className: "btn", disabled: bulkBusy, onClick: () => runBulk("on"), children: bulkBusy ? "…" : "Enable" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => runBulk("off"), children: "Disable" }), _jsx("button", { type: "button", className: "btn btn-danger", disabled: bulkBusy, onClick: () => runBulk("delete"), children: "Delete" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => setBulkOpen(false), children: "Cancel" })] })] }), created ? (_jsx(ApiKeyCreatedModal, { open: true, apiKey: created.api_key, url: created.url, name: created.name, ownerUserId: created.owner_user_id, ownerEmail: created.owner_email, onClose: () => setCreated(null) })) : null] }));
}
