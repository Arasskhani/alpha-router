import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import ResourceAccessEditor from "../../components/admin/ResourceAccessEditor";
import SearchableModelSelect from "../../components/admin/SearchableModelSelect";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import { agentStatusTone, humanAgentStatus, readableDate, } from "../../lib/agentPlatform";
import { embeddingModelOptionLabel } from "../../lib/embeddingDimensions";
const MAX_KNOWLEDGE_UPLOAD_FILES = 20;
export default function KnowledgeBases() {
    const { confirm, prompt } = useConfirm();
    const [bases, setBases] = useState([]);
    const [selectedId, setSelectedId] = useState("");
    const [detail, setDetail] = useState(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [flash, setFlash] = useState("");
    const [createOpen, setCreateOpen] = useState(false);
    const [name, setName] = useState("");
    const [slug, setSlug] = useState("");
    const [description, setDescription] = useState("");
    const [sensitivity, setSensitivity] = useState("internal");
    const [accessType, setAccessType] = useState("private");
    const [uploadTitle, setUploadTitle] = useState("");
    const [uploadFiles, setUploadFiles] = useState([]);
    const [uploadProgress, setUploadProgress] = useState(null);
    const [connectorName, setConnectorName] = useState("");
    const [connectorUrls, setConnectorUrls] = useState("");
    const [embeddingModels, setEmbeddingModels] = useState([]);
    const [selectedEmbeddingId, setSelectedEmbeddingId] = useState("");
    const [retentionDaysInput, setRetentionDaysInput] = useState("");
    const fileInput = useRef(null);
    const loadBases = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const rows = await api("/api/admin/knowledge/bases");
            setBases(rows);
            setSelectedId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id || "");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setLoading(false);
        }
    }, []);
    const loadDetail = useCallback(async (id) => {
        if (!id) {
            setDetail(null);
            setRetentionDaysInput("");
            return;
        }
        try {
            const next = await api(`/api/admin/knowledge/bases/${encodeURIComponent(id)}`);
            setDetail(next);
            setRetentionDaysInput(next.retention_days != null && next.retention_days > 0
                ? String(next.retention_days)
                : "");
        }
        catch (err) {
            setError(String(err));
        }
    }, []);
    useEffect(() => {
        void loadBases();
        api("/api/admin/knowledge/embedding-models")
            .then((rows) => {
            setEmbeddingModels(rows);
            setSelectedEmbeddingId((current) => {
                if (current && rows.some((row) => String(row.id) === current))
                    return current;
                const preferred = rows.find((row) => row.external_id.includes("text-embedding-3-small"))
                    || rows.find((row) => row.external_id.includes("text-embedding"))
                    || rows[0];
                return preferred ? String(preferred.id) : "";
            });
        })
            .catch(() => setEmbeddingModels([]));
    }, [loadBases]);
    useEffect(() => {
        void loadDetail(selectedId);
    }, [selectedId, loadDetail]);
    async function reload(message) {
        await loadBases();
        if (selectedId)
            await loadDetail(selectedId);
        if (message)
            setFlash(message);
    }
    async function createBase(e) {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
            const created = await api("/api/admin/knowledge/bases", {
                method: "POST",
                body: JSON.stringify({
                    name,
                    slug,
                    description: description || undefined,
                    sensitivity,
                    access_type: accessType,
                }),
            });
            setCreateOpen(false);
            setName("");
            setSlug("");
            setDescription("");
            await loadBases();
            setSelectedId(created.id);
            setFlash("Knowledge Base created.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    function resetUploadForm() {
        setUploadFiles([]);
        setUploadTitle("");
        if (fileInput.current)
            fileInput.current.value = "";
    }
    function onUploadFilesChange(files) {
        const selected = Array.from(files || []);
        if (selected.length > MAX_KNOWLEDGE_UPLOAD_FILES) {
            resetUploadForm();
            setError(`You can upload at most ${MAX_KNOWLEDGE_UPLOAD_FILES} files at a time. ` +
                `You selected ${selected.length}. Please choose ${MAX_KNOWLEDGE_UPLOAD_FILES} or fewer and try again.`);
            return;
        }
        setError("");
        setUploadFiles(selected);
        if (selected.length !== 1)
            setUploadTitle("");
    }
    async function uploadDocument(e) {
        e.preventDefault();
        if (!detail || uploadFiles.length === 0)
            return;
        if (uploadFiles.length > MAX_KNOWLEDGE_UPLOAD_FILES) {
            setError(`You can upload at most ${MAX_KNOWLEDGE_UPLOAD_FILES} files at a time. ` +
                `Please choose ${MAX_KNOWLEDGE_UPLOAD_FILES} or fewer and try again.`);
            return;
        }
        setBusy(true);
        setError("");
        const failures = [];
        let accepted = 0;
        setUploadProgress({ current: 0, total: uploadFiles.length });
        try {
            for (const [index, file] of uploadFiles.entries()) {
                setUploadProgress({ current: index + 1, total: uploadFiles.length });
                const body = new FormData();
                body.append("file", file);
                if (uploadFiles.length === 1 && uploadTitle.trim()) {
                    body.append("title", uploadTitle.trim());
                }
                body.append("classification", detail.sensitivity);
                try {
                    await api(`/api/admin/knowledge/bases/${detail.id}/documents`, {
                        method: "POST",
                        body,
                    });
                    accepted += 1;
                }
                catch (err) {
                    failures.push(`${file.name}: ${String(err)}`);
                }
            }
            resetUploadForm();
            if (accepted > 0) {
                await reload(accepted === 1
                    ? "Document accepted for secure ingestion."
                    : `${accepted} documents accepted for secure ingestion.`);
            }
            else {
                await reload();
            }
            if (failures.length) {
                setError(accepted > 0
                    ? `${accepted} uploaded; ${failures.length} failed: ${failures.join("; ")}`
                    : failures.join("; "));
            }
        }
        finally {
            setUploadProgress(null);
            setBusy(false);
        }
    }
    async function approveDocument(versionId) {
        const reason = await prompt({
            title: "Approve document version",
            message: "Approve this document version so it can be included in a Knowledge release?",
            promptLabel: "Approval reason",
            promptDefault: "Reviewed for publication",
            confirmLabel: "Approve",
        });
        if (!reason?.trim())
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/document-versions/${versionId}/approve`, {
                method: "POST",
                body: JSON.stringify({ reason: reason.trim() }),
            });
            await reload("Document version approved.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function revokeDocument(documentId, title) {
        const reason = await prompt({
            title: "Revoke document",
            message: `Revoke “${title}” so it leaves retrieval immediately?`,
            promptLabel: "Reason",
            promptDefault: "Removed from Knowledge Base",
            confirmLabel: "Continue",
            danger: true,
        });
        if (!reason?.trim())
            return;
        const purgeChoice = await confirm({
            title: "Purge storage?",
            message: "Revoke from retrieval now. Optionally also purge vectors/objects asynchronously.",
            confirmLabel: "Revoke only",
            secondaryLabel: "Revoke + purge now",
            danger: true,
        });
        if (!purgeChoice)
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/documents/${documentId}/revoke`, {
                method: "POST",
                body: JSON.stringify({
                    reason: reason.trim(),
                    purge_now: purgeChoice === "secondary",
                }),
            });
            await reload(purgeChoice === "secondary"
                ? "Document revoked; purge jobs queued."
                : "Document revoked from retrieval.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function pauseConnector(connectorId) {
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/connectors/${connectorId}`, {
                method: "PATCH",
                body: JSON.stringify({ status: "paused" }),
            });
            await reload("Connector paused.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function resumeConnector(connectorId) {
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/connectors/${connectorId}`, {
                method: "PATCH",
                body: JSON.stringify({ status: "active" }),
            });
            await reload("Connector resumed.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function disableConnector(connectorId, name) {
        const reason = await prompt({
            title: "Disable connector",
            message: `Disable “${name}” and revoke content ingested from its URLs?`,
            promptLabel: "Reason",
            promptDefault: "Connector decommissioned",
            confirmLabel: "Continue",
            danger: true,
        });
        if (!reason?.trim())
            return;
        const purgeChoice = await confirm({
            title: "Purge connector content?",
            message: "Revoke connector documents now. Optionally also purge vectors/objects asynchronously.",
            confirmLabel: "Disable + revoke",
            secondaryLabel: "Disable + revoke + purge",
            danger: true,
        });
        if (!purgeChoice)
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/connectors/${connectorId}/disable`, {
                method: "POST",
                body: JSON.stringify({
                    reason: reason.trim(),
                    revoke_content: true,
                    archive: true,
                    purge_now: purgeChoice === "secondary",
                }),
            });
            await reload("Connector disabled and content revoked.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function archiveKnowledgeBase() {
        if (!detail)
            return;
        const reason = await prompt({
            title: "Archive Knowledge Base",
            message: `Archive “${detail.name}” and revoke its documents/connectors? This removes the KB from active use but keeps records.`,
            promptLabel: "Reason",
            promptDefault: "Knowledge Base retired",
            confirmLabel: "Archive",
            danger: true,
        });
        if (!reason?.trim())
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/bases/${detail.id}/delete`, {
                method: "POST",
                body: JSON.stringify({
                    reason: reason.trim(),
                    mode: "archive_and_revoke",
                    purge_now: false,
                }),
            });
            await reload("Knowledge Base archived and content revoked.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function hardDeleteKnowledgeBase() {
        if (!detail)
            return;
        const typed = await prompt({
            title: "Delete permanently?",
            message: `This permanently deletes “${detail.name}” and all of its documents, releases, indexes, vectors, and stored files. ` +
                "This cannot be undone.",
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
            setError("Knowledge Base name did not match. Deletion cancelled.");
            return;
        }
        const reason = await prompt({
            title: "Deletion reason",
            message: `Provide a short reason for permanently deleting “${detail.name}”.`,
            promptLabel: "Reason",
            promptDefault: "Created by mistake",
            confirmLabel: "Continue",
            danger: true,
        });
        if (!reason?.trim())
            return;
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}/hard-delete`, {
                method: "POST",
                body: JSON.stringify({
                    confirm_name: detail.name,
                    reason: reason.trim(),
                }),
            });
            setSelectedId("");
            setDetail(null);
            await loadBases();
            setFlash(`Knowledge Base “${detail.name}” permanently deleted.`);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function saveRetention() {
        if (!detail)
            return;
        const trimmed = retentionDaysInput.trim();
        let retentionDays = null;
        if (trimmed) {
            const parsed = Number(trimmed);
            if (!Number.isInteger(parsed) || parsed < 1 || parsed > 36500) {
                setError("Retention days must be an integer from 1 to 36500, or empty to disable.");
                return;
            }
            retentionDays = parsed;
        }
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}`, {
                method: "PATCH",
                body: JSON.stringify({ retention_days: retentionDays }),
            });
            await reload(retentionDays == null
                ? "Automatic retention cleanup disabled for this Knowledge Base."
                : `Retention set to ${retentionDays} day${retentionDays === 1 ? "" : "s"} after revoke.`);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function runRetentionCleanup() {
        if (!detail)
            return;
        if (detail.retention_days == null) {
            setError("Save a retention period before running cleanup.");
            return;
        }
        const ok = await confirm({
            title: "Run cleanup?",
            message: `Delete revoked documents in “${detail.name}” that are older than ` +
                `${detail.retention_days} day${detail.retention_days === 1 ? "" : "s"}. ` +
                "Stored files and vectors are removed. Documents under legal hold are skipped.",
            confirmLabel: "Run cleanup",
            danger: true,
        });
        if (!ok)
            return;
        setBusy(true);
        setError("");
        try {
            const result = await api(`/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}/retention/cleanup`, { method: "POST" });
            await reload(`Cleanup finished: ${result.purged_versions} version(s) removed` +
                (result.failed_versions ? `, ${result.failed_versions} failed` : "") +
                (result.held_resources ? `, ${result.held_resources} held` : "") +
                (result.not_expired_documents
                    ? `, ${result.not_expired_documents} still within retention`
                    : "") +
                ".");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function createRelease() {
        if (!detail)
            return;
        const versionIds = (detail.documents || [])
            .map((document) => document.versions.find((version) => ["review", "published"].includes(version.status)))
            .filter((version) => version?.status === "review" || version?.status === "published")
            .map((version) => version.id);
        if (!versionIds.length) {
            setError("Approve at least one document version before creating a release.");
            return;
        }
        const summary = await prompt({
            title: "Create Knowledge release",
            message: "Create an immutable release draft from approved/published document versions. You must then submit it for indexing before Agents can retrieve it.",
            promptLabel: "Change summary",
            promptDefault: "Publish reviewed knowledge",
            confirmLabel: "Create release",
        });
        if (!summary?.trim())
            return;
        setBusy(true);
        try {
            const release = await api(`/api/admin/knowledge/bases/${detail.id}/releases`, {
                method: "POST",
                body: JSON.stringify({ document_version_ids: versionIds, change_summary: summary }),
            });
            await reload("Release draft created. Submit it for indexing so Agents can use these documents.");
            const shouldIndex = await confirm({
                title: "Index this release now?",
                message: "Without indexing into Qdrant, Agents with fail-closed retrieval will refuse to answer from these documents.",
                confirmLabel: "Submit for indexing",
                cancelLabel: "Later",
            });
            if (shouldIndex === true) {
                await submitRelease(release.id);
            }
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function submitRelease(releaseId) {
        const model = embeddingModels.find((row) => String(row.id) === selectedEmbeddingId);
        if (!model) {
            setError("Select an embedding model before submitting a release for indexing.");
            return;
        }
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/releases/${releaseId}/submit`, {
                method: "POST",
                body: JSON.stringify({
                    embedding_provider: model.provider,
                    embedding_model: model.external_id,
                    embedding_dimensions: model.suggested_dimensions,
                    embedding_fingerprint: model.embedding_fingerprint,
                    sparse_profile: { algorithm: "bm25" },
                }),
            });
            await reload(`Indexing queued with ${model.external_id}. Wait for the index status to become active before chatting.`);
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function addHttpConnector(e) {
        e.preventDefault();
        if (!detail)
            return;
        const urls = connectorUrls.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
        if (!urls.length)
            return;
        setBusy(true);
        try {
            await api(`/api/admin/knowledge/bases/${detail.id}/connectors`, {
                method: "POST",
                body: JSON.stringify({
                    connector_type: "http",
                    name: connectorName,
                    config: { urls },
                    activate: true,
                }),
            });
            setConnectorName("");
            setConnectorUrls("");
            await reload("HTTP connector created.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function syncConnector(connectorId) {
        setBusy(true);
        try {
            await api(`/api/admin/knowledge/connectors/${connectorId}/sync`, {
                method: "POST",
            });
            await reload("Connector synchronization queued.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function retryJob(jobId) {
        setBusy(true);
        try {
            await api(`/api/admin/knowledge/jobs/${jobId}/retry`, { method: "POST" });
            await reload("Ingestion job queued for retry.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function retryFailedIndex(indexId) {
        setBusy(true);
        setError("");
        try {
            await api(`/api/admin/knowledge/indexes/${indexId}/retry`, { method: "POST" });
            await reload("Index rebuild queued.");
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setBusy(false);
        }
    }
    const documentVersions = useMemo(() => (detail?.documents || []).flatMap((document) => document.versions.map((version) => ({ document, version }))), [detail]);
    const publishedDocCount = useMemo(() => (detail?.documents || []).filter((document) => document.versions.some((version) => version.status === "published")).length, [detail]);
    const hasActiveIndex = useMemo(() => (detail?.indexes || []).some((index) => index.status === "active"), [detail]);
    return (_jsxs(AdminPage, { title: "Knowledge Bases", actions: _jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void reload(), children: "Refresh" }), _jsx("button", { type: "button", className: "btn", onClick: () => setCreateOpen(true), children: "New Knowledge Base" })] }), children: [error ? _jsx("div", { className: "error", children: error }) : null, flash ? _jsx("div", { className: "success", children: flash }) : null, _jsxs("div", { className: "knowledge-layout", "aria-busy": loading, children: [_jsxs("aside", { className: "knowledge-list", children: [bases.map((knowledgeBase) => (_jsxs("button", { type: "button", className: selectedId === knowledgeBase.id ? "is-selected" : "", onClick: () => setSelectedId(knowledgeBase.id), children: [_jsxs("span", { children: [_jsx("strong", { children: knowledgeBase.name }), _jsx("small", { children: humanAgentStatus(knowledgeBase.sensitivity) })] }), _jsx("em", { children: knowledgeBase.document_count })] }, knowledgeBase.id))), !loading && bases.length === 0 ? _jsx("p", { className: "agent-empty", children: "No Knowledge Bases." }) : null] }), _jsx("section", { className: "knowledge-detail", children: !detail ? (_jsxs("div", { className: "agent-empty-state", children: [_jsx("h2", { children: "Select or create a Knowledge Base" }), _jsx("p", { children: "Each base is an independent security, retention, and publication boundary." })] })) : (_jsxs(_Fragment, { children: [_jsxs("div", { className: "agent-studio-title", children: [_jsxs("div", { children: [_jsx("h2", { children: detail.name }), _jsxs("p", { children: [detail.description || "No description", " \u00B7 ", detail.access_type, " \u00B7", " ", humanAgentStatus(detail.sensitivity), " \u00B7", " ", _jsx("span", { className: `agent-status ${agentStatusTone(detail.status)}`, children: humanAgentStatus(detail.status) })] })] }), _jsxs("div", { className: "agent-studio-title-actions", children: [_jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void createRelease(), children: "Create release" }), _jsx(RowActionsMenu, { actions: [
                                                        ...(detail.status !== "archived"
                                                            ? [
                                                                {
                                                                    label: "Archive",
                                                                    disabled: busy,
                                                                    onClick: () => void archiveKnowledgeBase(),
                                                                },
                                                            ]
                                                            : []),
                                                        {
                                                            label: "Delete permanently",
                                                            danger: true,
                                                            disabled: busy,
                                                            onClick: () => void hardDeleteKnowledgeBase(),
                                                        },
                                                    ] })] })] }), _jsxs("div", { className: "knowledge-summary", children: [_jsxs("span", { children: [_jsx("strong", { children: detail.documents?.length || 0 }), " Documents"] }), _jsxs("span", { children: [_jsx("strong", { children: detail.releases?.length || 0 }), " Releases"] }), _jsxs("span", { children: [_jsx("strong", { children: (detail.indexes || []).filter((index) => index.status === "active").length }), " Active indexes"] }), _jsxs("span", { children: [_jsx("strong", { children: detail.jobs?.filter((job) => job.status === "dead").length || 0 }), " Dead jobs"] })] }), publishedDocCount > 0 && !hasActiveIndex ? (_jsx("div", { className: "error", children: "Approved documents are not searchable yet. Create a release and submit it for indexing (embedding into Qdrant). Until an active index exists, Agents with fail-closed retrieval will answer that no organizational evidence was found." })) : null, _jsxs("section", { className: "agent-section-card", children: [_jsx("div", { className: "agent-section-card__head", children: _jsxs("div", { children: [_jsx("h3", { children: "Releases & indexing" }), _jsx("p", { children: "Agents retrieve only from an active indexed release, not from uploaded/approved files alone." })] }) }), _jsxs("label", { className: "knowledge-embed-picker", children: ["Embedding model for indexing", _jsx(SearchableModelSelect, { ariaLabel: "Embedding model for indexing", value: selectedEmbeddingId, disabled: busy || embeddingModels.length === 0, allowEmpty: false, emptyLabel: "No enabled embedding models found", placeholder: "Search embedding models\u2026", options: embeddingModels.map((model) => ({
                                                        value: String(model.id),
                                                        label: embeddingModelOptionLabel(model.external_id, model.provider, model.suggested_dimensions),
                                                    })), onChange: setSelectedEmbeddingId })] }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Release" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Summary" }), _jsx("th", { children: "Created" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [(detail.releases || []).map((release) => (_jsxs("tr", { children: [_jsxs("td", { children: ["v", release.version_number] }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(release.status)}`, children: humanAgentStatus(release.status) }) }), _jsx("td", { children: release.change_summary || "—" }), _jsx("td", { children: readableDate(release.created_at) }), _jsx("td", { children: release.status === "draft" ? (_jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy || !selectedEmbeddingId, onClick: () => void submitRelease(release.id), children: "Submit index" })) : null })] }, release.id))), (detail.releases || []).length === 0 ? (_jsx("tr", { children: _jsx("td", { colSpan: 5, children: "No releases yet. Click Create release after approving documents." }) })) : null] })] }) }), (detail.indexes || []).length > 0 ? (_jsx("div", { className: "table-wrap", style: { marginTop: "0.75rem" }, children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Index" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Model" }), _jsx("th", { children: "Points" }), _jsx("th", { children: "Failure" }), _jsx("th", {})] }) }), _jsx("tbody", { children: (detail.indexes || []).map((index) => (_jsxs("tr", { children: [_jsxs("td", { children: ["v", index.version_number] }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(index.status)}`, children: humanAgentStatus(index.status) }) }), _jsx("td", { children: index.embedding_model || "—" }), _jsxs("td", { children: [index.indexed_point_count ?? 0, "/", index.expected_point_count ?? 0] }), _jsx("td", { children: index.failure_reason || "—" }), _jsx("td", { children: index.status === "failed" ? (_jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => void retryFailedIndex(index.id), children: "Retry" })) : null })] }, index.id))) })] }) })) : null] }), _jsx(ResourceAccessEditor, { title: "Who can use this Knowledge Base", loadPath: `/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}/access`, savePath: `/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}/access`, disabled: busy, onError: setError, onSaved: () => void reload("Knowledge Base access updated.") }), _jsxs("section", { className: "agent-section-card", children: [_jsx("div", { className: "agent-section-card__head", children: _jsxs("div", { children: [_jsx("h3", { children: "Retention" }), _jsx("p", { children: "After a document is revoked, keep its stored files and vectors for this many days, then clean them up automatically." })] }) }), _jsxs("div", { className: "knowledge-retention-form", children: [_jsxs("label", { children: ["Days after revoke", _jsx("input", { type: "number", min: 1, max: 36500, step: 1, placeholder: "Disabled", value: retentionDaysInput, disabled: busy, onChange: (e) => setRetentionDaysInput(e.target.value) })] }), _jsxs("div", { className: "agent-inline-form", children: [_jsx("button", { type: "button", className: "btn", disabled: busy, onClick: () => void saveRetention(), children: "Save retention" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy || detail.retention_days == null, onClick: () => void runRetentionCleanup(), title: detail.retention_days == null
                                                                ? "Save a retention period first"
                                                                : "Delete revoked documents past retention", children: "Run cleanup" })] })] }), _jsx("p", { className: "agent-table-sub", children: detail.retention_days != null
                                                ? `Current: ${detail.retention_days} day${detail.retention_days === 1 ? "" : "s"} after revoke. Leave empty and save to disable automatic cleanup.`
                                                : "Automatic cleanup is disabled until you set and save a retention period." })] }), _jsxs("section", { className: "agent-section-card", children: [_jsx("h3", { children: "Upload document" }), _jsxs("form", { className: "knowledge-upload-form", onSubmit: uploadDocument, children: [_jsx("input", { ref: fileInput, required: true, type: "file", multiple: true, onChange: (e) => onUploadFilesChange(e.target.files), disabled: busy }), uploadFiles.length <= 1 ? (_jsx("input", { placeholder: "Optional document title", value: uploadTitle, onChange: (e) => setUploadTitle(e.target.value), disabled: busy })) : (_jsxs("p", { className: "knowledge-upload-hint", children: [uploadFiles.length, " files selected. Titles will use each file name."] })), _jsx("button", { className: "btn", disabled: uploadFiles.length === 0 || busy, children: uploadProgress
                                                        ? `Uploading ${uploadProgress.current} of ${uploadProgress.total}…`
                                                        : uploadFiles.length > 1
                                                            ? `Upload ${uploadFiles.length} files`
                                                            : "Upload" })] }), _jsxs("p", { className: "agent-table-sub", children: ["Up to ", MAX_KNOWLEDGE_UPLOAD_FILES, " files per upload. An optional title is available only when uploading a single file."] })] }), _jsxs("section", { className: "agent-section-card", children: [_jsx("h3", { children: "Documents" }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Document" }), _jsx("th", { children: "Version" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Class" }), _jsx("th", { children: "Uploaded" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [documentVersions.map(({ document, version }) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: document.title }), _jsx("small", { className: "agent-table-sub", children: version.file_name }), _jsxs("small", { className: "agent-table-sub", children: ["Document: ", humanAgentStatus(document.status)] }), version.status === "failed" && version.failure_reason ? (_jsx("small", { className: "agent-table-sub error", children: version.failure_reason })) : null, version.status === "revoked" || document.status === "revoked" ? (_jsx("small", { className: "agent-table-sub error", children: "Revoked from retrieval" })) : null] }), _jsxs("td", { children: ["v", version.version_number] }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(version.status)}`, children: humanAgentStatus(version.status) }) }), _jsx("td", { children: humanAgentStatus(version.classification) }), _jsx("td", { children: readableDate(version.created_at) }), _jsxs("td", { children: [version.status === "review" ? (_jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => void approveDocument(version.id), children: "Approve" })) : null, !["revoked", "deleted"].includes(document.status) ? (_jsx("button", { type: "button", className: "btn btn-ghost", disabled: busy, onClick: () => void revokeDocument(document.id, document.title), children: "Revoke" })) : null] })] }, version.id))), documentVersions.length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 6, children: "No documents yet." }) }) : null] })] }) })] }), _jsxs("section", { className: "agent-section-card", children: [_jsx("h3", { children: "HTTP connector" }), _jsxs("form", { className: "knowledge-connector-form", onSubmit: addHttpConnector, children: [_jsx("input", { required: true, placeholder: "Connector name", value: connectorName, onChange: (e) => setConnectorName(e.target.value) }), _jsx("textarea", { required: true, rows: 1, placeholder: "One public HTTPS URL per line", value: connectorUrls, onChange: (e) => setConnectorUrls(e.target.value) }), _jsx("button", { className: "btn", disabled: busy, children: "Add connector" })] }), _jsx("div", { className: "agent-chip-list", children: (detail.connectors || []).map((connector) => (_jsxs("span", { className: "agent-binding-chip", children: [connector.name, _jsx("em", { className: `agent-status ${agentStatusTone(connector.status)}`, children: humanAgentStatus(connector.status) }), Array.isArray(connector.config?.urls) ? (_jsxs("small", { children: [connector.config.urls.length, " URL(s)"] })) : null, connector.status === "active" ? (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", disabled: busy, onClick: () => void syncConnector(connector.id), children: "Sync" }), _jsx("button", { type: "button", disabled: busy, onClick: () => void pauseConnector(connector.id), children: "Pause" })] })) : null, connector.status === "paused" ? (_jsx("button", { type: "button", disabled: busy, onClick: () => void resumeConnector(connector.id), children: "Resume" })) : null, connector.status !== "archived" ? (_jsx("button", { type: "button", disabled: busy, onClick: () => void disableConnector(connector.id, connector.name), children: "Delete" })) : null] }, connector.id))) })] }), _jsxs("section", { className: "agent-section-card", children: [_jsx("h3", { children: "Ingestion operations" }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Job" }), _jsx("th", { children: "Type" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Attempts" }), _jsx("th", { children: "Created" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [(detail.jobs || []).map((job) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("code", { children: job.id.slice(0, 8) }) }), _jsx("td", { children: humanAgentStatus(job.job_type) }), _jsx("td", { children: _jsx("span", { className: `agent-status ${agentStatusTone(job.status)}`, children: humanAgentStatus(job.status) }) }), _jsxs("td", { children: [job.attempt_count, "/", job.max_attempts] }), _jsx("td", { children: readableDate(job.created_at) }), _jsx("td", { children: job.status === "dead" ? _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void retryJob(job.id), children: "Retry" }) : null })] }, job.id))), (detail.jobs || []).length === 0 ? _jsx("tr", { children: _jsx("td", { colSpan: 6, children: "No ingestion jobs." }) }) : null] })] }) })] })] })) })] }), _jsx(Modal, { open: createOpen, title: "New Knowledge Base", onClose: () => !busy && setCreateOpen(false), panelClassName: "modal-panel--agent", children: _jsxs("form", { className: "agent-modal-form", onSubmit: createBase, children: [_jsxs("label", { children: ["Name", _jsx("input", { required: true, value: name, onChange: (e) => {
                                        setName(e.target.value);
                                        if (!slug)
                                            setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
                                    } })] }), _jsxs("label", { children: ["Slug", _jsx("input", { required: true, value: slug, onChange: (e) => setSlug(e.target.value) })] }), _jsxs("label", { children: ["Description", _jsx("textarea", { rows: 3, value: description, onChange: (e) => setDescription(e.target.value) })] }), _jsxs("label", { children: ["Sensitivity", _jsxs("select", { value: sensitivity, onChange: (e) => setSensitivity(e.target.value), children: [_jsx("option", { value: "internal", children: "Internal" }), _jsx("option", { value: "confidential", children: "Confidential" }), _jsx("option", { value: "hr_confidential", children: "HR confidential" }), _jsx("option", { value: "legal_privileged", children: "Legal privileged" }), _jsx("option", { value: "finance_restricted", children: "Finance restricted" })] })] }), _jsxs("label", { children: ["Access", _jsxs("select", { value: accessType, onChange: (e) => setAccessType(e.target.value), children: [_jsx("option", { value: "private", children: "Private" }), _jsx("option", { value: "public", children: "Public" })] })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => setCreateOpen(false), children: "Cancel" }), _jsx("button", { className: "btn", disabled: busy, children: busy ? "Creating…" : "Create" })] })] }) })] }));
}
