import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AdminPage from "../../components/AdminPage";
import { api, formatApiError } from "../../api";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
const PERIODS = [
    { value: "day", label: "Last 24 hours" },
    { value: "week", label: "Last 7 days" },
    { value: "month", label: "Last 30 days" },
];
function formatUsd(n) {
    return `$${n.toFixed(2)}`;
}
export default function ProjectUsage() {
    const navigate = useNavigate();
    const [period, setPeriod] = useState("month");
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    useEffect(() => {
        let active = true;
        setLoading(true);
        setError("");
        api(`/api/admin/project-usage?period=${encodeURIComponent(period)}`)
            .then((data) => {
            if (active)
                setRows(data.projects ?? []);
        })
            .catch((err) => {
            if (active)
                setError(formatApiError(err));
        })
            .finally(() => {
            if (active)
                setLoading(false);
        });
        return () => {
            active = false;
        };
    }, [period]);
    return (_jsxs(AdminPage, { title: "Projects", actions: _jsxs("label", { className: "form-field form-field--inline", children: [_jsx("span", { children: "Period" }), _jsx("select", { className: "input", value: period, onChange: (e) => setPeriod(e.target.value), children: PERIODS.map((p) => (_jsx("option", { value: p.value, children: p.label }, p.value))) })] }), children: [_jsx("p", { className: "muted-text", children: "Organization project spend for the selected period. Open Activity to see the same Overview / Trends / Explore charts used elsewhere, scoped to one project." }), error ? _jsx("p", { className: "flash flash-error", children: error }) : null, loading ? _jsx("div", { className: "loading-state", children: "Loading\u2026" }) : null, _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Project" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Visibility" }), _jsx("th", { children: "Cost" }), _jsx("th", { children: "Media" }), _jsx("th", { children: "Requests" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [rows.map((row) => (_jsxs("tr", { children: [_jsx("td", { children: row.name }), _jsx("td", { children: row.status }), _jsx("td", { children: row.visibility }), _jsx("td", { children: formatUsd(row.costUsd) }), _jsx("td", { children: formatUsd(row.mediaCostUsd) }), _jsx("td", { children: row.requests }), _jsx("td", { children: _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => navigate(`/app/projects/${row.id}/activity`), children: USAGE_AND_ACTIVITY_LABEL }) })] }, row.id))), !loading && rows.length === 0 ? (_jsx("tr", { children: _jsx("td", { colSpan: 7, className: "empty-state", children: "No projects yet." }) })) : null] })] })] }));
}
