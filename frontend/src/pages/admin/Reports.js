import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import UserOwnerSelect from "../../components/apiKeys/UserOwnerSelect";
import { api, authFetch, formatApiError } from "../../api";
const emptyParams = {
    user_id: null,
    plan_id: "",
    department: "",
    office: "",
    group_id: "",
    alpha_router_api_key_id: "",
    agent_id: "",
    project_id: "",
    app: "",
    model_id: "",
    provider: "",
    top_n: 10,
    threshold_pct: 80,
    latency_ms: 10000,
    inactive_days: 30,
    auth_provider: "",
    group_by: "model",
};
function isoDate(d) {
    return d.toISOString().slice(0, 10);
}
const DATE_PRESETS = [
    { value: "7", label: "Last 7 days", days: 7 },
    { value: "14", label: "Last 14 days", days: 14 },
    { value: "30", label: "Last 30 days", days: 30 },
    { value: "60", label: "Last 60 days", days: 60 },
    { value: "90", label: "Last 90 days", days: 90 },
    { value: "custom", label: "Custom range", days: null },
];
function applyPresetDays(days) {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - days);
    return { start: isoDate(start), end: isoDate(end) };
}
function applyPreset(preset) {
    const entry = DATE_PRESETS.find((p) => p.value === preset);
    if (entry?.days)
        return applyPresetDays(entry.days);
    return applyPresetDays(30);
}
function presetLabel(preset) {
    return DATE_PRESETS.find((p) => p.value === preset)?.label ?? "Custom range";
}
export default function Reports() {
    const [catalog, setCatalog] = useState([]);
    const [categories, setCategories] = useState({});
    const [options, setOptions] = useState(null);
    const [search, setSearch] = useState("");
    const [selectedId, setSelectedId] = useState(null);
    const [params, setParams] = useState(emptyParams);
    const [start, setStart] = useState("");
    const [end, setEnd] = useState("");
    const [datePreset, setDatePreset] = useState("30");
    const [format, setFormat] = useState("csv");
    const [preview, setPreview] = useState(null);
    const [err, setErr] = useState("");
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        void api("/api/admin/reports/catalog").then((data) => {
            setCatalog(data.reports);
            setCategories(data.categories);
            const d = applyPreset("30");
            setStart(d.start);
            setEnd(d.end);
        });
        void api("/api/admin/reports/options").then(setOptions).catch(() => { });
    }, []);
    const selected = useMemo(() => catalog.find((r) => r.id === selectedId) ?? null, [catalog, selectedId]);
    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q)
            return catalog;
        return catalog.filter((r) => r.title.toLowerCase().includes(q) ||
            r.description.toLowerCase().includes(q) ||
            r.id.toLowerCase().includes(q));
    }, [catalog, search]);
    const grouped = useMemo(() => {
        const map = new Map();
        for (const r of filtered) {
            const list = map.get(r.category) ?? [];
            list.push(r);
            map.set(r.category, list);
        }
        return map;
    }, [filtered]);
    function buildBody() {
        if (!selected)
            return {};
        const body = {
            report_type: selected.id,
            format,
        };
        if (selected.needs_date || selected.id === "users_no_recent_login") {
            body.start_date = start;
            body.end_date = end;
        }
        if (params.user_id)
            body.user_id = params.user_id;
        if (params.plan_id)
            body.plan_id = Number(params.plan_id);
        if (params.department)
            body.department = params.department;
        if (params.office)
            body.office = params.office;
        if (params.group_id)
            body.group_id = Number(params.group_id);
        if (params.alpha_router_api_key_id) {
            body.alpha_router_api_key_id = Number(params.alpha_router_api_key_id);
        }
        if (params.agent_id)
            body.agent_id = params.agent_id;
        if (params.project_id)
            body.project_id = params.project_id;
        if (params.app)
            body.app = params.app;
        if (params.model_id)
            body.model_id = params.model_id;
        if (params.provider)
            body.provider = params.provider;
        if (params.auth_provider)
            body.auth_provider = params.auth_provider;
        body.top_n = params.top_n;
        body.threshold_pct = params.threshold_pct;
        body.latency_ms = params.latency_ms;
        body.inactive_days = params.inactive_days;
        body.group_by = params.group_by;
        return body;
    }
    function selectReport(id) {
        setSelectedId(id);
        setParams(emptyParams);
        setPreview(null);
        setErr("");
    }
    function onPresetChange(preset) {
        setDatePreset(preset);
        if (preset !== "custom") {
            const d = applyPreset(preset);
            setStart(d.start);
            setEnd(d.end);
        }
    }
    async function runPreview(e) {
        e.preventDefault();
        if (!selected)
            return;
        setBusy(true);
        setErr("");
        try {
            const data = await api("/api/admin/reports/preview", {
                method: "POST",
                body: JSON.stringify(buildBody()),
            });
            setPreview(data);
        }
        catch (ex) {
            setErr(formatApiError(ex));
            setPreview(null);
        }
        finally {
            setBusy(false);
        }
    }
    async function runExport() {
        if (!selected)
            return;
        setBusy(true);
        setErr("");
        try {
            const res = await authFetch("/api/admin/reports/export", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(buildBody()),
            });
            if (!res.ok)
                throw new Error(await res.text());
            const blob = await res.blob();
            const ext = format === "xls" ? "xlsx" : format;
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `${selected.id}.${ext}`;
            a.click();
        }
        catch (ex) {
            setErr(formatApiError(ex));
        }
        finally {
            setBusy(false);
        }
    }
    function renderParam(name) {
        if (!options)
            return null;
        switch (name) {
            case "user":
                return (_jsxs("div", { children: [_jsx("label", { children: "User (optional)" }), _jsx(UserOwnerSelect, { value: params.user_id, onChange: (u) => setParams((p) => ({ ...p, user_id: u?.id ?? null })) })] }, name));
            case "plan":
                return (_jsxs("div", { children: [_jsxs("label", { children: ["Plan", selected?.id === "plan_usage" ? " *" : " (optional)"] }), _jsxs("select", { className: "input-block", value: params.plan_id, onChange: (e) => setParams((p) => ({ ...p, plan_id: e.target.value })), required: selected?.id === "plan_usage", children: [selected?.id !== "plan_usage" && _jsx("option", { value: "", children: "All plans" }), selected?.id === "plan_usage" && _jsx("option", { value: "", children: "Select plan\u2026" }), options.plans.map((p) => (_jsx("option", { value: String(p.id), children: p.name }, p.id)))] })] }, name));
            case "department":
                return (_jsxs("div", { children: [_jsx("label", { children: "Department" }), _jsxs("select", { className: "input-block", value: params.department, onChange: (e) => setParams((p) => ({ ...p, department: e.target.value })), children: [_jsx("option", { value: "", children: "Select department\u2026" }), options.departments.map((d) => (_jsx("option", { value: d, children: d }, d)))] })] }, name));
            case "office":
                return (_jsxs("div", { children: [_jsx("label", { children: "Office (optional)" }), _jsxs("select", { className: "input-block", value: params.office, onChange: (e) => setParams((p) => ({ ...p, office: e.target.value })), children: [_jsx("option", { value: "", children: "All offices" }), options.offices.map((o) => (_jsx("option", { value: o, children: o }, o)))] })] }, name));
            case "group":
                return (_jsxs("div", { children: [_jsx("label", { children: "Group" }), _jsxs("select", { className: "input-block", value: params.group_id, onChange: (e) => setParams((p) => ({ ...p, group_id: e.target.value })), children: [_jsx("option", { value: "", children: "Select group\u2026" }), options.groups.map((g) => (_jsxs("option", { value: String(g.id), children: [g.name, " (", g.source, ")"] }, g.id)))] })] }, name));
            case "alpha_router_api_key":
                return (_jsxs("div", { children: [_jsx("label", { children: "API key (optional)" }), _jsxs("select", { className: "input-block", value: params.alpha_router_api_key_id, onChange: (e) => setParams((p) => ({ ...p, alpha_router_api_key_id: e.target.value })), children: [_jsx("option", { value: "", children: "All keys" }), options.alpha_router_api_keys.map((k) => (_jsx("option", { value: String(k.id), children: k.name }, k.id)))] })] }, name));
            case "agent":
                return (_jsxs("div", { children: [_jsx("label", { children: "Agent (optional)" }), _jsxs("select", { className: "input-block", value: params.agent_id, onChange: (e) => setParams((p) => ({ ...p, agent_id: e.target.value })), children: [_jsx("option", { value: "", children: "All Agents" }), (options.agents ?? []).map((agent) => (_jsx("option", { value: agent.id, children: agent.name }, agent.id)))] })] }, name));
            case "project":
                return (_jsxs("div", { children: [_jsx("label", { children: "Project *" }), _jsxs("select", { className: "input-block", value: params.project_id, onChange: (e) => setParams((p) => ({ ...p, project_id: e.target.value })), required: true, children: [_jsx("option", { value: "", children: "Select project\u2026" }), (options.projects ?? []).map((project) => (_jsx("option", { value: project.id, children: project.name }, project.id)))] })] }, name));
            case "app":
                return (_jsxs("div", { children: [_jsx("label", { children: "Application (optional)" }), _jsxs("select", { className: "input-block", value: params.app, onChange: (e) => setParams((p) => ({ ...p, app: e.target.value })), children: [_jsx("option", { value: "", children: "All apps" }), options.apps.map((a) => (_jsx("option", { value: a, children: a }, a)))] })] }, name));
            case "model":
                return (_jsxs("div", { children: [_jsx("label", { children: "Model (optional)" }), _jsxs("select", { className: "input-block", value: params.model_id, onChange: (e) => setParams((p) => ({ ...p, model_id: e.target.value })), children: [_jsx("option", { value: "", children: "All models" }), options.models.map((m) => (_jsx("option", { value: m, children: m }, m)))] })] }, name));
            case "provider":
                return (_jsxs("div", { children: [_jsx("label", { children: "Provider (optional)" }), _jsxs("select", { className: "input-block", value: params.provider, onChange: (e) => setParams((p) => ({ ...p, provider: e.target.value })), children: [_jsx("option", { value: "", children: "All providers" }), options.providers.map((p) => (_jsx("option", { value: p, children: p }, p)))] })] }, name));
            case "top_n":
                return (_jsxs("div", { children: [_jsx("label", { children: "Top N" }), _jsx("input", { type: "number", min: 1, max: 100, className: "input-block", value: params.top_n, onChange: (e) => setParams((p) => ({ ...p, top_n: Number(e.target.value) })) })] }, name));
            case "threshold_pct":
                return (_jsxs("div", { children: [_jsx("label", { children: "Threshold (%)" }), _jsx("input", { type: "number", min: 1, max: 100, className: "input-block", value: params.threshold_pct, onChange: (e) => setParams((p) => ({ ...p, threshold_pct: Number(e.target.value) })) })] }, name));
            case "latency_ms":
                return (_jsxs("div", { children: [_jsx("label", { children: "Slow threshold (ms)" }), _jsx("input", { type: "number", min: 1, className: "input-block", value: params.latency_ms, onChange: (e) => setParams((p) => ({ ...p, latency_ms: Number(e.target.value) })) })] }, name));
            case "inactive_days":
                return (_jsxs("div", { children: [_jsx("label", { children: "Inactive days" }), _jsx("input", { type: "number", min: 1, max: 365, className: "input-block", value: params.inactive_days, onChange: (e) => setParams((p) => ({ ...p, inactive_days: Number(e.target.value) })) })] }, name));
            case "auth_provider":
                return (_jsxs("div", { children: [_jsx("label", { children: "Auth provider (optional)" }), _jsxs("select", { className: "input-block", value: params.auth_provider, onChange: (e) => setParams((p) => ({ ...p, auth_provider: e.target.value })), children: [_jsx("option", { value: "", children: "All" }), options.auth_providers.map((a) => (_jsx("option", { value: a, children: a }, a)))] })] }, name));
            case "group_by":
                return (_jsxs("div", { children: [_jsx("label", { children: "Group by" }), _jsx("select", { className: "input-block", value: params.group_by, onChange: (e) => setParams((p) => ({ ...p, group_by: e.target.value })), children: options.group_by_options.map((o) => (_jsx("option", { value: o.value, children: o.label }, o.value))) })] }, name));
            default:
                return null;
        }
    }
    return (_jsxs(AdminPage, { title: "Reports", children: [err && _jsx("p", { className: "alert alert-error", children: err }), _jsx("div", { className: "search-bar", children: _jsx("input", { placeholder: "Search reports\u2026", value: search, onChange: (e) => setSearch(e.target.value) }) }), _jsxs("div", { className: "reports-layout", children: [_jsx("div", { className: "reports-catalog card", children: Array.from(grouped.entries()).map(([cat, items]) => (_jsxs("section", { className: "reports-catalog__section", children: [_jsx("h3", { className: "reports-catalog__heading", children: categories[cat] ?? cat }), _jsx("ul", { className: "reports-catalog__list", children: items.map((r) => (_jsx("li", { children: _jsxs("button", { type: "button", className: `reports-catalog__item${selectedId === r.id ? " reports-catalog__item--active" : ""}`, onClick: () => selectReport(r.id), children: [_jsx("strong", { children: r.title }), _jsx("span", { className: "muted-text", children: r.description })] }) }, r.id))) })] }, cat))) }), _jsxs("div", { className: "reports-runner card", children: [!selected ? (_jsx("p", { className: "muted-text", children: "Select a report from the catalog." })) : (_jsxs("form", { onSubmit: runPreview, children: [_jsx("h3", { style: { marginTop: 0 }, children: selected.title }), _jsx("p", { className: "muted-text", children: selected.description }), selected.needs_date ? (_jsxs(_Fragment, { children: [_jsx("label", { children: "Period preset" }), _jsx("select", { className: "input-block", value: datePreset, onChange: (e) => onPresetChange(e.target.value), children: DATE_PRESETS.map((p) => (_jsx("option", { value: p.value, children: p.label }, p.value))) }), datePreset !== "custom" && start && end ? (_jsxs("p", { className: "muted-text reports-runner__period", children: ["Period: ", start, " \u2192 ", end, " (", presetLabel(datePreset), ")"] })) : null, datePreset === "custom" ? (_jsxs(_Fragment, { children: [_jsx("label", { children: "Start date" }), _jsx("input", { type: "date", className: "input-block", value: start, onChange: (e) => setStart(e.target.value) }), _jsx("label", { children: "End date" }), _jsx("input", { type: "date", className: "input-block", value: end, onChange: (e) => setEnd(e.target.value) })] })) : null] })) : (_jsx("p", { className: "muted-text reports-runner__snapshot", children: "Snapshot report \u2014 date range does not apply." })), selected.params.map((p) => renderParam(p)), _jsx("label", { children: "Export format" }), _jsxs("select", { className: "input-block", value: format, onChange: (e) => setFormat(e.target.value), children: [_jsx("option", { value: "csv", children: "CSV" }), _jsx("option", { value: "xls", children: "Excel" }), _jsx("option", { value: "pdf", children: "PDF" })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: busy, children: busy ? "Loading…" : "Preview" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => void runExport(), children: "Download" })] })] })), preview && (_jsxs("div", { className: "reports-preview", children: [_jsxs("h4", { children: ["Preview (", preview.row_count, " rows)"] }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsx("tr", { children: preview.columns.map((c) => _jsx("th", { children: c }, c)) }) }), _jsx("tbody", { children: preview.rows.slice(0, 200).map((row, i) => (_jsx("tr", { children: preview.columns.map((c) => (_jsx("td", { children: String(row[c] ?? "") }, c))) }, i))) })] }) }), preview.row_count > 200 && (_jsx("p", { className: "muted-text", children: "Showing first 200 rows in preview." }))] }))] })] })] }));
}
