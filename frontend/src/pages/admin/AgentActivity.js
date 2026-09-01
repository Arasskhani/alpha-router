import { jsxs as _jsxs, jsx as _jsx, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import { activityApiPath, humanActivityEventType, nextActivitySearch, parseActivityQuery, } from "../../lib/agentActivity";
import { agentStatusTone, humanAgentStatus, readableDate, } from "../../lib/agentPlatform";
function payloadText(payload, key) {
    const value = payload[key];
    return typeof value === "string" && value.trim() ? value : "";
}
export default function AgentActivity() {
    const [searchParams, setSearchParams] = useSearchParams();
    const activityQuery = useMemo(() => parseActivityQuery(searchParams), [searchParams]);
    const [items, setItems] = useState([]);
    const [holds, setHolds] = useState([]);
    const [audit, setAudit] = useState(null);
    const [query, setQuery] = useState("");
    const [holdType, setHoldType] = useState("knowledge_document");
    const [holdResourceId, setHoldResourceId] = useState("");
    const [holdReason, setHoldReason] = useState("");
    const [loading, setLoading] = useState(true);
    const [working, setWorking] = useState(false);
    const [error, setError] = useState("");
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const [activityPayload, holdPayload, auditPayload] = await Promise.all([
                api(activityApiPath(activityQuery)),
                api("/api/admin/agents/governance/holds?status=active"),
                api("/api/admin/agents/governance/audit/verify"),
            ]);
            setItems(activityPayload.items);
            setHolds(holdPayload.items);
            setAudit(auditPayload);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setLoading(false);
        }
    }, [activityQuery]);
    const createHold = async () => {
        if (!holdResourceId.trim() || holdReason.trim().length < 3)
            return;
        setWorking(true);
        setError("");
        try {
            await api("/api/admin/agents/governance/holds", {
                method: "POST",
                body: JSON.stringify({
                    resource_type: holdType,
                    resource_id: holdResourceId.trim(),
                    reason: holdReason.trim(),
                }),
            });
            setHoldResourceId("");
            setHoldReason("");
            await load();
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setWorking(false);
        }
    };
    const releaseHold = async (holdId) => {
        setWorking(true);
        setError("");
        try {
            await api(`/api/admin/agents/governance/holds/${encodeURIComponent(holdId)}/release`, {
                method: "POST",
                body: JSON.stringify({ reason: "Released from Audit" }),
            });
            await load();
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setWorking(false);
        }
    };
    const runRetention = async () => {
        setWorking(true);
        setError("");
        try {
            await api("/api/admin/agents/governance/retention/run", { method: "POST" });
            await load();
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setWorking(false);
        }
    };
    useEffect(() => {
        void load();
    }, [load]);
    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return items.filter((item) => {
            if (!needle)
                return true;
            const agentName = payloadText(item.payload, "agent_name");
            return `${item.event_type} ${item.resource_id || ""} ${item.reason || ""} ${agentName}`
                .toLowerCase()
                .includes(needle);
        });
    }, [items, query]);
    function updateActivityQuery(patch) {
        setSearchParams(nextActivitySearch(searchParams, patch), { replace: true });
    }
    return (_jsxs(AdminPage, { title: "Audit", actions: (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "btn btn-ghost", disabled: working, onClick: () => void runRetention(), children: "Run retention" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void load(), children: "Refresh" })] })), children: [_jsxs("p", { className: "agent-page-lead", children: ["Append-only lifecycle evidence and metadata-only runtime outcomes.", activityQuery.sinceHours
                        ? ` Showing the last ${activityQuery.sinceHours} hours.`
                        : ""] }), error ? _jsx("div", { className: "error", children: error }) : null, _jsxs("section", { className: "agent-governance-summary", "aria-label": "Governance status", children: [_jsxs("div", { children: [_jsx("span", { children: "Audit chain" }), _jsx("strong", { className: `agent-status ${audit?.valid ? "is-success" : "is-danger"}`, children: audit ? (audit.valid ? `Verified · ${audit.event_count} events` : "Integrity failure") : "Checking…" })] }), _jsxs("div", { children: [_jsx("span", { children: "Active legal holds" }), _jsx("strong", { children: holds.length })] })] }), _jsxs("section", { className: "agent-hold-panel", children: [_jsxs("div", { children: [_jsx("h2", { children: "Place legal hold" }), _jsx("p", { children: "Held resources are excluded from chat and Knowledge retention jobs." })] }), _jsxs("div", { className: "agent-hold-form", children: [_jsxs("select", { value: holdType, onChange: (event) => setHoldType(event.target.value), children: [_jsx("option", { value: "knowledge_document", children: "Knowledge document" }), _jsx("option", { value: "knowledge_document_version", children: "Document version" }), _jsx("option", { value: "knowledge_base", children: "Knowledge base" }), _jsx("option", { value: "chat_session", children: "Chat session" }), _jsx("option", { value: "agent_run", children: "Agent run" }), _jsx("option", { value: "agent", children: "Agent" })] }), _jsx("input", { value: holdResourceId, onChange: (event) => setHoldResourceId(event.target.value), placeholder: "Resource ID" }), _jsx("input", { value: holdReason, onChange: (event) => setHoldReason(event.target.value), placeholder: "Reason" }), _jsx("button", { type: "button", className: "btn btn-primary", disabled: working || !holdResourceId.trim() || holdReason.trim().length < 3, onClick: () => void createHold(), children: "Place hold" })] }), holds.length ? (_jsx("div", { className: "agent-hold-list", children: holds.map((hold) => (_jsxs("div", { children: [_jsxs("span", { children: [_jsx("strong", { children: humanAgentStatus(hold.resource_type) }), _jsx("code", { children: hold.resource_id }), _jsxs("small", { children: [hold.reason, " \u00B7 ", readableDate(hold.placed_at)] })] }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: working, onClick: () => void releaseHold(hold.id), children: "Release" })] }, hold.id))) })) : null] }), _jsxs("div", { className: "agent-audit-toolbar", children: [_jsx("input", { type: "search", placeholder: "Search event or resource\u2026", value: query, onChange: (e) => setQuery(e.target.value) }), _jsxs("select", { value: activityQuery.source, onChange: (e) => updateActivityQuery({ source: e.target.value }), children: [_jsx("option", { value: "all", children: "All sources" }), _jsx("option", { value: "agent", children: "Agent lifecycle" }), _jsx("option", { value: "tool", children: "Tool registry" }), _jsx("option", { value: "knowledge", children: "Knowledge lifecycle" }), _jsx("option", { value: "governance", children: "Governance" }), _jsx("option", { value: "runtime", children: "Runtime" })] }), activityQuery.source === "runtime" ? (_jsxs("select", { value: activityQuery.status, onChange: (e) => updateActivityQuery({ status: e.target.value }), children: [_jsx("option", { value: "", children: "All statuses" }), _jsx("option", { value: "blocked", children: "Blocked" }), _jsx("option", { value: "failed", children: "Failed" }), _jsx("option", { value: "succeeded", children: "Succeeded" }), _jsx("option", { value: "abstained", children: "Abstained" }), _jsx("option", { value: "cancelled", children: "Cancelled" })] })) : null, activityQuery.sinceHours ? (_jsxs("button", { type: "button", className: "btn btn-ghost", onClick: () => updateActivityQuery({ sinceHours: "" }), children: ["Last ", activityQuery.sinceHours, "h \u00B7 Clear"] })) : null] }), _jsxs("div", { className: "audit-timeline", "aria-busy": loading, children: [visible.map((item) => {
                        const terminal = item.event_type.split(".").at(-1) || item.source;
                        const agentName = payloadText(item.payload, "agent_name");
                        return (_jsxs("article", { className: "audit-event", children: [_jsx("span", { className: `audit-event__dot ${agentStatusTone(terminal)}`, "aria-hidden": true }), _jsxs("div", { className: "audit-event__body", children: [_jsxs("div", { children: [_jsx("strong", { children: humanActivityEventType(item.event_type) }), _jsx("span", { className: "agent-status is-neutral", children: humanAgentStatus(item.source) })] }), _jsxs("p", { children: [agentName || (item.resource_id ? _jsx("code", { children: item.resource_id }) : "Platform event"), item.actor_user_id ? ` · actor ${item.actor_user_id}` : "", item.reason ? ` · ${humanAgentStatus(item.reason)}` : ""] }), Object.keys(item.payload || {}).length ? (_jsxs("details", { className: "agent-inline-details", children: [_jsx("summary", { children: "Evidence" }), _jsx("pre", { children: JSON.stringify(item.payload, null, 2) })] })) : null] }), _jsx("time", { children: readableDate(item.created_at) })] }, `${item.source}-${item.id}`));
                    }), !loading && visible.length === 0 ? (_jsxs("div", { className: "agent-empty-state", children: [_jsx("h2", { children: "No activity found" }), _jsx("p", { children: "Try another source, status, or time range." })] })) : null] })] }));
}
