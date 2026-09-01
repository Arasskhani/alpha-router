import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import { formatRequests, formatSpend, formatTokens } from "../../components/activity/formatters";
import { runtimeHealthHref } from "../../lib/agentActivity";
const emptyOverview = {
    agents: { total: 0, active: 0, draft: 0, in_review: 0 },
    knowledge: { bases: 0, documents: 0, review: 0, failed_jobs: 0 },
    tools: { total: 0, active: 0, in_review: 0 },
    runs_24h: { total: 0, succeeded: 0, blocked: 0, failed: 0 },
    spend_24h: { cost_usd: 0, tokens: 0, turns: 0, billed_turns: 0, top_agents: [] },
    pending_approvals: 0,
};
export default function AgentsOverview() {
    const [data, setData] = useState(emptyOverview);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            setData(await api("/api/admin/agents/overview"));
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
    const successRate = data.runs_24h.total
        ? Math.round((data.runs_24h.succeeded / data.runs_24h.total) * 100)
        : 0;
    return (_jsxs(AdminPage, { title: "Agents & Knowledge", actions: _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void load(), children: "Refresh" }), children: [_jsx("p", { className: "agent-page-lead", children: "Govern specialist Agents, approved knowledge, tool contracts, and runtime evidence." }), error ? _jsx("div", { className: "error", children: error }) : null, _jsxs("div", { className: "agent-kpi-grid", "aria-busy": loading, children: [_jsxs(Link, { className: "agent-kpi-card", to: "/admin/agents/studio", children: [_jsx("span", { children: "Agents" }), _jsx("strong", { children: data.agents.active }), _jsxs("small", { children: [data.agents.total, " total \u00B7 ", data.agents.in_review, " awaiting review"] })] }), _jsxs(Link, { className: "agent-kpi-card", to: "/admin/knowledge", children: [_jsx("span", { children: "Knowledge" }), _jsx("strong", { children: data.knowledge.documents }), _jsxs("small", { children: [data.knowledge.bases, " bases \u00B7 ", data.knowledge.failed_jobs, " failed jobs"] })] }), _jsxs(Link, { className: "agent-kpi-card", to: "/admin/agent-tools", children: [_jsx("span", { children: "Tools" }), _jsx("strong", { children: data.tools.active }), _jsxs("small", { children: [data.tools.total, " registered \u00B7 ", data.tools.in_review, " awaiting review"] })] }), _jsxs(Link, { className: "agent-kpi-card", to: "/admin/agent-approvals", children: [_jsx("span", { children: "Approvals" }), _jsx("strong", { children: data.pending_approvals }), _jsx("small", { children: "Agent, knowledge, binding, and tool decisions" })] })] }), _jsxs("section", { className: "agent-section-card", children: [_jsxs("div", { className: "agent-section-card__head", children: [_jsxs("div", { children: [_jsx("h2", { children: "Runtime health \u00B7 last 24 hours" }), _jsx("p", { children: "Metadata-only Agent turn outcomes; prompts and provider output are excluded." })] }), _jsx(Link, { className: "btn btn-ghost", to: "/admin/agent-activity", children: "View audit" })] }), _jsxs("div", { className: "agent-runtime-summary", children: [_jsxs(Link, { to: runtimeHealthHref(), children: [_jsx("strong", { children: data.runs_24h.total }), _jsx("span", { children: "Turns" })] }), _jsxs("div", { children: [_jsxs("strong", { children: [successRate, "%"] }), _jsx("span", { children: "Success rate" })] }), _jsxs(Link, { to: runtimeHealthHref("blocked"), children: [_jsx("strong", { children: data.runs_24h.blocked }), _jsx("span", { children: "Guardrail blocked" })] }), _jsxs(Link, { to: runtimeHealthHref("failed"), children: [_jsx("strong", { children: data.runs_24h.failed }), _jsx("span", { children: "Failed" })] })] })] }), _jsxs("div", { className: "agent-quick-grid", children: [_jsxs(Link, { to: "/admin/agents/studio", className: "agent-quick-card", children: [_jsx("strong", { children: "Build an Agent" }), _jsx("span", { children: "Create a draft, bind policies and knowledge, then submit it for review." })] }), _jsxs(Link, { to: "/admin/knowledge", className: "agent-quick-card", children: [_jsx("strong", { children: "Curate knowledge" }), _jsx("span", { children: "Upload governed documents, monitor ingestion, and publish immutable releases." })] }), _jsxs(Link, { to: "/admin/agent-evaluations", className: "agent-quick-card", children: [_jsx("strong", { children: "Check readiness" }), _jsx("span", { children: "Validate policy completeness and inspect production success signals." })] })] }), _jsxs("section", { className: "agent-section-card", children: [_jsx("div", { className: "agent-section-card__head", children: _jsxs("div", { children: [_jsx("h2", { children: "Agent spend \u00B7 last 24 hours" }), _jsx("p", { children: "Chat-turn cost attributed to Agents. Knowledge ingest and embedding jobs are excluded." })] }) }), _jsxs("div", { className: "agent-spend-strip", children: [_jsxs("div", { className: "agent-runtime-summary agent-runtime-summary--3", children: [_jsxs("div", { children: [_jsx("strong", { children: formatSpend(data.spend_24h.cost_usd) }), _jsx("span", { children: "Total spend" })] }), _jsxs("div", { children: [_jsx("strong", { children: formatRequests(data.spend_24h.billed_turns) }), _jsx("span", { children: "Billed turns" })] }), _jsxs("div", { children: [_jsx("strong", { children: formatTokens(data.spend_24h.tokens) }), _jsx("span", { children: "Token volume" })] })] }), _jsxs("div", { className: "agent-spend-leaders", children: [_jsx("p", { children: "Top Agents" }), data.spend_24h.top_agents.length ? (_jsx("ol", { children: data.spend_24h.top_agents.map((agent) => (_jsx("li", { children: _jsxs(Link, { to: `/admin/agents/${encodeURIComponent(agent.id)}/activity`, children: [_jsx("strong", { children: agent.name }), _jsxs("span", { children: [formatSpend(agent.cost_usd), " \u00B7 ", formatRequests(agent.turns), " turns"] })] }) }, agent.id))) })) : (_jsx("p", { className: "agent-spend-leaders__empty", children: "No Agent-attributed spend in this window." }))] })] })] })] }));
}
