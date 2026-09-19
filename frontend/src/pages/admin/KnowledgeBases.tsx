import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiList, NO_LIST_BOUNDS, type ListBounds } from "../../api";
import ListTruncatedBanner from "../../components/ListTruncatedBanner";
import AdminPage from "../../components/AdminPage";
import ResourceAccessEditor from "../../components/admin/ResourceAccessEditor";
import SearchableModelSelect from "../../components/admin/SearchableModelSelect";
import Modal from "../../components/Modal";
import RowActionsMenu, { RowAction } from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import {
  KnowledgeBaseRecord,
  KnowledgeEmbeddingModel,
  agentStatusTone,
  humanAgentStatus,
  readableDate,
} from "../../lib/agentPlatform";
import { embeddingModelOptionLabel } from "../../lib/embeddingDimensions";

const MAX_KNOWLEDGE_UPLOAD_FILES = 20;

export default function KnowledgeBases() {
  const { confirm, prompt } = useConfirm();
  const [bases, setBases] = useState<KnowledgeBaseRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<KnowledgeBaseRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bounds, setBounds] = useState<ListBounds>(NO_LIST_BOUNDS);
  const [flash, setFlash] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [sensitivity, setSensitivity] = useState("internal");
  const [accessType, setAccessType] = useState<"public" | "private">("private");
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number } | null>(null);
  const [connectorName, setConnectorName] = useState("");
  const [connectorUrls, setConnectorUrls] = useState("");
  const [embeddingModels, setEmbeddingModels] = useState<KnowledgeEmbeddingModel[]>([]);
  const [selectedEmbeddingId, setSelectedEmbeddingId] = useState("");
  const [retentionDaysInput, setRetentionDaysInput] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);

  const loadBases = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data: rows, bounds } = await apiList<KnowledgeBaseRecord[]>("/api/admin/knowledge/bases");
      setBases(rows);
      setBounds(bounds);
      setSelectedId((current) =>
        current && rows.some((row) => row.id === current) ? current : rows[0]?.id || "",
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    if (!id) {
      setDetail(null);
      setRetentionDaysInput("");
      return;
    }
    try {
      const next = await api<KnowledgeBaseRecord>(
        `/api/admin/knowledge/bases/${encodeURIComponent(id)}`,
      );
      setDetail(next);
      setRetentionDaysInput(
        next.retention_days != null && next.retention_days > 0
          ? String(next.retention_days)
          : "",
      );
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void loadBases();
    api<KnowledgeEmbeddingModel[]>("/api/admin/knowledge/embedding-models")
      .then((rows) => {
        setEmbeddingModels(rows);
        setSelectedEmbeddingId((current) => {
          if (current && rows.some((row) => String(row.id) === current)) return current;
          const preferred =
            rows.find((row) => row.external_id.includes("text-embedding-3-small"))
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

  async function reload(message?: string) {
    await loadBases();
    if (selectedId) await loadDetail(selectedId);
    if (message) setFlash(message);
  }

  async function createBase(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<KnowledgeBaseRecord>("/api/admin/knowledge/bases", {
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function resetUploadForm() {
    setUploadFiles([]);
    setUploadTitle("");
    if (fileInput.current) fileInput.current.value = "";
  }

  function onUploadFilesChange(files: FileList | null) {
    const selected = Array.from(files || []);
    if (selected.length > MAX_KNOWLEDGE_UPLOAD_FILES) {
      resetUploadForm();
      setError(
        `You can upload at most ${MAX_KNOWLEDGE_UPLOAD_FILES} files at a time. ` +
          `You selected ${selected.length}. Please choose ${MAX_KNOWLEDGE_UPLOAD_FILES} or fewer and try again.`,
      );
      return;
    }
    setError("");
    setUploadFiles(selected);
    if (selected.length !== 1) setUploadTitle("");
  }

  async function uploadDocument(e: FormEvent) {
    e.preventDefault();
    if (!detail || uploadFiles.length === 0) return;
    if (uploadFiles.length > MAX_KNOWLEDGE_UPLOAD_FILES) {
      setError(
        `You can upload at most ${MAX_KNOWLEDGE_UPLOAD_FILES} files at a time. ` +
          `Please choose ${MAX_KNOWLEDGE_UPLOAD_FILES} or fewer and try again.`,
      );
      return;
    }
    setBusy(true);
    setError("");
    const failures: string[] = [];
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
        } catch (err) {
          failures.push(`${file.name}: ${String(err)}`);
        }
      }
      resetUploadForm();
      if (accepted > 0) {
        await reload(
          accepted === 1
            ? "Document accepted for secure ingestion."
            : `${accepted} documents accepted for secure ingestion.`,
        );
      } else {
        await reload();
      }
      if (failures.length) {
        setError(
          accepted > 0
            ? `${accepted} uploaded; ${failures.length} failed: ${failures.join("; ")}`
            : failures.join("; "),
        );
      }
    } finally {
      setUploadProgress(null);
      setBusy(false);
    }
  }

  async function approveDocument(versionId: string) {
    const reason = await prompt({
      title: "Approve document version",
      message: "Approve this document version so it can be included in a Knowledge release?",
      promptLabel: "Approval reason",
      promptDefault: "Reviewed for publication",
      confirmLabel: "Approve",
    });
    if (!reason?.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/admin/knowledge/document-versions/${versionId}/approve`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      await reload("Document version approved.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function revokeDocument(documentId: string, title: string) {
    const reason = await prompt({
      title: "Revoke document",
      message: `Revoke “${title}” so it leaves retrieval immediately?`,
      promptLabel: "Reason",
      promptDefault: "Removed from Knowledge Base",
      confirmLabel: "Continue",
      danger: true,
    });
    if (!reason?.trim()) return;
    const purgeChoice = await confirm({
      title: "Purge storage?",
      message: "Revoke from retrieval now. Optionally also purge vectors/objects asynchronously.",
      confirmLabel: "Revoke only",
      secondaryLabel: "Revoke + purge now",
      danger: true,
    });
    if (!purgeChoice) return;
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
      await reload(
        purgeChoice === "secondary"
          ? "Document revoked; purge jobs queued."
          : "Document revoked from retrieval.",
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function pauseConnector(connectorId: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/api/admin/knowledge/connectors/${connectorId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "paused" }),
      });
      await reload("Connector paused.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function resumeConnector(connectorId: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/api/admin/knowledge/connectors/${connectorId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "active" }),
      });
      await reload("Connector resumed.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function disableConnector(connectorId: string, name: string) {
    const reason = await prompt({
      title: "Disable connector",
      message: `Disable “${name}” and revoke content ingested from its URLs?`,
      promptLabel: "Reason",
      promptDefault: "Connector decommissioned",
      confirmLabel: "Continue",
      danger: true,
    });
    if (!reason?.trim()) return;
    const purgeChoice = await confirm({
      title: "Purge connector content?",
      message: "Revoke connector documents now. Optionally also purge vectors/objects asynchronously.",
      confirmLabel: "Disable + revoke",
      secondaryLabel: "Disable + revoke + purge",
      danger: true,
    });
    if (!purgeChoice) return;
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function archiveKnowledgeBase() {
    if (!detail) return;
    const reason = await prompt({
      title: "Archive Knowledge Base",
      message: `Archive “${detail.name}” and revoke its documents/connectors? This removes the KB from active use but keeps records.`,
      promptLabel: "Reason",
      promptDefault: "Knowledge Base retired",
      confirmLabel: "Archive",
      danger: true,
    });
    if (!reason?.trim()) return;
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function hardDeleteKnowledgeBase() {
    if (!detail) return;
    const typed = await prompt({
      title: "Delete permanently?",
      message:
        `This permanently deletes “${detail.name}” and all of its documents, releases, indexes, vectors, and stored files. ` +
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
    if (typed == null) return;
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
    if (!reason?.trim()) return;
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveRetention() {
    if (!detail) return;
    const trimmed = retentionDaysInput.trim();
    let retentionDays: number | null = null;
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
      await reload(
        retentionDays == null
          ? "Automatic retention cleanup disabled for this Knowledge Base."
          : `Retention set to ${retentionDays} day${retentionDays === 1 ? "" : "s"} after revoke.`,
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runRetentionCleanup() {
    if (!detail) return;
    if (detail.retention_days == null) {
      setError("Save a retention period before running cleanup.");
      return;
    }
    const ok = await confirm({
      title: "Run cleanup?",
      message:
        `Delete revoked documents in “${detail.name}” that are older than ` +
        `${detail.retention_days} day${detail.retention_days === 1 ? "" : "s"}. ` +
        "Stored files and vectors are removed. Documents under legal hold are skipped.",
      confirmLabel: "Run cleanup",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{
        scheduled_versions: number;
        purged_versions: number;
        failed_versions: number;
        held_resources: number;
        not_expired_documents: number;
      }>(
        `/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}/retention/cleanup`,
        { method: "POST" },
      );
      await reload(
        `Cleanup finished: ${result.purged_versions} version(s) removed` +
          (result.failed_versions ? `, ${result.failed_versions} failed` : "") +
          (result.held_resources ? `, ${result.held_resources} held` : "") +
          (result.not_expired_documents
            ? `, ${result.not_expired_documents} still within retention`
            : "") +
          ".",
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function createRelease() {
    if (!detail) return;
    const versionIds = (detail.documents || [])
      .map((document) =>
        document.versions.find((version) => ["review", "published"].includes(version.status)),
      )
      .filter((version) => version?.status === "review" || version?.status === "published")
      .map((version) => version!.id);
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
    if (!summary?.trim()) return;
    setBusy(true);
    try {
      const release = await api<{ id: string }>(`/api/admin/knowledge/bases/${detail.id}/releases`, {
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitRelease(releaseId: string) {
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
      await reload(
        `Indexing queued with ${model.external_id}. Wait for the index status to become active before chatting.`,
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function addHttpConnector(e: FormEvent) {
    e.preventDefault();
    if (!detail) return;
    const urls = connectorUrls.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
    if (!urls.length) return;
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function syncConnector(connectorId: string) {
    setBusy(true);
    try {
      await api(`/api/admin/knowledge/connectors/${connectorId}/sync`, {
        method: "POST",
      });
      await reload("Connector synchronization queued.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function retryJob(jobId: string) {
    setBusy(true);
    try {
      await api(`/api/admin/knowledge/jobs/${jobId}/retry`, { method: "POST" });
      await reload("Ingestion job queued for retry.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function retryFailedIndex(indexId: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/api/admin/knowledge/indexes/${indexId}/retry`, { method: "POST" });
      await reload("Index rebuild queued.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  const documentVersions = useMemo(
    () => (detail?.documents || []).flatMap((document) =>
      document.versions.map((version) => ({ document, version })),
    ),
    [detail],
  );

  const publishedDocCount = useMemo(
    () =>
      (detail?.documents || []).filter((document) =>
        document.versions.some((version) => version.status === "published"),
      ).length,
    [detail],
  );

  const hasActiveIndex = useMemo(
    () => (detail?.indexes || []).some((index) => index.status === "active"),
    [detail],
  );

  return (
    <AdminPage
      title="Knowledge Bases"
      actions={
        <>
          <button type="button" className="btn btn-ghost" onClick={() => void reload()}>
            Refresh
          </button>
          <button type="button" className="btn" onClick={() => setCreateOpen(true)}>
            New Knowledge Base
          </button>
        </>
      }
    >
      {error ? <div className="error">{error}</div> : null}
      <ListTruncatedBanner bounds={bounds} noun="knowledge bases" />
      {flash ? <div className="success">{flash}</div> : null}
      <div className="knowledge-layout" aria-busy={loading}>
        <aside className="knowledge-list">
          {bases.map((knowledgeBase) => (
            <button
              key={knowledgeBase.id}
              type="button"
              className={selectedId === knowledgeBase.id ? "is-selected" : ""}
              onClick={() => setSelectedId(knowledgeBase.id)}
            >
              <span>
                <strong>{knowledgeBase.name}</strong>
                <small>{humanAgentStatus(knowledgeBase.sensitivity)}</small>
              </span>
              <em>{knowledgeBase.document_count}</em>
            </button>
          ))}
          {!loading && bases.length === 0 ? <p className="agent-empty">No Knowledge Bases.</p> : null}
        </aside>

        <section className="knowledge-detail">
          {!detail ? (
            <div className="agent-empty-state">
              <h2>Select or create a Knowledge Base</h2>
              <p>Each base is an independent security, retention, and publication boundary.</p>
            </div>
          ) : (
            <>
              <div className="agent-studio-title">
                <div>
                  <h2>{detail.name}</h2>
                  <p>
                    {detail.description || "No description"} · {detail.access_type} ·{" "}
                    {humanAgentStatus(detail.sensitivity)} ·{" "}
                    <span className={`agent-status ${agentStatusTone(detail.status)}`}>
                      {humanAgentStatus(detail.status)}
                    </span>
                  </p>
                </div>
                <div className="agent-studio-title-actions">
                  <button type="button" className="btn" disabled={busy} onClick={() => void createRelease()}>
                    Create release
                  </button>
                  <RowActionsMenu
                    actions={[
                      ...(detail.status !== "archived"
                        ? [
                            {
                              label: "Archive",
                              disabled: busy,
                              onClick: () => void archiveKnowledgeBase(),
                            } satisfies RowAction,
                          ]
                        : []),
                      {
                        label: "Delete permanently",
                        danger: true,
                        disabled: busy,
                        onClick: () => void hardDeleteKnowledgeBase(),
                      },
                    ]}
                  />
                </div>
              </div>

              <div className="knowledge-summary">
                <span><strong>{detail.documents?.length || 0}</strong> Documents</span>
                <span><strong>{detail.releases?.length || 0}</strong> Releases</span>
                <span><strong>{(detail.indexes || []).filter((index) => index.status === "active").length}</strong> Active indexes</span>
                <span><strong>{detail.jobs?.filter((job) => job.status === "dead").length || 0}</strong> Dead jobs</span>
              </div>

              {publishedDocCount > 0 && !hasActiveIndex ? (
                <div className="error">
                  Approved documents are not searchable yet. Create a release and submit it for indexing
                  (embedding into Qdrant). Until an active index exists, Agents with fail-closed retrieval
                  will answer that no organizational evidence was found.
                </div>
              ) : null}

              <section className="agent-section-card">
                <div className="agent-section-card__head">
                  <div>
                    <h3>Releases & indexing</h3>
                    <p>Agents retrieve only from an active indexed release, not from uploaded/approved files alone.</p>
                  </div>
                </div>
                <label className="knowledge-embed-picker">
                  Embedding model for indexing
                  <SearchableModelSelect
                    ariaLabel="Embedding model for indexing"
                    value={selectedEmbeddingId}
                    disabled={busy || embeddingModels.length === 0}
                    allowEmpty={false}
                    emptyLabel="No enabled embedding models found"
                    placeholder="Search embedding models…"
                    options={embeddingModels.map((model) => ({
                      value: String(model.id),
                      label: embeddingModelOptionLabel(
                        model.external_id,
                        model.provider,
                        model.suggested_dimensions,
                      ),
                    }))}
                    onChange={setSelectedEmbeddingId}
                  />
                </label>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Release</th><th>Status</th><th>Summary</th><th>Created</th><th /></tr>
                    </thead>
                    <tbody>
                      {(detail.releases || []).map((release) => (
                        <tr key={release.id}>
                          <td>v{release.version_number}</td>
                          <td>
                            <span className={`agent-status ${agentStatusTone(release.status)}`}>
                              {humanAgentStatus(release.status)}
                            </span>
                          </td>
                          <td>{release.change_summary || "—"}</td>
                          <td>{readableDate(release.created_at)}</td>
                          <td>
                            {release.status === "draft" ? (
                              <button
                                type="button"
                                className="btn btn-ghost"
                                disabled={busy || !selectedEmbeddingId}
                                onClick={() => void submitRelease(release.id)}
                              >
                                Submit index
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                      {(detail.releases || []).length === 0 ? (
                        <tr><td colSpan={5}>No releases yet. Click Create release after approving documents.</td></tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
                {(detail.indexes || []).length > 0 ? (
                  <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
                    <table>
                      <thead>
                        <tr><th>Index</th><th>Status</th><th>Model</th><th>Points</th><th>Failure</th><th /></tr>
                      </thead>
                      <tbody>
                        {(detail.indexes || []).map((index) => (
                          <tr key={index.id}>
                            <td>v{index.version_number}</td>
                            <td>
                              <span className={`agent-status ${agentStatusTone(index.status)}`}>
                                {humanAgentStatus(index.status)}
                              </span>
                            </td>
                            <td>{index.embedding_model || "—"}</td>
                            <td>{index.indexed_point_count ?? 0}/{index.expected_point_count ?? 0}</td>
                            <td>{index.failure_reason || "—"}</td>
                            <td>
                              {index.status === "failed" ? (
                                <button
                                  type="button"
                                  className="btn btn-ghost"
                                  disabled={busy}
                                  onClick={() => void retryFailedIndex(index.id)}
                                >
                                  Retry
                                </button>
                              ) : null}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </section>

              <ResourceAccessEditor
                title="Who can use this Knowledge Base"
                loadPath={`/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}/access`}
                savePath={`/api/admin/knowledge/bases/${encodeURIComponent(detail.id)}/access`}
                disabled={busy}
                onError={setError}
                onSaved={() => void reload("Knowledge Base access updated.")}
              />

              <section className="agent-section-card">
                <div className="agent-section-card__head">
                  <div>
                    <h3>Retention</h3>
                    <p>
                      After a document is revoked, keep its stored files and vectors for this many
                      days, then clean them up automatically.
                    </p>
                  </div>
                </div>
                <div className="knowledge-retention-form">
                  <label>
                    Days after revoke
                    <input
                      type="number"
                      min={1}
                      max={36500}
                      step={1}
                      placeholder="Disabled"
                      value={retentionDaysInput}
                      disabled={busy}
                      onChange={(e) => setRetentionDaysInput(e.target.value)}
                    />
                  </label>
                  <div className="agent-inline-form">
                    <button
                      type="button"
                      className="btn"
                      disabled={busy}
                      onClick={() => void saveRetention()}
                    >
                      Save retention
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={busy || detail.retention_days == null}
                      onClick={() => void runRetentionCleanup()}
                      title={
                        detail.retention_days == null
                          ? "Save a retention period first"
                          : "Delete revoked documents past retention"
                      }
                    >
                      Run cleanup
                    </button>
                  </div>
                </div>
                <p className="agent-table-sub">
                  {detail.retention_days != null
                    ? `Current: ${detail.retention_days} day${detail.retention_days === 1 ? "" : "s"} after revoke. Leave empty and save to disable automatic cleanup.`
                    : "Automatic cleanup is disabled until you set and save a retention period."}
                </p>
              </section>

              <section className="agent-section-card">
                <h3>Upload document</h3>
                <form className="knowledge-upload-form" onSubmit={uploadDocument}>
                  <input
                    ref={fileInput}
                    required
                    type="file"
                    multiple
                    onChange={(e) => onUploadFilesChange(e.target.files)}
                    disabled={busy}
                  />
                  {uploadFiles.length <= 1 ? (
                    <input
                      placeholder="Optional document title"
                      value={uploadTitle}
                      onChange={(e) => setUploadTitle(e.target.value)}
                      disabled={busy}
                    />
                  ) : (
                    <p className="knowledge-upload-hint">
                      {uploadFiles.length} files selected. Titles will use each file name.
                    </p>
                  )}
                  <button className="btn" disabled={uploadFiles.length === 0 || busy}>
                    {uploadProgress
                      ? `Uploading ${uploadProgress.current} of ${uploadProgress.total}…`
                      : uploadFiles.length > 1
                        ? `Upload ${uploadFiles.length} files`
                        : "Upload"}
                  </button>
                </form>
                <p className="agent-table-sub">
                  Up to {MAX_KNOWLEDGE_UPLOAD_FILES} files per upload. An optional title is available only when uploading a single file.
                </p>
              </section>

              <section className="agent-section-card">
                <h3>Documents</h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Document</th><th>Version</th><th>Status</th><th>Class</th><th>Uploaded</th><th /></tr>
                    </thead>
                    <tbody>
                      {documentVersions.map(({ document, version }) => (
                        <tr key={version.id}>
                          <td>
                            <strong>{document.title}</strong>
                            <small className="agent-table-sub">{version.file_name}</small>
                            <small className="agent-table-sub">
                              Document: {humanAgentStatus(document.status)}
                            </small>
                            {version.status === "failed" && version.failure_reason ? (
                              <small className="agent-table-sub error">{version.failure_reason}</small>
                            ) : null}
                            {version.status === "revoked" || document.status === "revoked" ? (
                              <small className="agent-table-sub error">Revoked from retrieval</small>
                            ) : null}
                          </td>
                          <td>v{version.version_number}</td>
                          <td><span className={`agent-status ${agentStatusTone(version.status)}`}>{humanAgentStatus(version.status)}</span></td>
                          <td>{humanAgentStatus(version.classification)}</td>
                          <td>{readableDate(version.created_at)}</td>
                          <td>
                            {version.status === "review" ? (
                              <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void approveDocument(version.id)}>
                                Approve
                              </button>
                            ) : null}
                            {!["revoked", "deleted"].includes(document.status) ? (
                              <button
                                type="button"
                                className="btn btn-ghost"
                                disabled={busy}
                                onClick={() => void revokeDocument(document.id, document.title)}
                              >
                                Revoke
                              </button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                      {documentVersions.length === 0 ? <tr><td colSpan={6}>No documents yet.</td></tr> : null}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="agent-section-card">
                <h3>HTTP connector</h3>
                <form className="knowledge-connector-form" onSubmit={addHttpConnector}>
                  <input
                    required
                    placeholder="Connector name"
                    value={connectorName}
                    onChange={(e) => setConnectorName(e.target.value)}
                  />
                  <textarea
                    required
                    rows={1}
                    placeholder="One public HTTPS URL per line"
                    value={connectorUrls}
                    onChange={(e) => setConnectorUrls(e.target.value)}
                  />
                  <button className="btn" disabled={busy}>Add connector</button>
                </form>
                <div className="agent-chip-list">
                  {(detail.connectors || []).map((connector) => (
                    <span className="agent-binding-chip" key={connector.id}>
                      {connector.name}
                      <em className={`agent-status ${agentStatusTone(connector.status)}`}>{humanAgentStatus(connector.status)}</em>
                      {Array.isArray(connector.config?.urls) ? (
                        <small>{connector.config.urls.length} URL(s)</small>
                      ) : null}
                      {connector.status === "active" ? (
                        <>
                          <button type="button" disabled={busy} onClick={() => void syncConnector(connector.id)}>Sync</button>
                          <button type="button" disabled={busy} onClick={() => void pauseConnector(connector.id)}>Pause</button>
                        </>
                      ) : null}
                      {connector.status === "paused" ? (
                        <button type="button" disabled={busy} onClick={() => void resumeConnector(connector.id)}>Resume</button>
                      ) : null}
                      {connector.status !== "archived" ? (
                        <button type="button" disabled={busy} onClick={() => void disableConnector(connector.id, connector.name)}>
                          Delete
                        </button>
                      ) : null}
                    </span>
                  ))}
                </div>
              </section>

              <section className="agent-section-card">
                <h3>Ingestion operations</h3>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Job</th><th>Type</th><th>Status</th><th>Attempts</th><th>Created</th><th /></tr></thead>
                    <tbody>
                      {(detail.jobs || []).map((job) => (
                        <tr key={job.id}>
                          <td><code>{job.id.slice(0, 8)}</code></td>
                          <td>{humanAgentStatus(job.job_type)}</td>
                          <td><span className={`agent-status ${agentStatusTone(job.status)}`}>{humanAgentStatus(job.status)}</span></td>
                          <td>{job.attempt_count}/{job.max_attempts}</td>
                          <td>{readableDate(job.created_at)}</td>
                          <td>{job.status === "dead" ? <button type="button" className="btn btn-ghost" onClick={() => void retryJob(job.id)}>Retry</button> : null}</td>
                        </tr>
                      ))}
                      {(detail.jobs || []).length === 0 ? <tr><td colSpan={6}>No ingestion jobs.</td></tr> : null}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </section>
      </div>

      <Modal open={createOpen} title="New Knowledge Base" onClose={() => !busy && setCreateOpen(false)} panelClassName="modal-panel--agent">
        <form className="agent-modal-form" onSubmit={createBase}>
          <label>Name<input required value={name} onChange={(e) => {
            setName(e.target.value);
            if (!slug) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
          }} /></label>
          <label>Slug<input required value={slug} onChange={(e) => setSlug(e.target.value)} /></label>
          <label>Description<textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
          <label>Sensitivity<select value={sensitivity} onChange={(e) => setSensitivity(e.target.value)}>
            <option value="internal">Internal</option>
            <option value="confidential">Confidential</option>
            <option value="hr_confidential">HR confidential</option>
            <option value="legal_privileged">Legal privileged</option>
            <option value="finance_restricted">Finance restricted</option>
          </select></label>
          <label>Access<select value={accessType} onChange={(e) => setAccessType(e.target.value as "public" | "private")}>
            <option value="private">Private</option><option value="public">Public</option>
          </select></label>
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setCreateOpen(false)}>Cancel</button>
            <button className="btn" disabled={busy}>{busy ? "Creating…" : "Create"}</button>
          </div>
        </form>
      </Modal>
    </AdminPage>
  );
}
