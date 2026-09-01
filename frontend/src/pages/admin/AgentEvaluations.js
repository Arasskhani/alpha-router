import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import { agentStatusTone, humanAgentStatus, readableDate, } from "../../lib/agentPlatform";
export default function AgentEvaluations() {
    const [items, setItems] = useState([]);
    const [datasets, setDatasets] = useState([]);
    const [runs, setRuns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [working, setWorking] = useState(false);
    const [error, setError] = useState("");
    const [filter, setFilter] = useState("all");
    const [view, setView] = useState("readiness");
    const [showCreate, setShowCreate] = useState(false);
    const [agentId, setAgentId] = useState("");
    const [datasetName, setDatasetName] = useState("");
    const [datasetSlug, setDatasetSlug] = useState("");
    const [minimumCases, setMinimumCases] = useState(100);
    const [requireReview, setRequireReview] = useState(false);
    const [caseImports, setCaseImports] = useState({});
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const [readiness, datasetPayload, runPayload] = await Promise.all([
                api("/api/admin/agents/evaluations"),
                api("/api/admin/agents/evaluations/datasets"),
                api("/api/admin/agents/evaluations/runs"),
            ]);
            setItems(readiness.items);
            setDatasets(datasetPayload.items);
            setRuns(runPayload.items);
            if (!agentId && readiness.items.length)
                setAgentId(readiness.items[0].agent_id);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setLoading(false);
        }
    }, [agentId]);
    useEffect(() => {
        void load();
    }, [load]);
    const visible = useMemo(() => items.filter((item) => filter === "all" || (filter === "ready" ? item.ready : !item.ready)), [items, filter]);
    const agents = useMemo(() => {
        const unique = new Map();
        items.forEach((item) => unique.set(item.agent_id, item.agent_name));
        return [...unique.entries()];
    }, [items]);
    const createDataset = async () => {
        if (!agentId || !datasetName.trim() || !datasetSlug.trim())
            return;
        setWorking(true);
        setError("");
        try {
            await api("/api/admin/agents/evaluations/datasets", {
                method: "POST",
                body: JSON.stringify({
                    agent_id: agentId,
                    name: datasetName.trim(),
                    slug: datasetSlug.trim(),
                    minimum_case_count: minimumCases,
                    is_publish_gate: true,
                    thresholds: { require_human_review: requireReview },
                }),
            });
            setDatasetName("");
            setDatasetSlug("");
            setShowCreate(false);
            setView("datasets");
            await load();
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setWorking(false);
        }
    };
    const importCases = async (datasetId) => {
        setWorking(true);
        setError("");
        try {
            const cases = JSON.parse(caseImports[datasetId] || "[]");
            if (!Array.isArray(cases))
                throw new Error("Cases JSON must be an array.");
            await api(`/api/admin/agents/evaluations/datasets/${encodeURIComponent(datasetId)}/cases`, {
                method: "PUT",
                body: JSON.stringify({ cases }),
            });
            setCaseImports((current) => ({ ...current, [datasetId]: "" }));
            await load();
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setWorking(false);
        }
    };
    const activateDataset = async (datasetId) => {
        setWorking(true);
        setError("");
        try {
            await api(`/api/admin/agents/evaluations/datasets/${encodeURIComponent(datasetId)}/activate`, {
                method: "POST",
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
    const reviewRun = async (runId, approved) => {
        setWorking(true);
        setError("");
        try {
            await api(`/api/admin/agents/evaluations/runs/${encodeURIComponent(runId)}/review`, {
                method: "POST",
                body: JSON.stringify({
                    approved,
                    notes: approved ? "Approved from Agent Evaluations" : "Rejected from Agent Evaluations",
                }),
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
    return (_jsxs(AdminPage, { title: "Agent Evaluations", actions: (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "btn btn-primary", onClick: () => setShowCreate((value) => !value), children: "New dataset" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void load(), children: "Refresh" })] })), children: [_jsx("p", { className: "agent-page-lead", children: "Versioned bilingual golden sets, deterministic scorecards, independent review, and fail-closed publish gates." }), error ? _jsx("div", { className: "error", children: error }) : null, showCreate ? (_jsxs("section", { className: "agent-hold-panel", children: [_jsxs("div", { children: [_jsx("h2", { children: "Create publish-gate dataset" }), _jsx("p", { children: "Active gates require Persian and English cases across routing, retrieval, citation, abstention, ACL, and injection." })] }), _jsxs("div", { className: "agent-hold-form", children: [_jsx("select", { value: agentId, onChange: (event) => setAgentId(event.target.value), children: agents.map(([id, name]) => _jsx("option", { value: id, children: name }, id)) }), _jsx("input", { value: datasetName, onChange: (event) => setDatasetName(event.target.value), placeholder: "Dataset name" }), _jsx("input", { value: datasetSlug, onChange: (event) => setDatasetSlug(event.target.value), placeholder: "dataset-slug" }), _jsx("input", { type: "number", min: 1, max: 10000, value: minimumCases, onChange: (event) => setMinimumCases(Number(event.target.value) || 1) }), _jsxs("label", { className: "agent-evaluation-checkbox", children: [_jsx("input", { type: "checkbox", checked: requireReview, onChange: (event) => setRequireReview(event.target.checked) }), "Require independent human review"] }), _jsx("button", { type: "button", className: "btn btn-primary", disabled: working, onClick: () => void createDataset(), children: "Create draft" })] })] })) : null, _jsx("div", { className: "agent-filter-tabs", role: "tablist", children: ["readiness", "datasets", "runs"].map((value) => (_jsxs("button", { type: "button", className: view === value ? "is-active" : "", onClick: () => setView(value), children: [humanAgentStatus(value), _jsx("span", { children: value === "readiness" ? items.length : value === "datasets" ? datasets.length : runs.length })] }, value))) }), view === "readiness" ? (_jsxs(_Fragment, { children: [_jsx("div", { className: "agent-filter-tabs", role: "tablist", children: ["all", "ready", "attention"].map((value) => (_jsxs("button", { type: "button", className: filter === value ? "is-active" : "", onClick: () => setFilter(value), children: [humanAgentStatus(value), _jsx("span", { children: value === "all"
                                        ? items.length
                                        : items.filter((item) => value === "ready" ? item.ready : !item.ready).length })] }, value))) }), _jsx("div", { className: "table-wrap", "aria-busy": loading, children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Agent version" }), _jsx("th", { children: "Lifecycle" }), _jsx("th", { children: "Policy check" }), _jsx("th", { children: "Runs" }), _jsx("th", { children: "Success" }), _jsx("th", { children: "Details" })] }) }), _jsxs("tbody", { children: [visible.map((item) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: item.agent_name }), _jsxs("small", { className: "agent-table-sub", children: ["v", item.version_number] })] }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(item.status)}`, children: humanAgentStatus(item.status) }) }), _jsx("td", { children: _jsx("span", { className: `agent-status ${item.ready ? "is-success" : "is-danger"}`, children: item.ready ? "Ready" : `${item.validation_errors.length} issue${item.validation_errors.length === 1 ? "" : "s"}` }) }), _jsx("td", { children: item.run_count }), _jsx("td", { children: item.success_rate == null ? "No data" : `${item.success_rate}%` }), _jsx("td", { children: item.validation_errors.length ? (_jsxs("details", { className: "agent-inline-details", children: [_jsx("summary", { children: "Validation" }), _jsx("ul", { children: item.validation_errors.map((message) => _jsx("li", { children: message }, message)) })] })) : (_jsx(Link, { to: "/admin/agents/studio", className: "agent-inline-link", children: "Open Studio" })) })] }, item.agent_version_id))), !loading && visible.length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 6, children: "No evaluation rows match this view." }) }) : null] })] }) })] })) : null, view === "datasets" ? (_jsx("div", { className: "table-wrap", "aria-busy": loading, children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Dataset" }), _jsx("th", { children: "Agent" }), _jsx("th", { children: "Lifecycle" }), _jsx("th", { children: "Cases" }), _jsx("th", { children: "Gate" }), _jsx("th", { children: "Actions" })] }) }), _jsxs("tbody", { children: [datasets.map((dataset) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: dataset.name }), _jsxs("small", { className: "agent-table-sub", children: [dataset.slug, " \u00B7 v", dataset.version_number] })] }), _jsx("td", { children: dataset.agent_name }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(dataset.status)}`, children: humanAgentStatus(dataset.status) }) }), _jsxs("td", { children: [dataset.case_count, " / ", dataset.minimum_case_count] }), _jsx("td", { children: dataset.is_publish_gate ? "Required" : "Advisory" }), _jsx("td", { children: dataset.status === "draft" ? (_jsxs("details", { className: "agent-inline-details agent-evaluation-import", children: [_jsx("summary", { children: "Import cases" }), _jsx("textarea", { value: caseImports[dataset.id] || "", onChange: (event) => setCaseImports((current) => ({ ...current, [dataset.id]: event.target.value })), placeholder: '[{"case_key":"...","category":"routing","language":"fa","prompt":"...","expected":{...}}]', rows: 7 }), _jsxs("div", { children: [_jsx("button", { type: "button", className: "btn btn-ghost", disabled: working, onClick: () => void importCases(dataset.id), children: "Replace cases" }), _jsx("button", { type: "button", className: "btn btn-primary", disabled: working || dataset.case_count < dataset.minimum_case_count, onClick: () => void activateDataset(dataset.id), children: "Activate gate" })] })] })) : (_jsx("small", { children: dataset.activated_at ? readableDate(dataset.activated_at) : "—" })) })] }, dataset.id))), !loading && datasets.length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 6, children: "No evaluation datasets exist yet." }) }) : null] })] }) })) : null, view === "runs" ? (_jsx("div", { className: "table-wrap", "aria-busy": loading, children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Run" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Cases" }), _jsx("th", { children: "Recall@10" }), _jsx("th", { children: "Routing" }), _jsx("th", { children: "Abstention" }), _jsx("th", { children: "ACL leaks" }), _jsx("th", { children: "Review" })] }) }), _jsxs("tbody", { children: [runs.map((run) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("code", { children: run.id.slice(0, 8) }), _jsxs("small", { className: "agent-table-sub", children: [humanAgentStatus(run.trigger_type), " \u00B7 ", readableDate(run.created_at)] })] }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(run.status)}`, children: humanAgentStatus(run.status) }) }), _jsxs("td", { children: [run.passed_case_count, "/", run.case_count, _jsxs("small", { className: "agent-table-sub", children: [run.failed_case_count, " failed"] })] }), _jsx("td", { children: run.metrics.retrieval_recall_at_10 == null ? "—" : `${Math.round(run.metrics.retrieval_recall_at_10 * 100)}%` }), _jsx("td", { children: run.metrics.routing_accuracy == null ? "—" : `${Math.round(run.metrics.routing_accuracy * 100)}%` }), _jsx("td", { children: run.metrics.abstention_rate == null ? "—" : `${Math.round(run.metrics.abstention_rate * 100)}%` }), _jsx("td", { children: run.metrics.acl_leak_count ?? "—" }), _jsx("td", { children: run.status === "awaiting_review" ? (_jsxs("span", { className: "agent-evaluation-review-actions", children: [_jsx("button", { type: "button", className: "btn btn-primary", disabled: working, onClick: () => void reviewRun(run.id, true), children: "Approve" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: working, onClick: () => void reviewRun(run.id, false), children: "Reject" })] })) : humanAgentStatus(run.review_status) })] }, run.id))), !loading && runs.length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 8, children: "No evaluation runs have been submitted." }) }) : null] })] }) })) : null] }));
}
