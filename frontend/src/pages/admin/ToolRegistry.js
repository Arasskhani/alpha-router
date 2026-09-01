import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import { agentStatusTone, humanAgentStatus, safeJsonObject, } from "../../lib/agentPlatform";
const emptySchema = JSON.stringify({ type: "object", properties: {}, additionalProperties: false }, null, 2);
export default function ToolRegistry() {
    const [tools, setTools] = useState([]);
    const [selectedToolId, setSelectedToolId] = useState("");
    const [selectedVersionId, setSelectedVersionId] = useState("");
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [flash, setFlash] = useState("");
    const [createOpen, setCreateOpen] = useState(false);
    const [name, setName] = useState("");
    const [slug, setSlug] = useState("");
    const [description, setDescription] = useState("");
    const [handlerKey, setHandlerKey] = useState("");
    const [effectType, setEffectType] = useState("read_only");
    const [inputSchema, setInputSchema] = useState(emptySchema);
    const [outputSchema, setOutputSchema] = useState(emptySchema);
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const rows = await api("/api/admin/agents/tools");
            setTools(rows);
            setSelectedToolId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id || "");
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
    const selectedTool = useMemo(() => tools.find((tool) => tool.id === selectedToolId) || null, [tools, selectedToolId]);
    const selectedVersion = useMemo(() => selectedTool?.versions.find((version) => version.id === selectedVersionId) || null, [selectedTool, selectedVersionId]);
    useEffect(() => {
        if (!selectedTool) {
            setSelectedVersionId("");
            return;
        }
        setSelectedVersionId((current) => current && selectedTool.versions.some((version) => version.id === current)
            ? current
            : selectedTool.versions.find((version) => version.status === "draft")?.id
                || selectedTool.active_version_id
                || selectedTool.versions[0]?.id
                || "");
    }, [selectedTool]);
    async function createTool(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const created = await api("/api/admin/agents/tools", {
                method: "POST",
                body: JSON.stringify({
                    name,
                    slug,
                    description: description || undefined,
                    handler_key: handlerKey,
                    input_schema: safeJsonObject(inputSchema, "Input schema"),
                    output_schema: safeJsonObject(outputSchema, "Output schema"),
                    effect_type: effectType,
                    idempotent: true,
                    approval_mode: effectType === "side_effecting" ? "required" : "never",
                    timeout_seconds: 20,
                    max_retries: 0,
                    change_summary: "Initial tool contract",
                }),
            });
            setCreateOpen(false);
            setName("");
            setSlug("");
            setDescription("");
            setHandlerKey("");
            setInputSchema(emptySchema);
            setOutputSchema(emptySchema);
            await load();
            setSelectedToolId(created.id);
            setFlash("Tool draft registered.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function lifecycle(action) {
        if (!selectedVersion)
            return;
        const reason = action === "rollback"
            ? window.prompt("Rollback reason:", "Restore approved tool contract")
            : null;
        if (action === "rollback" && !reason?.trim())
            return;
        setBusy(true);
        try {
            await api(`/api/admin/agents/tool-versions/${selectedVersion.id}/${action}`, {
                method: "POST",
                body: action === "rollback" ? JSON.stringify({ reason }) : undefined,
            });
            await load();
            setFlash(action === "submit"
                ? "Tool submitted for review."
                : action === "publish"
                    ? "Tool contract published."
                    : "Tool contract restored.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function cloneContract(version) {
        if (!selectedTool)
            return;
        setBusy(true);
        try {
            const created = await api(`/api/admin/agents/tools/${selectedTool.id}/versions`, {
                method: "POST",
                body: JSON.stringify({
                    input_schema: version.input_schema,
                    output_schema: version.output_schema,
                    handler_key: version.handler_key,
                    effect_type: version.effect_type,
                    approval_mode: version.approval_mode,
                    timeout_seconds: version.timeout_seconds,
                    max_retries: version.max_retries,
                    idempotent: version.idempotent,
                    change_summary: `Draft cloned from v${version.version_number}`,
                }),
            });
            await load();
            setSelectedVersionId(created.id);
            setFlash("New tool contract draft created.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs(AdminPage, { title: "Tool Registry", actions: _jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void load(), children: "Refresh" }), _jsx("button", { type: "button", className: "btn", onClick: () => setCreateOpen(true), children: "Register Tool" })] }), children: [_jsx("p", { className: "agent-page-lead", children: "Versioned JSON contracts, effect classification, explicit approvals, and model compatibility." }), error ? _jsx("div", { className: "error", children: error }) : null, flash ? _jsx("div", { className: "success", children: flash }) : null, _jsxs("div", { className: "tool-registry-layout", "aria-busy": loading, children: [_jsx("div", { className: "tool-registry-table table-wrap", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Tool" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Effect" }), _jsx("th", { children: "Handler" })] }) }), _jsxs("tbody", { children: [tools.map((tool) => {
                                            const active = tool.versions.find((version) => version.id === tool.active_version_id)
                                                || tool.versions[0];
                                            return (_jsxs("tr", { className: tool.id === selectedToolId ? "is-selected" : "", onClick: () => setSelectedToolId(tool.id), children: [_jsxs("td", { children: [_jsx("strong", { children: tool.name }), _jsx("small", { className: "agent-table-sub", children: tool.slug })] }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(tool.status)}`, children: humanAgentStatus(tool.status) }) }), _jsx("td", { children: active ? humanAgentStatus(active.effect_type) : "—" }), _jsx("td", { children: _jsx("code", { children: active?.handler_key || "—" }) })] }, tool.id));
                                        }), !loading && tools.length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 4, children: "No registered tools." }) }) : null] })] }) }), _jsx("aside", { className: "tool-contract-panel", children: !selectedTool || !selectedVersion ? (_jsxs("div", { className: "agent-empty-state", children: [_jsx("h2", { children: "Select a tool" }), _jsx("p", { children: "Inspect immutable contracts and lifecycle evidence." })] })) : (_jsxs(_Fragment, { children: [_jsxs("div", { className: "agent-studio-title", children: [_jsxs("div", { children: [_jsx("h2", { children: selectedTool.name }), _jsx("p", { children: selectedTool.description || "No description" })] }), _jsx("span", { className: `agent-status ${agentStatusTone(selectedVersion.status)}`, children: humanAgentStatus(selectedVersion.status) })] }), _jsxs("label", { children: ["Contract version", _jsx("select", { value: selectedVersionId, onChange: (e) => setSelectedVersionId(e.target.value), children: selectedTool.versions.map((version) => (_jsxs("option", { value: version.id, children: ["v", version.version_number, " \u00B7 ", humanAgentStatus(version.status)] }, version.id))) })] }), _jsxs("dl", { className: "agent-definition-list", children: [_jsxs("div", { children: [_jsx("dt", { children: "Handler" }), _jsx("dd", { children: _jsx("code", { children: selectedVersion.handler_key }) })] }), _jsxs("div", { children: [_jsx("dt", { children: "Effect" }), _jsx("dd", { children: humanAgentStatus(selectedVersion.effect_type) })] }), _jsxs("div", { children: [_jsx("dt", { children: "User approval" }), _jsx("dd", { children: humanAgentStatus(selectedVersion.approval_mode) })] }), _jsxs("div", { children: [_jsx("dt", { children: "Timeout" }), _jsxs("dd", { children: [selectedVersion.timeout_seconds, "s"] })] }), _jsxs("div", { children: [_jsx("dt", { children: "Retries" }), _jsx("dd", { children: selectedVersion.max_retries })] })] }), _jsxs("details", { className: "agent-contract-details", children: [_jsx("summary", { children: "Input schema" }), _jsx("pre", { children: JSON.stringify(selectedVersion.input_schema, null, 2) })] }), _jsxs("details", { className: "agent-contract-details", children: [_jsx("summary", { children: "Output schema" }), _jsx("pre", { children: JSON.stringify(selectedVersion.output_schema, null, 2) })] }), _jsxs("div", { className: "agent-action-row", children: [_jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => void cloneContract(selectedVersion), children: "Clone draft" }), selectedVersion.status === "draft" ? _jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void lifecycle("submit"), children: "Submit review" }) : null, selectedVersion.status === "review" ? _jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void lifecycle("publish"), children: "Publish" }) : null, selectedVersion.status === "archived" ? _jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void lifecycle("rollback"), children: "Restore" }) : null] })] })) })] }), _jsx(Modal, { open: createOpen, title: "Register Tool", onClose: () => !busy && setCreateOpen(false), panelClassName: "modal-panel--agent modal-panel--agent-wide", children: _jsxs("form", { className: "agent-modal-form agent-modal-form--tool", onSubmit: createTool, children: [_jsxs("label", { children: ["Name", _jsx("input", { required: true, value: name, onChange: (e) => {
                                        setName(e.target.value);
                                        if (!slug)
                                            setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
                                    } })] }), _jsxs("label", { children: ["Slug", _jsx("input", { required: true, value: slug, onChange: (e) => setSlug(e.target.value) })] }), _jsxs("label", { className: "agent-form-wide", children: ["Description", _jsx("textarea", { rows: 2, value: description, onChange: (e) => setDescription(e.target.value) })] }), _jsxs("label", { children: ["Handler key", _jsx("input", { required: true, placeholder: "service.action", value: handlerKey, onChange: (e) => setHandlerKey(e.target.value) })] }), _jsxs("label", { children: ["Effect", _jsxs("select", { value: effectType, onChange: (e) => setEffectType(e.target.value), children: [_jsx("option", { value: "read_only", children: "Read only" }), _jsx("option", { value: "side_effecting", children: "Side effecting \u00B7 approval required" })] })] }), _jsxs("label", { className: "agent-form-wide", children: ["Input JSON Schema", _jsx("textarea", { rows: 10, className: "agent-json-editor", spellCheck: false, value: inputSchema, onChange: (e) => setInputSchema(e.target.value) })] }), _jsxs("label", { className: "agent-form-wide", children: ["Output JSON Schema", _jsx("textarea", { rows: 10, className: "agent-json-editor", spellCheck: false, value: outputSchema, onChange: (e) => setOutputSchema(e.target.value) })] }), _jsxs("div", { className: "dialog-actions agent-form-wide", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => setCreateOpen(false), children: "Cancel" }), _jsx("button", { className: "btn", disabled: busy, children: busy ? "Registering…" : "Register draft" })] })] }) })] }));
}
