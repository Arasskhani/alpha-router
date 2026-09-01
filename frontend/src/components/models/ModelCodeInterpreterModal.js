import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import Modal from "../Modal";
function formatTime(value) {
    if (!value)
        return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
export default function ModelCodeInterpreterModal({ open, modelId, modelLabel, onClose, onSaved, }) {
    const [detail, setDetail] = useState(null);
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState("");
    const [msg, setMsg] = useState("");
    const load = useCallback(async () => {
        if (modelId == null)
            return;
        setLoading(true);
        setErr("");
        try {
            setDetail(await api(`/api/admin/models/${modelId}/code-interpreter-compatibility`));
        }
        catch (e) {
            setErr(String(e));
        }
        finally {
            setLoading(false);
        }
    }, [modelId]);
    useEffect(() => {
        if (!open || modelId == null)
            return;
        setMsg("");
        void load();
    }, [open, modelId, load]);
    async function applyOverride(override) {
        if (modelId == null)
            return;
        setBusy(true);
        setErr("");
        setMsg("");
        try {
            await api(`/api/admin/models/${modelId}/code-interpreter-compatibility`, {
                method: "PUT",
                body: JSON.stringify({ override }),
            });
            await load();
            await onSaved();
            setMsg(override === "auto"
                ? "Automatic detection restored."
                : `Pinned as ${override}.`);
        }
        catch (e) {
            setErr(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function runProbe() {
        if (modelId == null)
            return;
        setBusy(true);
        setErr("");
        setMsg("");
        try {
            const result = await api(`/api/admin/models/${modelId}/code-interpreter-probe`, { method: "POST" });
            await load();
            await onSaved();
            setMsg(result.ok
                ? `Probe passed${result.selected_model_id ? ` via ${result.selected_model_id}` : ""}.`
                : `Probe failed: ${result.reason_code || "unknown"}`);
        }
        catch (e) {
            setErr(String(e));
        }
        finally {
            setBusy(false);
        }
    }
    const compat = detail?.compatibility;
    const override = (compat?.manual_override || "auto");
    return (_jsxs(Modal, { open: open, title: `Code Interpreter — ${modelLabel}`, onClose: onClose, children: [err ? _jsx("p", { className: "error", children: err }) : null, msg ? _jsx("p", { className: "muted-text", children: msg }) : null, loading ? (_jsx("p", { className: "muted-text", children: "Loading\u2026" })) : (_jsxs(_Fragment, { children: [_jsxs("div", { className: "model-compat__summary", children: [_jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Status" }), _jsx("strong", { children: compat?.status || "unknown" })] }), _jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Health score" }), _jsx("strong", { children: compat?.score == null ? "—" : compat.score.toFixed(2) })] }), _jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Reason" }), _jsx("strong", { children: compat?.reason_detail || compat?.reason_code || "—" })] }), _jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Last probe" }), _jsx("strong", { children: formatTime(compat?.last_probe_at) })] }), _jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Last success" }), _jsx("strong", { children: formatTime(compat?.last_success_at) })] }), _jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Last failure" }), _jsx("strong", { children: formatTime(compat?.last_failure_at) })] }), _jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Next probe" }), _jsx("strong", { children: formatTime(compat?.next_probe_at) })] }), _jsxs("div", { children: [_jsx("span", { className: "muted-text", children: "Quarantine until" }), _jsx("strong", { children: formatTime(compat?.quarantine_until) })] })] }), _jsx("p", { className: "muted-text", children: "Compatibility is measured automatically. Pin a value only to override the measured result for this model." }), _jsxs("div", { className: "dialog-actions", style: { flexWrap: "wrap", gap: "0.5rem" }, children: [_jsx("button", { type: "button", className: "btn", disabled: busy, onClick: runProbe, children: busy ? "…" : "Run probe now" }), _jsx("button", { type: "button", className: `btn btn-ghost model-compat__choice${override === "auto" ? " model-compat__choice--on" : ""}`, disabled: busy, onClick: () => applyOverride("auto"), children: "Automatic" }), _jsx("button", { type: "button", className: `btn btn-ghost model-compat__choice${override === "compatible" ? " model-compat__choice--on" : ""}`, disabled: busy, onClick: () => applyOverride("compatible"), children: "Force allow" }), _jsx("button", { type: "button", className: `btn btn-ghost model-compat__choice${override === "incompatible" ? " model-compat__choice--on" : ""}`, disabled: busy, onClick: () => applyOverride("incompatible"), children: "Force block" })] }), _jsx("h4", { children: "Recent evidence" }), detail?.events?.length ? (_jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "card data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "When" }), _jsx("th", { children: "Source" }), _jsx("th", { children: "Result" }), _jsx("th", { children: "Reason" })] }) }), _jsx("tbody", { children: detail.events.map((event) => (_jsxs("tr", { children: [_jsx("td", { children: formatTime(event.created_at) }), _jsx("td", { children: event.source }), _jsx("td", { children: event.source === "admin"
                                                    ? "override"
                                                    : event.success
                                                        ? "pass"
                                                        : "fail" }), _jsx("td", { children: event.reason_code || event.detail || "—" })] }, event.id))) })] }) })) : (_jsx("p", { className: "muted-text", children: "No probe or runtime evidence recorded yet." }))] }))] }));
}
