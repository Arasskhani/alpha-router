import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { embeddingModelIdFromSpec, embeddingModelOptionLabel, suggestedEmbeddingDimensions, } from "../../lib/embeddingDimensions";
import SearchableModelSelect from "../../components/admin/SearchableModelSelect";
const SENSITIVE_OPTIONS = ["health", "financial", "work", "family", "preference", "identity", "other"];
/** Mirrors PROJECT_DENIED_CATEGORIES in the backend; not admin-configurable. */
const PROJECT_DENIED_CATEGORIES = ["health", "financial", "personal", "family", "identity"];
function formatJobs(byStatus) {
    const entries = Object.entries(byStatus || {}).filter(([, count]) => count > 0);
    if (!entries.length)
        return "Idle";
    return entries.map(([status, count]) => `${status} ${count}`).join(" · ");
}
function formatPendingAge(seconds) {
    if (seconds == null)
        return "—";
    if (seconds < 60)
        return `${Math.round(seconds)}s`;
    return `${Math.round(seconds / 60)}m`;
}
function formatUsd(n) {
    return `$${n.toFixed(n >= 1 ? 2 : 4)}`;
}
function FieldRow({ title, hint, children, detail, }) {
    return (_jsxs("div", { className: `settings-row-block${detail ? " settings-row-block--open" : ""}`, children: [_jsxs("div", { className: "settings-row", children: [_jsxs("div", { className: "settings-row__meta", children: [_jsx("span", { className: "settings-row__title", children: title }), hint ? _jsx("span", { className: "settings-row__hint", children: hint }) : null] }), children ? _jsx("div", { className: "settings-row__trail", children: children }) : null] }), detail ? _jsx("div", { className: "settings-row__detail", children: detail }) : null] }));
}
function NumberInput({ id, value, disabled, step, min, onChange, }) {
    return (_jsx("input", { id: id, type: "number", className: "settings-row__control", step: step, min: min, value: Number.isFinite(value) ? value : 0, disabled: disabled, "aria-label": id.replace(/-/g, " "), onChange: (e) => onChange(Number(e.target.value)) }));
}
function Toggle({ on, disabled, label, onToggle, }) {
    return (_jsx("button", { type: "button", className: `alpha-router-toggle${on ? " on" : ""}`, onClick: onToggle, "aria-label": label, "aria-pressed": on, disabled: disabled, children: _jsx("span", { className: "alpha-router-toggle-knob" }) }));
}
function StatusCell({ label, value }) {
    return (_jsxs("div", { children: [_jsx("dt", { children: label }), _jsx("dd", { children: value })] }));
}
export default function MemoryAdmin() {
    const { confirm } = useConfirm();
    const readOnly = useReadOnly();
    const [settings, setSettings] = useState(null);
    const [stats, setStats] = useState(null);
    const [models, setModels] = useState([]);
    const [flash, setFlash] = useState("");
    const [error, setError] = useState("");
    const [saving, setSaving] = useState(false);
    const [reindexing, setReindexing] = useState(false);
    const [purgeUserId, setPurgeUserId] = useState("");
    async function load() {
        setError("");
        const [cfg, st, catalog] = await Promise.all([
            api("/api/admin/memory/settings"),
            api("/api/admin/memory/stats"),
            api("/api/admin/models"),
        ]);
        setSettings(cfg);
        setStats(st);
        setModels(Array.isArray(catalog) ? catalog : []);
    }
    useEffect(() => {
        void load().catch((err) => setError(String(err)));
    }, []);
    const textModels = models.filter((m) => m.enabled && (m.kinds || []).includes("text"));
    const embeddingModels = models.filter((m) => m.enabled && (m.kinds || []).includes("embeddings"));
    useEffect(() => {
        if (!settings?.embedding_model)
            return;
        if ((settings.embedding_dimensions ?? 0) > 0)
            return;
        const dims = suggestedEmbeddingDimensions(embeddingModelIdFromSpec(settings.embedding_model));
        setSettings((current) => {
            if (!current?.embedding_model || (current.embedding_dimensions ?? 0) > 0)
                return current;
            return { ...current, embedding_dimensions: dims };
        });
    }, [settings]);
    async function onSave(e) {
        e.preventDefault();
        if (!settings)
            return;
        setSaving(true);
        setError("");
        setFlash("");
        try {
            const saved = await api("/api/admin/memory/settings", {
                method: "PATCH",
                body: JSON.stringify(settings),
            });
            setSettings(saved);
            setFlash("Memory settings saved.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setSaving(false);
        }
    }
    async function onReindex() {
        const ok = await confirm({
            title: "Rebuild memory index",
            message: "Re-embed every stored memory into a new Qdrant collection. Chat stays online; this may take a few minutes.",
            confirmLabel: "Reindex",
        });
        if (!ok)
            return;
        setReindexing(true);
        setError("");
        setFlash("");
        try {
            const result = await api("/api/admin/memory/reindex", { method: "POST" });
            setFlash(`Reindexed ${result.indexed ?? 0} memories.`);
            await load();
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setReindexing(false);
        }
    }
    async function onPurgeUser() {
        const id = Number(purgeUserId);
        if (!Number.isInteger(id) || id < 1) {
            setError("Enter a valid user id.");
            return;
        }
        const ok = await confirm({
            title: "Purge user memories",
            message: `Permanently delete all memories for user ${id}. This cannot be undone.`,
            confirmLabel: "Purge",
            danger: true,
        });
        if (!ok)
            return;
        setError("");
        setFlash("");
        try {
            const result = await api(`/api/admin/memory/purge-user/${id}`, {
                method: "POST",
            });
            setFlash(`Deleted ${result.deleted ?? 0} memories for user ${id}.`);
            setPurgeUserId("");
            await load();
        }
        catch (err) {
            setError(String(err));
        }
    }
    function patch(partial) {
        if (!settings)
            return;
        setSettings({ ...settings, ...partial });
    }
    function toggleCategory(cat, checked) {
        if (!settings)
            return;
        const next = new Set(settings.allowed_sensitive_categories || []);
        if (checked)
            next.add(cat);
        else
            next.delete(cat);
        patch({ allowed_sensitive_categories: [...next] });
    }
    const saveBar = (_jsxs(_Fragment, { children: [_jsx("button", { type: "submit", form: "memory-settings-form", className: "btn", disabled: readOnly || saving || !settings, children: saving ? "Saving…" : "Save" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: readOnly || reindexing || !settings, onClick: () => void onReindex(), children: reindexing ? "Reindexing…" : "Rebuild index" })] }));
    if (!settings) {
        return (_jsx(AdminPage, { title: "Memory", actions: saveBar, children: _jsx("p", { className: "muted-text", children: error || "Loading…" }) }));
    }
    return (_jsx(AdminPage, { title: "Memory", actions: saveBar, children: _jsxs("div", { className: "memory-admin", children: [_jsx("p", { className: "muted-text memory-admin__lead", children: "Automatic long-term memory for personal chat and shared project facts. Extraction uses the model below (system cost). Until a model is selected, nothing is learned." }), flash ? _jsx("p", { className: "alert alert-success", children: flash }) : null, error ? _jsx("p", { className: "alert alert-error", children: error }) : null, _jsxs("section", { className: "memory-admin__status", "aria-label": "Memory health", children: [_jsxs("div", { children: [_jsx("h2", { children: "User" }), _jsxs("dl", { children: [_jsx(StatusCell, { label: "Memories", value: stats ? stats.total_memories.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Last 7 days", value: stats ? stats.memories_last_7d.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Embed backlog", value: stats ? stats.embedding_backlog.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Dead letter", value: stats ? stats.dead_letter_count.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Oldest pending", value: stats ? formatPendingAge(stats.oldest_pending_job_age_seconds) : "…" }), _jsx(StatusCell, { label: "Extract 30d", value: stats ? formatUsd(stats.extraction_cost_usd_30d) : "…" }), _jsx(StatusCell, { label: "Jobs", value: stats ? formatJobs(stats.jobs_by_status) : "…" })] })] }), _jsxs("div", { children: [_jsx("h2", { children: "Project" }), _jsxs("dl", { children: [_jsx(StatusCell, { label: "Learned", value: stats ? stats.project_learned_memories.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Manual", value: stats ? stats.project_manual_memories.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Embed backlog", value: stats ? stats.project_embedding_backlog.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Dead letter", value: stats ? stats.project_dead_letter_count.toLocaleString() : "…" }), _jsx(StatusCell, { label: "Extract 30d", value: stats ? formatUsd(stats.project_extraction_cost_usd_30d) : "…" }), _jsx(StatusCell, { label: "Jobs", value: stats ? formatJobs(stats.project_jobs_by_status) : "…" })] })] })] }), _jsxs("form", { id: "memory-settings-form", onSubmit: (e) => void onSave(e), children: [_jsxs("section", { className: "settings-section", children: [_jsx("h2", { children: "Pipeline" }), _jsx("p", { className: "settings-section-desc", children: "Shared models and housekeeping. Changing the embedding model requires a rebuild." }), _jsxs("div", { className: "settings-list", children: [_jsx(FieldRow, { title: "Automatic memory", hint: "Master switch for user extraction and injection", children: _jsx(Toggle, { label: "Automatic memory", on: settings.feature_enabled, disabled: readOnly, onToggle: () => patch({ feature_enabled: !settings.feature_enabled }) }) }), _jsx(FieldRow, { title: "Extraction model", hint: "Required. Cost is billed as a system operation", children: _jsx(SearchableModelSelect, { id: "memory-extraction-model", ariaLabel: "Extraction model", value: settings.extraction_model_id ? String(settings.extraction_model_id) : "", disabled: readOnly, emptyLabel: "Not configured", placeholder: "Search extraction models\u2026", options: textModels.map((m) => ({
                                                    value: String(m.id),
                                                    label: `${m.display_name || m.external_id} · ${m.provider}`,
                                                })), onChange: (next) => patch({ extraction_model_id: next ? Number(next) : null }) }) }), _jsx(FieldRow, { title: "Embedding model", hint: "Empty = Postgres-only retrieval", children: _jsx(SearchableModelSelect, { id: "memory-embedding-model", ariaLabel: "Embedding model", value: settings.embedding_model || "", disabled: readOnly, emptyLabel: "Not configured", placeholder: "Search embedding models\u2026", options: embeddingModels.map((m) => ({
                                                    value: `${m.provider}:${m.external_id}`,
                                                    label: embeddingModelOptionLabel(m.external_id, m.provider),
                                                })), onChange: (spec) => {
                                                    if (!spec) {
                                                        patch({ embedding_model: "", embedding_dimensions: null });
                                                        return;
                                                    }
                                                    patch({
                                                        embedding_model: spec,
                                                        embedding_dimensions: suggestedEmbeddingDimensions(embeddingModelIdFromSpec(spec)),
                                                    });
                                                } }) }), _jsx(FieldRow, { title: "Embedding dimensions", hint: "Filled from the model. Override if needed. Rebuild after changing", children: _jsx(NumberInput, { id: "memory-embedding-dims", value: settings.embedding_dimensions ?? 0, min: 0, disabled: readOnly || !settings.embedding_model, onChange: (n) => patch({ embedding_dimensions: n || null }) }) }), _jsx(FieldRow, { title: "Retrieval timeout", hint: "Milliseconds", children: _jsx(NumberInput, { id: "memory-retrieval-timeout", value: settings.retrieval_timeout_ms, disabled: readOnly, onChange: (n) => patch({ retrieval_timeout_ms: n }) }) }), _jsx(FieldRow, { title: "Stale archive", hint: "Days unused before archive \u00B7 0 = off", children: _jsx(NumberInput, { id: "memory-stale-archive", value: settings.stale_archive_days, min: 0, disabled: readOnly, onChange: (n) => patch({ stale_archive_days: n }) }) }), _jsx(FieldRow, { title: "Soft-delete purge", hint: "Days after delete before hard purge", children: _jsx(NumberInput, { id: "memory-soft-delete", value: settings.soft_delete_purge_days, disabled: readOnly, onChange: (n) => patch({ soft_delete_purge_days: n }) }) }), _jsx(FieldRow, { title: "Suppression", hint: "Days a deleted fact is blocked from re-learning", children: _jsx(NumberInput, { id: "memory-suppression", value: settings.suppression_days, disabled: readOnly, onChange: (n) => patch({ suppression_days: n }) }) })] })] }), _jsxs("section", { className: "settings-section", children: [_jsx("h2", { children: "User memory" }), _jsx("p", { className: "settings-section-desc", children: "Caps, retrieval, and extraction cadence for personal chat." }), _jsxs("div", { className: "settings-list", children: [_jsx(FieldRow, { title: "Max per user", children: _jsx(NumberInput, { id: "memory-max-per-user", value: settings.max_per_user, disabled: readOnly, onChange: (n) => patch({ max_per_user: n }) }) }), _jsx(FieldRow, { title: "Core items", hint: "Always injected when present", children: _jsx(NumberInput, { id: "memory-core-items", value: settings.core_items, disabled: readOnly, onChange: (n) => patch({ core_items: n }) }) }), _jsx(FieldRow, { title: "Inject max items", children: _jsx(NumberInput, { id: "memory-inject-items", value: settings.inject_max_items, disabled: readOnly, onChange: (n) => patch({ inject_max_items: n }) }) }), _jsx(FieldRow, { title: "Inject max chars", children: _jsx(NumberInput, { id: "memory-inject-chars", value: settings.inject_max_chars, disabled: readOnly, onChange: (n) => patch({ inject_max_chars: n }) }) }), _jsx(FieldRow, { title: "Semantic top-k", children: _jsx(NumberInput, { id: "memory-semantic-k", value: settings.semantic_top_k, disabled: readOnly, onChange: (n) => patch({ semantic_top_k: n }) }) }), _jsx(FieldRow, { title: "Lexical top-k", children: _jsx(NumberInput, { id: "memory-lexical-k", value: settings.lexical_top_k, disabled: readOnly, onChange: (n) => patch({ lexical_top_k: n }) }) }), _jsx(FieldRow, { title: "Min similarity", hint: "0\u20131", children: _jsx(NumberInput, { id: "memory-min-sim", value: settings.min_similarity, step: "0.01", disabled: readOnly, onChange: (n) => patch({ min_similarity: n }) }) }), _jsx(FieldRow, { title: "Debounce", hint: "Seconds after a turn before extract", children: _jsx(NumberInput, { id: "memory-debounce", value: settings.extract_debounce_seconds, disabled: readOnly, onChange: (n) => patch({ extract_debounce_seconds: n }) }) }), _jsx(FieldRow, { title: "Max wait", hint: "Seconds before a forced extract", children: _jsx(NumberInput, { id: "memory-max-wait", value: settings.extract_max_wait_seconds, disabled: readOnly, onChange: (n) => patch({ extract_max_wait_seconds: n }) }) }), _jsx(FieldRow, { title: "Min new messages", children: _jsx(NumberInput, { id: "memory-min-messages", value: settings.extract_min_new_messages, disabled: readOnly, onChange: (n) => patch({ extract_min_new_messages: n }) }) }), _jsx(FieldRow, { title: "Sensitive categories", hint: `User memory only. Empty list drops all sensitive facts. Project memory always drops ${PROJECT_DENIED_CATEGORIES.join(", ")}.`, detail: _jsx("div", { className: "memory-admin__chips", children: SENSITIVE_OPTIONS.map((cat) => (_jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: (settings.allowed_sensitive_categories || []).includes(cat), disabled: readOnly, onChange: (e) => toggleCategory(cat, e.target.checked) }), cat] }, cat))) }) })] })] }), _jsxs("section", { className: "settings-section", children: [_jsx("h2", { children: "Project memory" }), _jsx("p", { className: "settings-section-desc", children: "Shared team facts from project AI chats. Personal memory is never injected there." }), _jsxs("div", { className: "settings-list", children: [_jsx(FieldRow, { title: "Automatic project memory", hint: "Organization-wide kill switch", children: _jsx(Toggle, { label: "Automatic project memory", on: settings.project_feature_enabled, disabled: readOnly, onToggle: () => patch({ project_feature_enabled: !settings.project_feature_enabled }) }) }), _jsx(FieldRow, { title: "Max per project", children: _jsx(NumberInput, { id: "project-max", value: settings.project_max_per_project, disabled: readOnly, onChange: (n) => patch({ project_max_per_project: n }) }) }), _jsx(FieldRow, { title: "Manual facts injected", hint: "Owner-authored facts always included", children: _jsx(NumberInput, { id: "project-manual", value: settings.project_manual_items, disabled: readOnly, onChange: (n) => patch({ project_manual_items: n }) }) }), _jsx(FieldRow, { title: "Inject max items", children: _jsx(NumberInput, { id: "project-inject-items", value: settings.project_inject_max_items, disabled: readOnly, onChange: (n) => patch({ project_inject_max_items: n }) }) }), _jsx(FieldRow, { title: "Inject max chars", children: _jsx(NumberInput, { id: "project-inject-chars", value: settings.project_inject_max_chars, disabled: readOnly, onChange: (n) => patch({ project_inject_max_chars: n }) }) }), _jsx(FieldRow, { title: "Semantic top-k", children: _jsx(NumberInput, { id: "project-semantic-k", value: settings.project_semantic_top_k, disabled: readOnly, onChange: (n) => patch({ project_semantic_top_k: n }) }) }), _jsx(FieldRow, { title: "Lexical top-k", children: _jsx(NumberInput, { id: "project-lexical-k", value: settings.project_lexical_top_k, disabled: readOnly, onChange: (n) => patch({ project_lexical_top_k: n }) }) }), _jsx(FieldRow, { title: "Min similarity", hint: "0\u20131", children: _jsx(NumberInput, { id: "project-min-sim", value: settings.project_min_similarity, step: "0.01", disabled: readOnly, onChange: (n) => patch({ project_min_similarity: n }) }) }), _jsx(FieldRow, { title: "Debounce", hint: "Seconds", children: _jsx(NumberInput, { id: "project-debounce", value: settings.project_extract_debounce_seconds, disabled: readOnly, onChange: (n) => patch({ project_extract_debounce_seconds: n }) }) }), _jsx(FieldRow, { title: "Max wait", hint: "Seconds", children: _jsx(NumberInput, { id: "project-max-wait", value: settings.project_extract_max_wait_seconds, disabled: readOnly, onChange: (n) => patch({ project_extract_max_wait_seconds: n }) }) }), _jsx(FieldRow, { title: "Min new messages", children: _jsx(NumberInput, { id: "project-min-messages", value: settings.project_extract_min_new_messages, disabled: readOnly, onChange: (n) => patch({ project_extract_min_new_messages: n }) }) })] })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: readOnly || saving, children: saving ? "Saving…" : "Save settings" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: readOnly || reindexing, onClick: () => void onReindex(), children: reindexing ? "Reindexing…" : "Rebuild index" })] })] }), _jsxs("section", { className: "settings-section", children: [_jsx("h2", { children: "Support" }), _jsx("p", { className: "settings-section-desc", children: "Compliance purge for a single user. This cannot be undone." }), _jsx("div", { className: "settings-list", children: _jsxs(FieldRow, { title: "Purge user memories", hint: "Permanently deletes every memory for this user id", children: [_jsx("input", { id: "memory-purge-user", className: "settings-row__control", inputMode: "numeric", value: purgeUserId, placeholder: "User id", disabled: readOnly, "aria-label": "User id to purge", onChange: (e) => setPurgeUserId(e.target.value) }), _jsx("button", { type: "button", className: "settings-row__action settings-row__action--danger", disabled: readOnly, onClick: () => void onPurgeUser(), children: "Purge" })] }) })] })] }) }));
}
