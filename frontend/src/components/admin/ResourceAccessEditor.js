import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
export default function ResourceAccessEditor({ title = "Access control", loadPath, savePath, disabled, onSaved, onError, }) {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [accessType, setAccessType] = useState("private");
    const [aclVersion, setAclVersion] = useState(0);
    const [grants, setGrants] = useState([]);
    const [groups, setGroups] = useState([]);
    const [roles, setRoles] = useState([]);
    const [targetType, setTargetType] = useState("group");
    const [target, setTarget] = useState("");
    const [effect, setEffect] = useState("allow");
    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        api(loadPath)
            .then((row) => {
            if (cancelled)
                return;
            setAccessType(row.access_type);
            setAclVersion(row.acl_version);
            setGrants((row.grants || []).map((grant) => ({
                target_type: grant.target_type,
                target: grant.target,
                effect: grant.effect,
            })));
        })
            .catch((err) => {
            if (!cancelled)
                onError?.(String(err));
        })
            .finally(() => {
            if (!cancelled)
                setLoading(false);
        });
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when resource path changes
    }, [loadPath]);
    useEffect(() => {
        api("/api/admin/groups")
            .then(setGroups)
            .catch(() => setGroups([]));
        api("/api/admin/roles")
            .then((rows) => setRoles(rows.map((row) => ({ slug: row.slug, name: row.name }))))
            .catch(() => setRoles([]));
    }, []);
    const grantLabels = useMemo(() => {
        const groupNames = new Map(groups.map((group) => [String(group.id), group.name]));
        const roleNames = new Map(roles.map((role) => [role.slug, role.name]));
        return grants.map((grant) => {
            if (grant.target_type === "group") {
                return groupNames.get(String(grant.target)) || `Group #${grant.target}`;
            }
            if (grant.target_type === "role") {
                return roleNames.get(String(grant.target)) || String(grant.target);
            }
            if (grant.target_type === "user")
                return `User #${grant.target}`;
            return String(grant.target);
        });
    }, [grants, groups, roles]);
    function addGrant(e) {
        e.preventDefault();
        const raw = target.trim();
        if (!raw)
            return;
        const normalizedTarget = targetType === "user" || targetType === "group" ? Number(raw) : raw;
        if ((targetType === "user" || targetType === "group")
            && (!Number.isFinite(normalizedTarget) || Number(normalizedTarget) <= 0)) {
            onError?.("User/Group target must be a positive numeric id.");
            return;
        }
        const next = {
            target_type: targetType,
            target: normalizedTarget,
            effect,
        };
        const key = `${next.target_type}:${next.target}:${next.effect}`;
        if (grants.some((grant) => `${grant.target_type}:${grant.target}:${grant.effect}` === key)) {
            return;
        }
        setGrants((current) => [...current, next]);
        setTarget("");
    }
    async function saveAccess() {
        setSaving(true);
        try {
            const saved = await api(savePath, {
                method: "PUT",
                body: JSON.stringify({
                    access_type: accessType,
                    grants,
                }),
            });
            setAccessType(saved.access_type);
            setAclVersion(saved.acl_version);
            setGrants((saved.grants || []).map((grant) => ({
                target_type: grant.target_type,
                target: grant.target,
                effect: grant.effect,
            })));
            onSaved?.(saved);
        }
        catch (err) {
            onError?.(String(err));
        }
        finally {
            setSaving(false);
        }
    }
    return (_jsxs("section", { className: "agent-section-card", children: [_jsxs("div", { className: "agent-section-card__head", children: [_jsxs("div", { children: [_jsx("h3", { children: title }), _jsxs("p", { children: ["Private resources require an allow grant. Deny always wins. ACL v", aclVersion || 0, "."] })] }), _jsx("button", { type: "button", className: "btn", disabled: disabled || loading || saving, onClick: () => void saveAccess(), children: saving ? "Saving…" : "Save access" })] }), _jsxs("label", { children: ["Visibility", _jsxs("select", { value: accessType, disabled: disabled || loading, onChange: (e) => setAccessType(e.target.value), children: [_jsx("option", { value: "private", children: "Private" }), _jsx("option", { value: "public", children: "Public" })] })] }), _jsxs("form", { className: "agent-inline-form resource-access-form", onSubmit: addGrant, children: [_jsxs("select", { value: targetType, disabled: disabled || loading, onChange: (e) => {
                            setTargetType(e.target.value);
                            setTarget("");
                        }, children: [_jsx("option", { value: "group", children: "Group" }), _jsx("option", { value: "role", children: "Role" }), _jsx("option", { value: "department", children: "Department" }), _jsx("option", { value: "user", children: "User ID" })] }), targetType === "group" && groups.length > 0 ? (_jsxs("select", { value: target, disabled: disabled || loading, onChange: (e) => setTarget(e.target.value), children: [_jsx("option", { value: "", children: "Select group\u2026" }), groups.map((group) => (_jsx("option", { value: String(group.id), children: group.name }, group.id)))] })) : null, targetType === "role" && roles.length > 0 ? (_jsxs("select", { value: target, disabled: disabled || loading, onChange: (e) => setTarget(e.target.value), children: [_jsx("option", { value: "", children: "Select role\u2026" }), roles.map((role) => (_jsx("option", { value: role.slug, children: role.name }, role.slug)))] })) : null, targetType === "user" || targetType === "department" || (targetType === "group" && groups.length === 0) || (targetType === "role" && roles.length === 0) ? (_jsx("input", { value: target, disabled: disabled || loading, placeholder: targetType === "user"
                            ? "User id"
                            : targetType === "department"
                                ? "Department name"
                                : "Target", onChange: (e) => setTarget(e.target.value) })) : null, _jsxs("select", { value: effect, disabled: disabled || loading, onChange: (e) => setEffect(e.target.value), children: [_jsx("option", { value: "allow", children: "Allow" }), _jsx("option", { value: "deny", children: "Deny" })] }), _jsx("button", { type: "submit", className: "btn btn-ghost", disabled: disabled || loading || !target.trim(), children: "Add grant" })] }), _jsxs("div", { className: "agent-chip-list", children: [grants.map((grant, index) => (_jsxs("span", { className: "agent-binding-chip", children: [_jsx("strong", { children: grant.effect }), _jsx("em", { children: grant.target_type }), grantLabels[index], _jsx("button", { type: "button", disabled: disabled || loading, onClick: () => setGrants((current) => current.filter((_, i) => i !== index)), children: "Remove" })] }, `${grant.target_type}-${grant.target}-${grant.effect}-${index}`))), !loading && grants.length === 0 ? (_jsx("p", { className: "agent-empty", children: accessType === "private"
                            ? "No grants yet — private means nobody can use this until you allow a target."
                            : "No explicit grants. Public access is open unless a deny grant matches." })) : null] })] }));
}
