import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import { useConfirm } from "../../context/ConfirmContext";
import { agentStatusTone, humanAgentStatus, readableDate, } from "../../lib/agentPlatform";
function submittedByLabel(item) {
    const name = (item.submitted_by_display_name || item.submitted_by_username || "").trim();
    if (name)
        return name;
    if (item.submitted_by_user_id)
        return `User #${item.submitted_by_user_id}`;
    return "";
}
export default function AgentApprovals() {
    const { confirm, prompt } = useConfirm();
    const [items, setItems] = useState([]);
    const [filter, setFilter] = useState("all");
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState("");
    const [error, setError] = useState("");
    const [flash, setFlash] = useState("");
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const payload = await api("/api/admin/agents/approvals");
            setItems(payload.items);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setLoading(false);
        }
    }, []);
    useEffect(() => {
        void load();
    }, [load]);
    const visible = useMemo(() => filter === "all" ? items : items.filter((item) => item.kind === filter), [items, filter]);
    async function approve(item) {
        let path = "";
        let body;
        if (item.kind === "agent_version") {
            const ok = await confirm({
                title: "Publish Agent version",
                message: `Publish ${item.title}? This makes the version active for users who can access the Agent.`,
                confirmLabel: "Publish",
            });
            if (!ok)
                return;
            path = `/api/admin/agents/versions/${item.id}/publish`;
        }
        else if (item.kind === "tool_version") {
            const ok = await confirm({
                title: "Publish Tool version",
                message: `Publish ${item.title}?`,
                confirmLabel: "Publish",
            });
            if (!ok)
                return;
            path = `/api/admin/agents/tool-versions/${item.id}/publish`;
        }
        else if (item.kind === "knowledge_binding") {
            const reason = await prompt({
                title: "Approve knowledge binding",
                message: `Approve binding for ${item.title}?`,
                promptLabel: "Approval reason",
                promptDefault: "Reviewed and approved",
                confirmLabel: "Approve",
            });
            if (!reason?.trim())
                return;
            path = item.status === "pending_domain_approval"
                ? `/api/admin/agents/bindings/${item.id}/approve-domain`
                : `/api/admin/agents/bindings/${item.id}/approve-knowledge`;
            body = JSON.stringify({ reason: reason.trim() });
        }
        else {
            const reason = await prompt({
                title: "Approve document version",
                message: `Approve ${item.title} for Knowledge releases?`,
                promptLabel: "Document review reason",
                promptDefault: "Reviewed and approved",
                confirmLabel: "Approve",
            });
            if (!reason?.trim())
                return;
            path = `/api/admin/knowledge/document-versions/${item.id}/approve`;
            body = JSON.stringify({ reason: reason.trim() });
        }
        setBusyId(item.id);
        setError("");
        setFlash("");
        try {
            await api(path, { method: "POST", body });
            setFlash(`${item.title} approved.`);
            await load();
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusyId("");
        }
    }
    const filters = [
        ["all", "All"],
        ["agent_version", "Agents"],
        ["knowledge_binding", "Bindings"],
        ["document_version", "Documents"],
        ["tool_version", "Tools"],
    ];
    return (_jsxs(AdminPage, { title: "Approvals", actions: _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void load(), children: "Refresh" }), children: [_jsx("p", { className: "agent-page-lead", children: "Maker-checker queue for version publication and sensitive knowledge access. Super Admin can complete both maker and checker steps when needed." }), error ? _jsx("div", { className: "error", children: error }) : null, flash ? _jsx("div", { className: "success", children: flash }) : null, _jsx("div", { className: "agent-filter-tabs", role: "tablist", children: filters.map(([value, label]) => (_jsxs("button", { type: "button", className: filter === value ? "is-active" : "", onClick: () => setFilter(value), children: [label, _jsx("span", { children: value === "all" ? items.length : items.filter((item) => item.kind === value).length })] }, value))) }), _jsxs("div", { className: "approval-grid", "aria-busy": loading, children: [visible.map((item) => (_jsxs("article", { className: "approval-card", children: [_jsxs("div", { children: [_jsx("span", { className: "approval-card__kind", children: humanAgentStatus(item.kind) }), _jsx("h2", { children: item.title }), _jsxs("p", { children: ["Submitted ", readableDate(item.created_at), submittedByLabel(item) ? ` · ${submittedByLabel(item)}` : ""] })] }), _jsxs("div", { className: "approval-card__actions", children: [_jsx("span", { className: `agent-status ${agentStatusTone(item.status)}`, children: humanAgentStatus(item.status) }), _jsx("button", { type: "button", className: "btn", disabled: !!busyId, onClick: () => void approve(item), children: busyId === item.id ? "Approving…" : "Approve" })] })] }, `${item.kind}-${item.id}`))), !loading && visible.length === 0 ? (_jsxs("div", { className: "agent-empty-state", children: [_jsx("h2", { children: "Approval queue is clear" }), _jsx("p", { children: "No pending items match this view." })] })) : null] })] }));
}
