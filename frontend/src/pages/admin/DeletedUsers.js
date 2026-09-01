import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
export default function DeletedUsers() {
    const navigate = useNavigate();
    const { confirm } = useConfirm();
    const [users, setUsers] = useState([]);
    const [flash, setFlash] = useState("");
    const [err, setErr] = useState("");
    const [selectedIds, setSelectedIds] = useState([]);
    const [bulkOpen, setBulkOpen] = useState(false);
    const [bulkBusy, setBulkBusy] = useState(false);
    const load = () => {
        api("/api/admin/deleted-users")
            .then(setUsers)
            .catch((e) => setErr(String(e)));
    };
    useEffect(() => {
        load();
    }, []);
    const allVisibleSelected = useMemo(() => users.length > 0 && users.every((u) => selectedIds.includes(u.id)), [users, selectedIds]);
    function toggleSelection(userId) {
        setSelectedIds((prev) => prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]);
    }
    function toggleSelectAllVisible() {
        setSelectedIds((prev) => {
            if (allVisibleSelected) {
                return prev.filter((id) => !users.some((u) => u.id === id));
            }
            const merged = new Set(prev);
            for (const u of users)
                merged.add(u.id);
            return Array.from(merged);
        });
    }
    async function permanentlyDeleteUser(u) {
        const ok1 = await confirm({
            title: "Permanently delete user",
            message: `Permanently delete "${u.username}"? All chat history, media, and account data will be removed from the server. This cannot be undone.`,
            confirmLabel: "Continue",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok1)
            return;
        const ok2 = await confirm({
            title: "Final confirmation",
            message: `You are about to permanently erase "${u.username}" from Alpharouter. Confirm permanent deletion?`,
            confirmLabel: "Permanently delete",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok2)
            return;
        setErr("");
        try {
            await api(`/api/admin/users/${u.id}/permanently-delete`, { method: "POST" });
            setFlash(`User "${u.username}" permanently deleted.`);
            setSelectedIds((prev) => prev.filter((id) => id !== u.id));
            load();
        }
        catch (e) {
            setErr(String(e));
        }
    }
    async function bulkPermanentlyDelete() {
        if (!selectedIds.length)
            return;
        const ok1 = await confirm({
            title: "Permanently delete users",
            message: `Permanently delete ${selectedIds.length} selected user(s)? All their data will be removed from the server.`,
            confirmLabel: "Continue",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok1)
            return;
        const ok2 = await confirm({
            title: "Final confirmation",
            message: `Confirm permanent deletion of ${selectedIds.length} user(s)? This cannot be undone.`,
            confirmLabel: "Permanently delete all",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok2)
            return;
        setBulkBusy(true);
        setErr("");
        try {
            const res = await api("/api/admin/deleted-users/bulk-permanently-delete", {
                method: "POST",
                body: JSON.stringify({ user_ids: selectedIds }),
            });
            setFlash(`Permanently deleted ${res.deleted ?? 0} user(s).`);
            setSelectedIds([]);
            setBulkOpen(false);
            load();
        }
        catch (e) {
            setErr(String(e));
        }
        finally {
            setBulkBusy(false);
        }
    }
    function rowActions(u) {
        return [
            {
                label: USAGE_AND_ACTIVITY_LABEL,
                menuWrap: true,
                onClick: () => navigate(`/admin/users/${u.id}/activity`),
            },
            {
                label: "User Storage",
                onClick: () => navigate(`/admin/users/${u.id}/media`),
            },
            {
                label: "Permanently Delete User",
                onClick: () => void permanentlyDeleteUser(u),
                danger: true,
            },
        ];
    }
    const prov = (p) => `badge badge-${p === "local" ? "local" : p === "ldap" ? "ldap" : p === "saml" ? "saml" : p === "oidc" ? "oidc" : "keycloak"}`;
    return (_jsxs(AdminPage, { title: "Deleted Users", children: [flash && _jsx("p", { className: "alert alert-success", children: flash }), err && _jsx("p", { className: "alert alert-error", children: err }), _jsx("p", { className: "muted-text", children: "Users removed from sync or deleted by an admin. They cannot sign in. Data is kept until permanently deleted." }), _jsx("div", { className: "search-bar", children: _jsxs("button", { className: "btn btn-ghost", type: "button", disabled: selectedIds.length === 0, onClick: () => setBulkOpen(true), children: ["Bulk Edit", selectedIds.length > 0 ? ` (${selectedIds.length})` : ""] }) }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "card data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { style: { width: 36 }, children: _jsx("input", { type: "checkbox", checked: allVisibleSelected, onChange: toggleSelectAllVisible, "aria-label": "Select all" }) }), _jsx("th", { children: "User" }), _jsx("th", { children: "Source" }), _jsx("th", { children: "Deleted" }), _jsx("th", { children: "Last login" }), _jsx("th", { className: "col-actions", children: "Actions" })] }) }), _jsx("tbody", { children: users.map((u) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("input", { type: "checkbox", checked: selectedIds.includes(u.id), onChange: () => toggleSelection(u.id), "aria-label": `Select ${u.username}` }) }), _jsxs("td", { children: [u.display_name || u.username, _jsx("br", {}), _jsxs("small", { children: [u.username, u.email ? ` · ${u.email}` : ""] })] }), _jsx("td", { children: _jsx("span", { className: prov(u.auth_provider), children: u.auth_provider }) }), _jsx("td", { children: u.deleted_at ? new Date(u.deleted_at).toLocaleString() : "—" }), _jsx("td", { children: u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—" }), _jsx("td", { className: "col-actions", children: _jsx(RowActionsMenu, { actions: rowActions(u) }) })] }, u.id))) })] }) }), _jsxs(Modal, { open: bulkOpen, title: `Bulk Edit (${selectedIds.length} users)`, onClose: () => !bulkBusy && setBulkOpen(false), children: [_jsx("p", { className: "muted-text", children: "Permanently remove selected users and all their data from the server." }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-danger", disabled: bulkBusy, onClick: () => void bulkPermanentlyDelete(), children: bulkBusy ? "…" : "Permanently Delete User" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: bulkBusy, onClick: () => setBulkOpen(false), children: "Cancel" })] })] })] }));
}
