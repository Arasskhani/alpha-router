import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import ConnectionFormModal from "../../components/connections/ConnectionFormModal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { formatLocalDateTime } from "../../lib/dateTime";
import { useConfirm } from "../../context/ConfirmContext";
import { BROWSER_EVENT_NAMES } from "../../lib/brand";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
function formatDateTime(iso) {
    return formatLocalDateTime(iso);
}
function formatUsd(v) {
    if (v >= 1)
        return `$${v.toFixed(2)}`;
    if (v > 0)
        return `$${v.toFixed(4)}`;
    return "$0";
}
function syncScheduleLabel(hours) {
    if (!hours || hours <= 0)
        return "Manual only";
    if (hours === 1)
        return "Every 1 hour";
    return `Every ${hours} hours`;
}
function truncateUrl(url, max = 42) {
    if (!url)
        return "Default";
    if (url.length <= max)
        return url;
    return `${url.slice(0, max - 1)}…`;
}
export default function Connections() {
    const { confirm } = useConfirm();
    const navigate = useNavigate();
    const [list, setList] = useState([]);
    const [search, setSearch] = useState("");
    const [msg, setMsg] = useState("");
    const [err, setErr] = useState("");
    const [createOpen, setCreateOpen] = useState(false);
    const [editConn, setEditConn] = useState(null);
    const load = useCallback(async () => {
        try {
            setErr("");
            const data = await api("/api/admin/connections");
            setList(data);
        }
        catch (e) {
            setErr(String(e));
        }
    }, []);
    useEffect(() => {
        void load();
    }, [load]);
    const filtered = list.filter((c) => {
        const q = search.trim().toLowerCase();
        if (!q)
            return true;
        return (c.name.toLowerCase().includes(q) ||
            c.provider_type.toLowerCase().includes(q) ||
            (c.base_url || "").toLowerCase().includes(q));
    });
    async function createConnection(values) {
        await api("/api/admin/connections?sync_now=false", {
            method: "POST",
            body: JSON.stringify({
                name: values.name,
                provider_type: values.provider_type,
                api_key: values.api_key,
                base_url: values.base_url || null,
                sync_interval_hours: values.sync_interval_hours,
            }),
        });
        setMsg(`Connection "${values.name}" added. Use Sync now to pull models.`);
        await load();
    }
    async function updateConnection(values) {
        if (!editConn)
            return;
        const body = {
            name: values.name,
            provider_type: values.provider_type,
            base_url: values.base_url || null,
            sync_interval_hours: values.sync_interval_hours,
        };
        if (values.api_key.trim())
            body.api_key = values.api_key.trim();
        await api(`/api/admin/connections/${editConn.id}`, { method: "PATCH", body: JSON.stringify(body) });
        setMsg("Connection updated.");
        await load();
    }
    async function syncNow(id) {
        try {
            const r = await api(`/api/admin/connections/${id}/sync`, { method: "POST" });
            setMsg(`Synced ${r.synced} models.`);
            window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.modelsSyncFlash));
            await load();
        }
        catch (e) {
            setErr(String(e));
        }
    }
    async function toggleConn(c) {
        await api(`/api/admin/connections/${c.id}/toggle?enabled=${!c.is_active}`, { method: "PATCH" });
        setMsg(c.is_active
            ? "Connection disabled. All its models were turned off."
            : "Connection enabled. Its models were turned on.");
        await load();
    }
    async function removeConnection(c) {
        const ok = await confirm({
            title: "Delete connection",
            message: `Delete connection "${c.name}"? Synced models for this provider will be removed. This cannot be undone.`,
            danger: true,
        });
        if (!ok)
            return;
        await api(`/api/admin/connections/${c.id}`, { method: "DELETE" });
        if (editConn?.id === c.id)
            setEditConn(null);
        setMsg(`Connection "${c.name}" deleted.`);
        await load();
    }
    return (_jsxs(AdminPage, { title: "Connections", actions: _jsx("button", { type: "button", className: "btn connections-new-btn", onClick: () => setCreateOpen(true), children: "+ New Connection" }), children: [_jsxs("p", { className: "muted-text connections-lead", children: ["Upstream provider accounts (OpenRouter, OpenAI, \u2026). Set a custom ", _jsx("strong", { children: "Base URL" }), " per connection for chat, embeddings, video, or other API paths \u2014 then sync models for that endpoint."] }), msg && _jsx("p", { className: "alert alert-success", children: msg }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsx("div", { className: "connections-toolbar card", children: _jsx("input", { type: "search", className: "input-block connections-search", placeholder: "Search name, provider, or base URL\u2026", value: search, onChange: (e) => setSearch(e.target.value) }) }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "card data-table connections-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Name" }), _jsx("th", { className: "col-sm", children: "Provider" }), _jsx("th", { className: "col-lg", children: "Base URL" }), _jsx("th", { className: "col-sm", children: "Usage" }), _jsx("th", { className: "col-lg", children: "Last sync" }), _jsx("th", { className: "col-md", children: "Schedule" }), _jsx("th", { className: "col-actions", children: "Actions" })] }) }), _jsxs("tbody", { children: [filtered.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 7, className: "muted-text", children: list.length === 0 ? "No connections yet. Add one with + New Connection." : "No matches." }) })), filtered.map((c) => (_jsxs("tr", { className: c.is_active ? "" : "connections-row--disabled", children: [_jsx("td", { children: _jsxs("div", { className: "connections-name-cell", children: [_jsx("strong", { children: c.name }), !c.is_active ? _jsx("span", { className: "connections-badge", children: "Disabled" }) : null] }) }), _jsx("td", { className: "col-sm", children: c.provider_type }), _jsx("td", { className: "col-lg", children: _jsx("code", { className: "connections-base-url", title: c.base_url || undefined, children: truncateUrl(c.base_url) }) }), _jsx("td", { className: "col-sm", children: _jsx("strong", { children: formatUsd(c.usage_usd ?? 0) }) }), _jsx("td", { className: "col-lg", children: c.last_sync_at ? formatDateTime(c.last_sync_at) : "—" }), _jsx("td", { className: "col-md", children: syncScheduleLabel(c.sync_interval_hours) }), _jsx("td", { className: "col-actions", children: _jsx(RowActionsMenu, { actions: [
                                                    { label: "Edit", onClick: () => setEditConn(c) },
                                                    {
                                                        label: USAGE_AND_ACTIVITY_LABEL,
                                                        menuWrap: true,
                                                        onClick: () => navigate(`/admin/connections/${c.id}/activity`),
                                                    },
                                                    { label: "Sync now", onClick: () => syncNow(c.id) },
                                                    { label: c.is_active ? "Disable" : "Enable", onClick: () => toggleConn(c) },
                                                    { label: "Delete", onClick: () => removeConnection(c), danger: true },
                                                ] }) })] }, c.id)))] })] }) }), _jsx(ConnectionFormModal, { open: createOpen, title: "Add connection", onClose: () => setCreateOpen(false), onSubmit: createConnection }), _jsx(ConnectionFormModal, { open: !!editConn, title: "Edit connection", initial: editConn
                    ? {
                        name: editConn.name,
                        provider_type: editConn.provider_type,
                        base_url: editConn.base_url ?? "",
                        sync_interval_hours: editConn.sync_interval_hours,
                        api_key_masked: editConn.api_key_masked,
                    }
                    : undefined, onClose: () => setEditConn(null), onSubmit: updateConnection })] }));
}
