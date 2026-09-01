import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import { api } from "../../api";
import { roleLabel } from "../../lib/rbac";
export default function Roles() {
    const [roles, setRoles] = useState([]);
    const [users, setUsers] = useState([]);
    const [err, setErr] = useState("");
    const [flash, setFlash] = useState("");
    const [query, setQuery] = useState("");
    const [selectedRoleSlugs, setSelectedRoleSlugs] = useState([]);
    const [assignOpen, setAssignOpen] = useState(false);
    const [assignRoleSlug, setAssignRoleSlug] = useState("");
    const [assignUserIds, setAssignUserIds] = useState([]);
    const [assignUserQuery, setAssignUserQuery] = useState("");
    const [assignSaving, setAssignSaving] = useState(false);
    const selectedSlugs = useMemo(() => new Set(selectedRoleSlugs), [selectedRoleSlugs]);
    useEffect(() => {
        api("/api/admin/roles")
            .then(setRoles)
            .catch((e) => setErr(String(e)));
    }, []);
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        const list = [...roles].sort((a, b) => a.name.localeCompare(b.name));
        if (!q)
            return list;
        return list.filter((role) => role.name.toLowerCase().includes(q) ||
            role.description.toLowerCase().includes(q) ||
            role.category.toLowerCase().includes(q));
    }, [query, roles]);
    const selectedRoles = useMemo(() => roles.filter((role) => selectedSlugs.has(role.slug)), [roles, selectedSlugs]);
    const filteredAssignUsers = useMemo(() => {
        const q = assignUserQuery.trim().toLowerCase();
        if (!q)
            return users;
        return users.filter((u) => u.username.toLowerCase().includes(q) ||
            (u.display_name || "").toLowerCase().includes(q) ||
            (u.email || "").toLowerCase().includes(q));
    }, [assignUserQuery, users]);
    function toggleRole(slug) {
        setSelectedRoleSlugs((prev) => prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]);
    }
    function toggleAllVisible(checked) {
        setSelectedRoleSlugs(checked ? filtered.map((r) => r.slug) : []);
    }
    function openAssignModal() {
        if (selectedRoles.length === 0)
            return;
        setErr("");
        setFlash("");
        setAssignRoleSlug(selectedRoles[0]?.slug || "");
        setAssignUserIds([]);
        setAssignUserQuery("");
        setAssignOpen(true);
        api("/api/admin/users")
            .then(setUsers)
            .catch((e) => setErr(String(e)));
    }
    function toggleAssignUser(userId) {
        setAssignUserIds((prev) => prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]);
    }
    async function submitAssign(e) {
        e.preventDefault();
        if (!assignRoleSlug || assignUserIds.length === 0) {
            setErr("Select a role and at least one user.");
            return;
        }
        setAssignSaving(true);
        setErr("");
        try {
            await api("/api/admin/users/bulk", {
                method: "POST",
                body: JSON.stringify({ user_ids: assignUserIds, role: assignRoleSlug }),
            });
            setFlash(`Assigned ${roleLabel(roles, assignRoleSlug)} to ${assignUserIds.length} user${assignUserIds.length === 1 ? "" : "s"}.`);
            setAssignOpen(false);
            setSelectedRoleSlugs([]);
        }
        catch (e2) {
            setErr(String(e2));
        }
        finally {
            setAssignSaving(false);
        }
    }
    const allVisibleSelected = filtered.length > 0 && filtered.every((r) => selectedSlugs.has(r.slug));
    return (_jsxs(AdminPage, { title: "Roles", actions: selectedRoles.length > 0 ? (_jsxs("button", { type: "button", className: "btn", onClick: openAssignModal, children: ["Assign Roles (", selectedRoles.length, ")"] })) : null, children: [_jsxs("p", { className: "muted-text", children: ["Built-in RBAC roles define which admin sections a user can open and whether they can change settings. Select one or more roles, then use ", _jsx("strong", { children: "Assign Roles" }), " to apply them to users."] }), flash && _jsx("p", { className: "alert alert-success", children: flash }), err && !assignOpen && _jsx("p", { className: "alert alert-error", children: err }), _jsx("div", { className: "admin-toolbar roles-toolbar", children: _jsx("input", { type: "search", className: "input-block roles-toolbar__search", placeholder: "Search roles\u2026", value: query, onChange: (e) => setQuery(e.target.value) }) }), _jsx("div", { className: "table-wrap table-wrap--roles", children: _jsxs("table", { className: "card data-table roles-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { className: "roles-table__check", children: _jsx("input", { type: "checkbox", checked: allVisibleSelected, onChange: (e) => toggleAllVisible(e.target.checked), "aria-label": "Select all visible roles" }) }), _jsx("th", { children: "Name" }), _jsx("th", { children: "Description" }), _jsx("th", { children: "Category" })] }) }), _jsx("tbody", { children: filtered.map((role) => (_jsxs("tr", { className: selectedSlugs.has(role.slug) ? "row-selected" : "", children: [_jsx("td", { className: "roles-table__check", children: _jsx("input", { type: "checkbox", checked: selectedSlugs.has(role.slug), onChange: () => toggleRole(role.slug), "aria-label": `Select ${role.name}` }) }), _jsxs("td", { className: "roles-table__name", children: [_jsx("strong", { children: role.name }), role.read_only && _jsx("span", { className: "badge badge-muted", children: "Read only" })] }), _jsx("td", { className: "roles-table__desc", children: role.description }), _jsx("td", { className: "roles-table__category", children: role.category })] }, role.slug))) })] }) }), filtered.length === 0 && !err && _jsx("p", { className: "muted-text", children: "No roles match your search." }), _jsx(Modal, { open: assignOpen, title: "Assign Roles", onClose: () => setAssignOpen(false), children: _jsxs("form", { onSubmit: submitAssign, children: [err && assignOpen && _jsx("p", { className: "alert alert-error", children: err }), _jsxs("p", { className: "muted-text", children: ["Selected ", selectedRoles.length, " role", selectedRoles.length === 1 ? "" : "s", ". Choose which role to apply, then pick one or more users."] }), _jsx("label", { className: "form-label", children: "Role to assign" }), _jsx("select", { className: "input-block", value: assignRoleSlug, onChange: (e) => setAssignRoleSlug(e.target.value), required: true, children: selectedRoles.map((role) => (_jsx("option", { value: role.slug, children: role.name }, role.slug))) }), _jsx("label", { className: "form-label", style: { marginTop: "1rem" }, children: "Users" }), _jsx("input", { type: "search", className: "input-block", placeholder: "Filter users\u2026", value: assignUserQuery, onChange: (e) => setAssignUserQuery(e.target.value) }), _jsxs("div", { className: "roles-assign-users", children: [filteredAssignUsers.map((u) => (_jsxs("label", { className: "roles-assign-users__row", children: [_jsx("input", { type: "checkbox", checked: assignUserIds.includes(u.id), onChange: () => toggleAssignUser(u.id) }), _jsxs("span", { children: [_jsx("strong", { children: u.username }), u.display_name && u.display_name !== u.username ? ` (${u.display_name})` : "", u.email ? ` · ${u.email}` : "", _jsxs("span", { className: "muted-text", children: [" \u00B7 ", roleLabel(roles, u.role)] })] })] }, u.id))), filteredAssignUsers.length === 0 && _jsx("p", { className: "muted-text", children: "No users match." })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost dialog-actions-cancel", onClick: () => setAssignOpen(false), children: "Cancel" }), _jsx("button", { type: "submit", className: "btn", disabled: assignSaving || assignUserIds.length === 0, children: assignSaving ? "Assigning…" : `Assign to ${assignUserIds.length || 0} user${assignUserIds.length === 1 ? "" : "s"}` })] })] }) })] }));
}
