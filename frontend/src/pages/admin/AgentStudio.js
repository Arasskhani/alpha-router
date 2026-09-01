import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import ResourceAccessEditor from "../../components/admin/ResourceAccessEditor";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import { agentStatusTone, humanAgentStatus, readableDate, safeJsonObject, } from "../../lib/agentPlatform";
import { applyPolicyForm, policiesFromUnknown, readPolicyForm, splitExampleInput, splitKeywordInput, } from "../../lib/agentPolicyForm";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";
const defaultPolicies = (modelId) => ({
    model_policy: {
        primary_model_id: modelId,
        max_output_tokens: 4096,
    },
    retrieval_policy: {
        enabled: true,
        require_evidence: false,
        citations_required: true,
        fail_closed: true,
    },
    routing_policy: {
        enabled: true,
        explicit_only: false,
        priority: 100,
        keywords: [],
        examples: [],
    },
    disclaimer_policy: {
        required: false,
        text: "",
    },
    guardrail_policy: {
        fail_closed: true,
    },
});
export default function AgentStudio() {
    const navigate = useNavigate();
    const { confirm, prompt } = useConfirm();
    const [agents, setAgents] = useState([]);
    const [selectedAgentId, setSelectedAgentId] = useState("");
    const [detail, setDetail] = useState(null);
    const [selectedVersionId, setSelectedVersionId] = useState("");
    const [models, setModels] = useState([]);
    const [knowledgeBases, setKnowledgeBases] = useState([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [flash, setFlash] = useState("");
    const [search, setSearch] = useState("");
    const [createOpen, setCreateOpen] = useState(false);
    const [createName, setCreateName] = useState("");
    const [createSlug, setCreateSlug] = useState("");
    const [createDescription, setCreateDescription] = useState("");
    const [createModel, setCreateModel] = useState("");
    const [createPrompt, setCreatePrompt] = useState("");
    const [createAccess, setCreateAccess] = useState("private");
    const [editorPrompt, setEditorPrompt] = useState("");
    const [editorSummary, setEditorSummary] = useState("");
    const [policyDraft, setPolicyDraft] = useState({});
    const [policyForm, setPolicyForm] = useState(() => readPolicyForm({}));
    const [advancedJson, setAdvancedJson] = useState("{}");
    const [jsonDirty, setJsonDirty] = useState(false);
    const [keywordInput, setKeywordInput] = useState("");
    const [examplesText, setExamplesText] = useState("");
    const [bindOpen, setBindOpen] = useState(false);
    const [bindSearch, setBindSearch] = useState("");
    const [bindSelected, setBindSelected] = useState([]);
    const hydratePolicies = useCallback((policies) => {
        const form = readPolicyForm(policies);
        setPolicyDraft(policies);
        setPolicyForm(form);
        setAdvancedJson(JSON.stringify(policies, null, 2));
        setJsonDirty(false);
        setKeywordInput("");
        setExamplesText(form.examples.join("\n"));
    }, []);
    const updatePolicyForm = useCallback((patch) => {
        setPolicyForm((current) => {
            const next = { ...current, ...patch };
            setPolicyDraft((policies) => {
                const merged = applyPolicyForm(policies, next);
                setAdvancedJson(JSON.stringify(merged, null, 2));
                return merged;
            });
            setJsonDirty(false);
            return next;
        });
    }, []);
    const loadAgents = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const rows = await api("/api/admin/agents");
            setAgents(rows);
            setSelectedAgentId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id || "");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setLoading(false);
        }
    }, []);
    const loadDetail = useCallback(async (agentId) => {
        if (!agentId) {
            setDetail(null);
            return;
        }
        try {
            const row = await api(`/api/admin/agents/${encodeURIComponent(agentId)}`);
            setDetail(row);
            const selectable = row.versions.filter((version) => !(version.status === "archived" && !version.published_at));
            setSelectedVersionId((current) => {
                if (current && selectable.some((version) => version.id === current))
                    return current;
                return (selectable.find((version) => version.status === "draft")?.id
                    || row.active_version_id
                    || selectable[0]?.id
                    || "");
            });
        }
        catch (err) {
            setError(String(err));
        }
    }, []);
    useEffect(() => {
        void loadAgents();
        api("/api/chat/models").then((rows) => {
            setModels(rows);
            setCreateModel(rows[0]?.id || "");
        }).catch(() => { });
        api("/api/admin/knowledge/bases")
            .then(setKnowledgeBases)
            .catch(() => { });
    }, [loadAgents]);
    useEffect(() => {
        void loadDetail(selectedAgentId);
    }, [selectedAgentId, loadDetail]);
    const selectedVersion = useMemo(() => detail?.versions.find((version) => version.id === selectedVersionId) || null, [detail, selectedVersionId]);
    useEffect(() => {
        setEditorPrompt(selectedVersion?.system_prompt || "");
        setEditorSummary(selectedVersion?.change_summary || "");
        hydratePolicies(selectedVersion?.policies || {});
    }, [selectedVersion, hydratePolicies]);
    const filteredAgents = useMemo(() => {
        const needle = search.trim().toLowerCase();
        if (!needle)
            return agents;
        return agents.filter((agent) => `${agent.name} ${agent.slug} ${agent.category || ""}`.toLowerCase().includes(needle));
    }, [agents, search]);
    async function reloadSelected(message) {
        await loadAgents();
        if (selectedAgentId)
            await loadDetail(selectedAgentId);
        if (message)
            setFlash(message);
    }
    async function createAgent(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const created = await api("/api/admin/agents", {
                method: "POST",
                body: JSON.stringify({
                    name: createName,
                    slug: createSlug,
                    description: createDescription || undefined,
                    access_type: createAccess,
                    system_prompt: createPrompt,
                    change_summary: "Initial Agent draft",
                    policies: defaultPolicies(createModel),
                }),
            });
            setCreateOpen(false);
            setCreateName("");
            setCreateSlug("");
            setCreateDescription("");
            setCreatePrompt("");
            await loadAgents();
            setSelectedAgentId(created.id);
            setFlash("Agent draft created.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    function addKeywords(raw) {
        const added = splitKeywordInput(raw);
        if (added.length === 0)
            return;
        updatePolicyForm({
            keywords: [...policyForm.keywords, ...added.filter((item) => !policyForm.keywords.includes(item))],
        });
        setKeywordInput("");
    }
    function onKeywordKeyDown(event) {
        if (event.key !== "Enter" && event.key !== ",")
            return;
        event.preventDefault();
        addKeywords(keywordInput);
    }
    async function saveDraft(e) {
        e.preventDefault();
        if (!selectedVersion || selectedVersion.status !== "draft")
            return;
        setBusy(true);
        setError("");
        try {
            const pendingKeywords = splitKeywordInput(keywordInput);
            const form = {
                ...policyForm,
                examples: splitExampleInput(examplesText),
                keywords: pendingKeywords.length
                    ? [
                        ...policyForm.keywords,
                        ...pendingKeywords.filter((item) => !policyForm.keywords.includes(item)),
                    ]
                    : policyForm.keywords,
            };
            const base = jsonDirty
                ? policiesFromUnknown(safeJsonObject(advancedJson, "Policies"))
                : policyDraft;
            const policies = applyPolicyForm(base, form);
            await api(`/api/admin/agents/versions/${selectedVersion.id}`, {
                method: "PATCH",
                body: JSON.stringify({
                    system_prompt: editorPrompt,
                    change_summary: editorSummary || undefined,
                    policies,
                }),
            });
            setKeywordInput("");
            await reloadSelected("Draft saved.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function versionAction(action) {
        if (!selectedVersion)
            return;
        const reason = action === "rollback"
            ? await prompt({
                title: "Restore archived version",
                message: "Rollback creates a new published version from this archived snapshot.",
                promptLabel: "Reason",
                promptDefault: "Restore approved version",
                confirmLabel: "Restore",
            })
            : null;
        if (action === "rollback" && !reason?.trim())
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/agents/versions/${selectedVersion.id}/${action}`, {
                method: "POST",
                body: action === "rollback" ? JSON.stringify({ reason }) : undefined,
            });
            await reloadSelected(action === "submit"
                ? "Version submitted for review."
                : action === "publish"
                    ? "Version published."
                    : "Version restored.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function cloneVersion() {
        if (!detail || !selectedVersion)
            return;
        const ok = await confirm({
            title: "Clone to draft?",
            message: `Create a new editable draft from v${selectedVersion.version_number} ` +
                `(${humanAgentStatus(selectedVersion.status)})? You can discard the draft later if you change your mind.`,
            confirmLabel: "Clone",
            cancelLabel: "Cancel",
        });
        if (!ok)
            return;
        setBusy(true);
        setError("");
        try {
            const created = await api(`/api/admin/agents/${detail.id}/versions`, {
                method: "POST",
                body: JSON.stringify({
                    clone_version_id: selectedVersion.id,
                    change_summary: `Draft cloned from v${selectedVersion.version_number}`,
                }),
            });
            await reloadSelected("New draft version created.");
            setSelectedVersionId(created.id);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function discardDraft() {
        if (!detail || !selectedVersion || selectedVersion.status !== "draft")
            return;
        const ok = await confirm({
            title: "Discard draft?",
            message: `Permanently discard draft v${selectedVersion.version_number}? ` +
                "Unsaved edits and draft-only knowledge bindings on this version will be removed.",
            confirmLabel: "Discard draft",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        setBusy(true);
        setError("");
        try {
            const result = await api(`/api/admin/agents/versions/${encodeURIComponent(selectedVersion.id)}/discard`, { method: "POST" });
            setSelectedVersionId(result.next_version_id);
            await reloadSelected(`Draft v${selectedVersion.version_number} discarded.`);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    function openBindModal() {
        setBindSearch("");
        setBindSelected([]);
        setBindOpen(true);
    }
    function toggleBindSelection(knowledgeBaseId) {
        setBindSelected((current) => current.includes(knowledgeBaseId)
            ? current.filter((id) => id !== knowledgeBaseId)
            : [...current, knowledgeBaseId]);
    }
    async function removeBinding(binding) {
        if (!selectedVersion || selectedVersion.status !== "draft")
            return;
        const name = binding.knowledge_base_name || binding.knowledge_base_id;
        const ok = await confirm({
            title: "Remove Knowledge binding?",
            message: `Remove “${name}” from this draft? You can add it again later.`,
            confirmLabel: "Remove",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/agents/bindings/${encodeURIComponent(binding.id)}/revoke`, {
                method: "POST",
                body: JSON.stringify({ reason: "Removed from draft" }),
            });
            await reloadSelected(`Removed “${name}” from this draft.`);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function bindKnowledge() {
        if (!selectedVersion || bindSelected.length === 0)
            return;
        setBusy(true);
        setError("");
        let bound = 0;
        try {
            for (const knowledgeBaseId of bindSelected) {
                await api(`/api/admin/agents/versions/${selectedVersion.id}/bindings`, {
                    method: "POST",
                    body: JSON.stringify({
                        knowledge_base_id: knowledgeBaseId,
                        release_mode: "latest",
                        retrieval_policy: {},
                    }),
                });
                bound += 1;
            }
            setBindOpen(false);
            setBindSelected([]);
            await reloadSelected(bound === 1
                ? "Knowledge binding sent for approval."
                : `${bound} Knowledge bindings sent for approval.`);
        }
        catch (err) {
            if (bound > 0) {
                await reloadSelected(`${bound} binding(s) created before an error. ${String(err)}`);
            }
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function setAgentStatus(status) {
        if (!detail)
            return;
        if (status === "archived") {
            const ok = await confirm({
                title: "Archive Agent",
                message: `Archive “${detail.name}”? It will disappear from the user Agent catalog but keep history for audit.`,
                confirmLabel: "Archive",
                danger: true,
            });
            if (!ok)
                return;
        }
        setBusy(true);
        try {
            await api(`/api/admin/agents/${detail.id}`, {
                method: "PATCH",
                body: JSON.stringify({ status }),
            });
            await reloadSelected(status === "archived" ? "Agent archived." : "Agent activated.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function deleteAgent() {
        if (!detail)
            return;
        const typed = await prompt({
            title: "Delete Agent permanently?",
            message: `This permanently removes “${detail.name}” from Agent Studio and the user catalog. ` +
                "Audit history is retained; the Agent cannot be reactivated. Type the Agent name to confirm.",
            emphasize: detail.name,
            emphasizeDanger: true,
            promptLabel: `Type “${detail.name}” to confirm`,
            promptDefault: "",
            promptExactMatch: detail.name,
            confirmLabel: "Delete permanently",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (typed == null)
            return;
        if (typed.trim() !== detail.name) {
            setError("Agent name did not match. Deletion cancelled.");
            return;
        }
        const reason = await prompt({
            title: "Deletion reason",
            message: `Provide a short reason for permanently deleting “${detail.name}”.`,
            promptLabel: "Reason",
            promptDefault: "Removed permanently",
            confirmLabel: "Continue",
            danger: true,
        });
        if (!reason?.trim())
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/agents/${detail.id}/delete`, {
                method: "POST",
                body: JSON.stringify({
                    reason: reason.trim(),
                    mode: "purge",
                    confirm_name: detail.name,
                }),
            });
            setSelectedAgentId("");
            setDetail(null);
            await loadAgents();
            setFlash("Agent permanently deleted.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    const modelOptions = useMemo(() => {
        const current = policyForm.primaryModelId;
        if (current &&
            !models.some((model) => model.id === current || model.external_id === current)) {
            return [...models, { id: current, name: current, external_id: current }];
        }
        return models;
    }, [models, policyForm.primaryModelId]);
    const selectedModelValue = modelOptions.find((model) => model.id === policyForm.primaryModelId ||
        model.external_id === policyForm.primaryModelId)?.id || policyForm.primaryModelId;
    const versionBindings = (detail?.bindings || []).filter((binding) => binding.agent_version_id === selectedVersionId);
    const boundKnowledgeIds = useMemo(() => new Set(versionBindings.map((binding) => binding.knowledge_base_id)), [versionBindings]);
    const availableKnowledgeBases = useMemo(() => {
        const needle = bindSearch.trim().toLowerCase();
        return knowledgeBases.filter((knowledgeBase) => {
            if (boundKnowledgeIds.has(knowledgeBase.id))
                return false;
            if (!needle)
                return true;
            return `${knowledgeBase.name} ${knowledgeBase.slug} ${knowledgeBase.sensitivity}`
                .toLowerCase()
                .includes(needle);
        });
    }, [knowledgeBases, boundKnowledgeIds, bindSearch]);
    const selectableVersions = useMemo(() => (detail?.versions || []).filter((version) => !(version.status === "archived" && !version.published_at)), [detail]);
    return (_jsxs(AdminPage, { title: "Agent Studio", actions: _jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void loadAgents(), children: "Refresh" }), _jsx("button", { type: "button", className: "btn", onClick: () => setCreateOpen(true), children: "New Agent" })] }), children: [error ? _jsx("div", { className: "error", children: error }) : null, flash ? _jsx("div", { className: "success", children: flash }) : null, _jsxs("div", { className: "agent-studio-layout", "aria-busy": loading, children: [_jsxs("aside", { className: "agent-studio-list", children: [_jsx("input", { type: "search", placeholder: "Search Agents\u2026", value: search, onChange: (e) => setSearch(e.target.value) }), _jsxs("div", { className: "agent-studio-list__rows", children: [filteredAgents.map((agent) => (_jsxs("button", { type: "button", className: agent.id === selectedAgentId ? "is-selected" : "", onClick: () => setSelectedAgentId(agent.id), children: [_jsx("span", { className: "agent-avatar", "aria-hidden": true, children: agent.icon || "A" }), _jsxs("span", { children: [_jsx("strong", { children: agent.name }), _jsx("small", { children: agent.slug })] }), _jsx("em", { className: `agent-status ${agentStatusTone(agent.status)}`, children: humanAgentStatus(agent.status) })] }, agent.id))), !loading && filteredAgents.length === 0 ? (_jsx("p", { className: "agent-empty", children: "No Agents found." })) : null] })] }), _jsx("section", { className: "agent-studio-editor", children: !detail ? (_jsxs("div", { className: "agent-empty-state", children: [_jsx("h2", { children: "Select or create an Agent" }), _jsx("p", { children: "Agent configuration is versioned and published through maker-checker review." })] })) : (_jsxs(_Fragment, { children: [_jsxs("div", { className: "agent-studio-title", children: [_jsxs("div", { children: [_jsx("h2", { children: detail.name }), _jsxs("p", { children: [detail.description || "No description", " \u00B7 ", detail.access_type, " access \u00B7", " ", _jsx("span", { className: `agent-status ${agentStatusTone(detail.status)}`, children: humanAgentStatus(detail.status) })] })] }), _jsx("div", { className: "agent-studio-title-actions", children: _jsx(RowActionsMenu, { actions: [
                                                    {
                                                        label: USAGE_AND_ACTIVITY_LABEL,
                                                        onClick: () => navigate(`/admin/agents/${encodeURIComponent(detail.id)}/activity`),
                                                    },
                                                    detail.status === "archived"
                                                        ? {
                                                            label: "Reactivate",
                                                            disabled: busy,
                                                            onClick: () => void setAgentStatus("active"),
                                                        }
                                                        : {
                                                            label: "Archive",
                                                            disabled: busy,
                                                            onClick: () => void setAgentStatus("archived"),
                                                        },
                                                    {
                                                        label: "Delete permanently",
                                                        danger: true,
                                                        disabled: busy,
                                                        onClick: () => void deleteAgent(),
                                                    },
                                                ] }) })] }), _jsx(ResourceAccessEditor, { title: "Who can see this Agent", loadPath: `/api/admin/agents/${encodeURIComponent(detail.id)}/access`, savePath: `/api/admin/agents/${encodeURIComponent(detail.id)}/access`, disabled: busy, onError: setError, onSaved: () => void reloadSelected("Agent access updated.") }), _jsxs("div", { className: "agent-version-toolbar", children: [_jsxs("label", { children: ["Version", _jsx("select", { value: selectedVersionId, onChange: (e) => setSelectedVersionId(e.target.value), children: selectableVersions.map((version) => (_jsxs("option", { value: version.id, children: ["v", version.version_number, " \u00B7 ", humanAgentStatus(version.status)] }, version.id))) })] }), _jsxs("div", { children: [_jsx("button", { type: "button", className: "btn btn-ghost", disabled: !selectedVersion || busy, onClick: () => void cloneVersion(), children: "Clone to draft" }), selectedVersion?.status === "draft" ? (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void versionAction("submit"), children: "Submit review" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => void discardDraft(), children: "Discard draft" })] })) : null, selectedVersion?.status === "review" ? (_jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void versionAction("publish"), children: "Publish" })) : null, selectedVersion?.status === "archived" ? (_jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void versionAction("rollback"), children: "Restore" })) : null] })] }), selectedVersion ? (_jsxs("form", { className: "agent-editor-form", onSubmit: saveDraft, children: [_jsxs("div", { className: "agent-editor-meta", children: [_jsx("span", { className: `agent-status ${agentStatusTone(selectedVersion.status)}`, children: humanAgentStatus(selectedVersion.status) }), _jsxs("span", { children: ["Created ", readableDate(selectedVersion.created_at)] }), _jsx("code", { children: selectedVersion.id })] }), _jsxs("label", { children: ["System prompt", _jsx("textarea", { rows: 10, value: editorPrompt, readOnly: selectedVersion.status !== "draft", onChange: (e) => setEditorPrompt(e.target.value) })] }), _jsxs("label", { children: ["Change summary", _jsx("input", { value: editorSummary, readOnly: selectedVersion.status !== "draft", onChange: (e) => setEditorSummary(e.target.value) })] }), _jsxs("fieldset", { className: "agent-policy-fieldset", disabled: selectedVersion.status !== "draft", children: [_jsx("legend", { children: "How this Agent is found and answers" }), _jsxs("label", { children: ["Primary model", _jsxs("select", { value: selectedModelValue, onChange: (e) => {
                                                                const model = modelOptions.find((item) => item.id === e.target.value);
                                                                updatePolicyForm({
                                                                    primaryModelId: model?.external_id || model?.id || e.target.value,
                                                                });
                                                            }, children: [_jsx("option", { value: "", children: "Select model\u2026" }), modelOptions.map((model) => (_jsx("option", { value: model.id, children: model.name }, model.id)))] })] }), _jsxs("label", { children: ["Keywords", _jsxs("div", { className: "agent-keyword-editor", children: [_jsxs("div", { className: "agent-chip-list agent-chip-list--editor", children: [policyForm.keywords.map((keyword) => (_jsxs("span", { className: "agent-binding-chip", children: [keyword, selectedVersion.status === "draft" ? (_jsx("button", { type: "button", "aria-label": `Remove ${keyword}`, onClick: () => updatePolicyForm({
                                                                                        keywords: policyForm.keywords.filter((item) => item !== keyword),
                                                                                    }), children: "\u00D7" })) : null] }, keyword))), policyForm.keywords.length === 0 ? (_jsx("span", { className: "agent-empty", children: "No keywords yet." })) : null] }), selectedVersion.status === "draft" ? (_jsx("input", { value: keywordInput, placeholder: "Add a keyword and press Enter", onChange: (e) => setKeywordInput(e.target.value), onKeyDown: onKeywordKeyDown, onBlur: () => addKeywords(keywordInput) })) : null] }), _jsx("small", { children: selectedVersion.status === "draft"
                                                                ? "Used for routing. Separate with Enter or comma. Persian and English are both fine."
                                                                : "This published version is read-only. Use Clone to draft above, then add keywords on the new draft and publish it." })] }), _jsxs("label", { children: ["Example questions", _jsx("textarea", { rows: 4, value: examplesText, readOnly: selectedVersion.status !== "draft", onChange: (e) => {
                                                                setExamplesText(e.target.value);
                                                                updatePolicyForm({ examples: splitExampleInput(e.target.value) });
                                                            } }), _jsx("small", { children: "One example per line. These help the router recognize this Agent." })] }), _jsxs("label", { children: ["Disclaimer (English)", _jsx("textarea", { rows: 2, value: policyForm.disclaimerEn, readOnly: selectedVersion.status !== "draft", onChange: (e) => updatePolicyForm({ disclaimerEn: e.target.value }) })] }), _jsxs("label", { children: ["Disclaimer (Persian)", _jsx("textarea", { rows: 2, dir: "rtl", value: policyForm.disclaimerFa, readOnly: selectedVersion.status !== "draft", onChange: (e) => updatePolicyForm({ disclaimerFa: e.target.value }) })] }), _jsxs("div", { className: "agent-policy-toggles", children: [_jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: policyForm.retrievalEnabled, onChange: (e) => updatePolicyForm({ retrievalEnabled: e.target.checked }) }), "Use Knowledge Base retrieval"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: policyForm.requireEvidence, onChange: (e) => updatePolicyForm({ requireEvidence: e.target.checked }) }), "Require organizational evidence"] }), _jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: policyForm.citationsRequired, onChange: (e) => updatePolicyForm({ citationsRequired: e.target.checked }) }), "Require citations"] })] })] }), _jsxs("details", { className: "agent-policy-advanced", children: [_jsx("summary", { children: "Advanced policy JSON" }), _jsxs("label", { children: ["Policy document", _jsx("textarea", { className: "agent-json-editor", rows: 14, spellCheck: false, value: advancedJson, readOnly: selectedVersion.status !== "draft", onChange: (e) => {
                                                                setAdvancedJson(e.target.value);
                                                                setJsonDirty(true);
                                                            }, onBlur: () => {
                                                                if (!jsonDirty || selectedVersion.status !== "draft")
                                                                    return;
                                                                try {
                                                                    hydratePolicies(policiesFromUnknown(safeJsonObject(advancedJson, "Policies")));
                                                                    setError("");
                                                                }
                                                                catch (err) {
                                                                    setError(String(err));
                                                                }
                                                            } }), _jsx("small", { children: "Escape hatch for tools, guardrails, locale, and other version policies. The form above overwrites model, routing keywords/examples, disclaimer, and retrieval flags on save." })] })] }), selectedVersion.status === "draft" ? (_jsxs("div", { className: "agent-inline-form", children: [_jsx("button", { type: "submit", className: "btn", disabled: busy || !editorPrompt.trim(), children: busy ? "Saving…" : "Save draft" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => void discardDraft(), children: "Discard draft" })] })) : null] })) : null, _jsxs("section", { className: "agent-binding-section", children: [_jsxs("div", { className: "agent-section-card__head", children: [_jsxs("div", { children: [_jsx("h3", { children: "Knowledge bindings" }), _jsx("p", { children: "Bindings are version-scoped and require Knowledge approval." }), selectedVersion && selectedVersion.status !== "draft" ? (_jsx("p", { children: "This published version is read-only. Use Clone to draft above, then add Knowledge Bases on the new draft and publish it." })) : null] }), selectedVersion?.status === "draft" ? (_jsx("button", { type: "button", className: "btn", disabled: busy, onClick: openBindModal, children: "+ Add knowledge" })) : null] }), _jsxs("div", { className: "agent-chip-list", children: [versionBindings.map((binding) => (_jsxs("span", { className: "agent-binding-chip", children: [binding.knowledge_base_name || binding.knowledge_base_id, _jsx("em", { className: `agent-status ${agentStatusTone(binding.status)}`, children: humanAgentStatus(binding.status) }), selectedVersion?.status === "draft" ? (_jsx("button", { type: "button", "aria-label": `Remove ${binding.knowledge_base_name || binding.knowledge_base_id}`, disabled: busy, onClick: () => void removeBinding(binding), children: "\u00D7" })) : null] }, binding.id))), versionBindings.length === 0 ? _jsx("span", { className: "agent-empty", children: "No bindings." }) : null] })] })] })) })] }), _jsx(Modal, { open: createOpen, title: "Create Agent draft", onClose: () => !busy && setCreateOpen(false), panelClassName: "modal-panel--agent", children: _jsxs("form", { className: "agent-modal-form", onSubmit: createAgent, children: [_jsxs("label", { children: ["Name", _jsx("input", { required: true, value: createName, onChange: (e) => {
                                        setCreateName(e.target.value);
                                        if (!createSlug) {
                                            setCreateSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
                                        }
                                    } })] }), _jsxs("label", { children: ["Slug", _jsx("input", { required: true, value: createSlug, onChange: (e) => setCreateSlug(e.target.value) })] }), _jsxs("label", { children: ["Description", _jsx("textarea", { rows: 3, value: createDescription, onChange: (e) => setCreateDescription(e.target.value) })] }), _jsxs("label", { children: ["Primary model", _jsxs("select", { required: true, value: createModel, onChange: (e) => setCreateModel(e.target.value), children: [_jsx("option", { value: "", children: "Select model\u2026" }), models.map((model) => (_jsx("option", { value: model.id, children: model.name }, model.id)))] })] }), _jsxs("label", { children: ["Access", _jsxs("select", { value: createAccess, onChange: (e) => setCreateAccess(e.target.value), children: [_jsx("option", { value: "private", children: "Private \u00B7 explicit grants required" }), _jsx("option", { value: "public", children: "Public \u00B7 all active users" })] })] }), _jsxs("label", { children: ["System prompt", _jsx("textarea", { required: true, rows: 8, value: createPrompt, onChange: (e) => setCreatePrompt(e.target.value) })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => setCreateOpen(false), children: "Cancel" }), _jsx("button", { type: "submit", className: "btn", disabled: busy || !createModel, children: busy ? "Creating…" : "Create draft" })] })] }) }), _jsx(Modal, { open: bindOpen, title: "Add knowledge", onClose: () => !busy && setBindOpen(false), panelClassName: "modal-panel--agent", children: _jsxs("div", { className: "agent-bind-modal", children: [_jsx("input", { type: "search", placeholder: "Search Knowledge Bases\u2026", value: bindSearch, onChange: (e) => setBindSearch(e.target.value), disabled: busy }), _jsxs("div", { className: "agent-bind-list", role: "group", "aria-label": "Available Knowledge Bases", children: [availableKnowledgeBases.map((knowledgeBase) => {
                                    const checked = bindSelected.includes(knowledgeBase.id);
                                    return (_jsxs("label", { className: checked ? "is-selected" : "", children: [_jsx("input", { type: "checkbox", checked: checked, disabled: busy, onChange: () => toggleBindSelection(knowledgeBase.id) }), _jsxs("span", { children: [_jsx("strong", { children: knowledgeBase.name }), _jsxs("small", { children: [humanAgentStatus(knowledgeBase.sensitivity), knowledgeBase.access_type === "private" ? " · Private" : ""] })] })] }, knowledgeBase.id));
                                }), availableKnowledgeBases.length === 0 ? (_jsx("p", { className: "agent-empty", children: knowledgeBases.some((item) => !boundKnowledgeIds.has(item.id))
                                        ? "No Knowledge Bases match this search."
                                        : "All Knowledge Bases are already bound to this version." })) : null] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => setBindOpen(false), children: "Cancel" }), _jsx("button", { type: "button", className: "btn", disabled: busy || bindSelected.length === 0, onClick: () => void bindKnowledge(), children: busy
                                        ? "Requesting…"
                                        : bindSelected.length > 1
                                            ? `Request binding (${bindSelected.length})`
                                            : "Request binding" })] })] }) })] }));
}
