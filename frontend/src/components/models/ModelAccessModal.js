import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import Modal from "../Modal";
export default function ModelAccessModal({ open, modelId, modelLabel, onClose, onSaved }) {
    const [accessType, setAccessType] = useState("public");
    const [users, setUsers] = useState([]);
    const [groups, setGroups] = useState([]);
    const [allGroups, setAllGroups] = useState([]);
    const [userQuery, setUserQuery] = useState("");
    const [groupQuery, setGroupQuery] = useState("");
    const [userHits, setUserHits] = useState([]);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [err, setErr] = useState("");
    useEffect(() => {
        if (!open || modelId == null)
            return;
        setErr("");
        setUserQuery("");
        setGroupQuery("");
        setUserHits([]);
        setLoading(true);
        Promise.all([
            api(`/api/admin/models/${modelId}/access`),
            api("/api/admin/groups"),
        ])
            .then(([detail, groupRows]) => {
            setAccessType(detail.access_type === "private" ? "private" : "public");
            setUsers(detail.users || []);
            setGroups(detail.groups || []);
            setAllGroups((groupRows || []).map((g) => ({
                id: g.id,
                name: g.name,
                source: g.source || "local",
            })));
        })
            .catch((e) => setErr(String(e)))
            .finally(() => setLoading(false));
    }, [open, modelId]);
    useEffect(() => {
        if (!open || accessType !== "private")
            return;
        const term = userQuery.trim();
        if (term.length < 2) {
            setUserHits([]);
            return;
        }
        const t = window.setTimeout(() => {
            const qs = new URLSearchParams({ picker: "true", q: term });
            api(`/api/admin/users?${qs}`)
                .then(setUserHits)
                .catch(() => setUserHits([]));
        }, 200);
        return () => window.clearTimeout(t);
    }, [userQuery, open, accessType]);
    const groupHits = useMemo(() => {
        const term = groupQuery.trim().toLowerCase();
        if (term.length < 1)
            return [];
        const selected = new Set(groups.map((g) => g.id));
        return allGroups
            .filter((g) => !selected.has(g.id))
            .filter((g) => {
            const name = (g.name || "").toLowerCase();
            const source = (g.source || "").toLowerCase();
            return name.includes(term) || source.includes(term);
        })
            .slice(0, 25);
    }, [allGroups, groups, groupQuery]);
    function addUser(u) {
        setUsers((prev) => (prev.some((x) => x.id === u.id) ? prev : [...prev, u]));
        setUserQuery("");
        setUserHits([]);
    }
    function removeUser(id) {
        setUsers((prev) => prev.filter((u) => u.id !== id));
    }
    function addGroup(g) {
        setGroups((prev) => (prev.some((x) => x.id === g.id) ? prev : [...prev, g]));
        setGroupQuery("");
    }
    function removeGroup(id) {
        setGroups((prev) => prev.filter((g) => g.id !== id));
    }
    async function handleSubmit(e) {
        e.preventDefault();
        if (modelId == null)
            return;
        setSaving(true);
        setErr("");
        try {
            await api(`/api/admin/models/${modelId}/access`, {
                method: "PUT",
                body: JSON.stringify({
                    access_type: accessType,
                    user_ids: accessType === "private" ? users.map((u) => u.id) : [],
                    group_ids: accessType === "private" ? groups.map((g) => g.id) : [],
                }),
            });
            await onSaved();
            onClose();
        }
        catch (ex) {
            setErr(String(ex));
        }
        finally {
            setSaving(false);
        }
    }
    return (_jsx(Modal, { open: open, title: "Model access", onClose: () => !saving && onClose(), children: _jsxs("form", { className: "model-access-form", onSubmit: handleSubmit, children: [_jsx("p", { className: "muted-text model-access-form__label", children: modelLabel }), loading ? _jsx("p", { className: "muted-text", children: "Loading\u2026" }) : null, err ? _jsx("p", { className: "alert alert-error", children: err }) : null, _jsxs("fieldset", { className: "model-access-form__type", disabled: loading || saving, children: [_jsx("legend", { children: "Access type" }), _jsxs("label", { className: "model-access-form__radio", children: [_jsx("input", { type: "radio", name: "access_type", checked: accessType === "public", onChange: () => setAccessType("public") }), _jsxs("span", { children: [_jsx("strong", { children: "Public" }), _jsx("span", { className: "muted-text", children: " \u2014 all logged-in users" })] })] }), _jsxs("label", { className: "model-access-form__radio", children: [_jsx("input", { type: "radio", name: "access_type", checked: accessType === "private", onChange: () => setAccessType("private") }), _jsxs("span", { children: [_jsx("strong", { children: "Private" }), _jsx("span", { className: "muted-text", children: " \u2014 selected users/groups only" })] })] })] }), accessType === "private" ? (_jsxs("div", { className: "model-access-form__private", children: [_jsx("p", { className: "muted-text model-access-form__hint", children: "Leave empty to allow Super Admins only." }), _jsx("label", { className: "model-access-form__section-title", children: "Users" }), _jsx("div", { className: "model-access-chips", children: users.map((u) => (_jsxs("button", { type: "button", className: "model-access-chip", onClick: () => removeUser(u.id), title: "Remove", children: [u.display_name || u.username, _jsx("span", { "aria-hidden": true, children: "\u00D7" })] }, u.id))) }), _jsx("input", { className: "input-block", placeholder: "Search users (2+ characters)\u2026", value: userQuery, onChange: (e) => setUserQuery(e.target.value), disabled: saving }), userHits.length > 0 ? (_jsx("ul", { className: "model-access-hits", children: userHits
                                .filter((u) => !users.some((x) => x.id === u.id))
                                .map((u) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => addUser(u), children: [_jsx("strong", { children: u.display_name || u.username }), _jsx("span", { className: "muted-text", children: u.email })] }) }, u.id))) })) : null, _jsx("label", { className: "model-access-form__section-title", children: "Groups" }), _jsx("div", { className: "model-access-chips", children: groups.map((g) => (_jsxs("button", { type: "button", className: "model-access-chip", onClick: () => removeGroup(g.id), title: "Remove", children: [g.name, _jsxs("span", { className: "muted-text", children: ["(", g.source, ")"] }), _jsx("span", { "aria-hidden": true, children: "\u00D7" })] }, g.id))) }), _jsx("input", { className: "input-block", placeholder: "Search groups\u2026", value: groupQuery, onChange: (e) => setGroupQuery(e.target.value), disabled: saving || loading }), groupQuery.trim() && groupHits.length === 0 ? (_jsx("p", { className: "muted-text model-access-form__empty-hits", children: "No groups found" })) : null, groupHits.length > 0 ? (_jsx("ul", { className: "model-access-hits", children: groupHits.map((g) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => addGroup(g), children: [_jsx("strong", { children: g.name }), _jsx("span", { className: "muted-text", children: g.source })] }) }, g.id))) })) : null] })) : null, _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: loading || saving, children: saving ? "…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: saving, onClick: onClose, children: "Cancel" })] })] }) }));
}
