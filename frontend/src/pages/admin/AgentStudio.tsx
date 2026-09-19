import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import ResourceAccessEditor from "../../components/admin/ResourceAccessEditor";
import Modal from "../../components/Modal";
import RowActionsMenu from "../../components/RowActionsMenu";
import { useConfirm } from "../../context/ConfirmContext";
import {
  AgentBindingRecord,
  AgentPolicyMap,
  AgentRecord,
  AgentVersionRecord,
  KnowledgeBaseRecord,
  agentStatusTone,
  humanAgentStatus,
  readableDate,
  safeJsonObject,
} from "../../lib/agentPlatform";
import {
  AgentPolicyFormValues,
  applyPolicyForm,
  policiesFromUnknown,
  readPolicyForm,
  splitExampleInput,
  splitKeywordInput,
} from "../../lib/agentPolicyForm";
import { USAGE_AND_ACTIVITY_LABEL } from "../../lib/usageActivityLabel";

type ChatModel = { id: string; name: string; external_id?: string };

const defaultPolicies = (modelId: string) => ({
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
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [detail, setDetail] = useState<AgentRecord | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [models, setModels] = useState<ChatModel[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseRecord[]>([]);
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
  const [createAccess, setCreateAccess] = useState<"public" | "private">("private");
  const [editorPrompt, setEditorPrompt] = useState("");
  const [editorSummary, setEditorSummary] = useState("");
  const [policyDraft, setPolicyDraft] = useState<AgentPolicyMap>({});
  const [policyForm, setPolicyForm] = useState<AgentPolicyFormValues>(() =>
    readPolicyForm({}),
  );
  const [advancedJson, setAdvancedJson] = useState("{}");
  const [jsonDirty, setJsonDirty] = useState(false);
  const [keywordInput, setKeywordInput] = useState("");
  const [examplesText, setExamplesText] = useState("");
  const [bindOpen, setBindOpen] = useState(false);
  const [bindSearch, setBindSearch] = useState("");
  const [bindSelected, setBindSelected] = useState<string[]>([]);

  const hydratePolicies = useCallback((policies: AgentPolicyMap) => {
    const form = readPolicyForm(policies);
    setPolicyDraft(policies);
    setPolicyForm(form);
    setAdvancedJson(JSON.stringify(policies, null, 2));
    setJsonDirty(false);
    setKeywordInput("");
    setExamplesText(form.examples.join("\n"));
  }, []);

  const updatePolicyForm = useCallback((patch: Partial<AgentPolicyFormValues>) => {
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
      const rows = await api<AgentRecord[]>("/api/admin/agents");
      setAgents(rows);
      setSelectedAgentId((current) =>
        current && rows.some((row) => row.id === current) ? current : rows[0]?.id || "",
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (agentId: string) => {
    if (!agentId) {
      setDetail(null);
      return;
    }
    try {
      const row = await api<AgentRecord>(`/api/admin/agents/${encodeURIComponent(agentId)}`);
      setDetail(row);
      const selectable = row.versions.filter(
        (version) => !(version.status === "archived" && !version.published_at),
      );
      setSelectedVersionId((current) => {
        if (current && selectable.some((version) => version.id === current)) return current;
        return (
          selectable.find((version) => version.status === "draft")?.id
          || row.active_version_id
          || selectable[0]?.id
          || ""
        );
      });
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void loadAgents();
    api<ChatModel[]>("/api/chat/models").then((rows) => {
      setModels(rows);
      setCreateModel(rows[0]?.id || "");
    }).catch(() => {});
    api<KnowledgeBaseRecord[]>("/api/admin/knowledge/bases")
      .then(setKnowledgeBases)
      .catch(() => {});
  }, [loadAgents]);

  useEffect(() => {
    void loadDetail(selectedAgentId);
  }, [selectedAgentId, loadDetail]);

  const selectedVersion = useMemo(
    () => detail?.versions.find((version) => version.id === selectedVersionId) || null,
    [detail, selectedVersionId],
  );

  useEffect(() => {
    setEditorPrompt(selectedVersion?.system_prompt || "");
    setEditorSummary(selectedVersion?.change_summary || "");
    hydratePolicies(selectedVersion?.policies || {});
  }, [selectedVersion, hydratePolicies]);

  const filteredAgents = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter((agent) =>
      `${agent.name} ${agent.slug} ${agent.category || ""}`.toLowerCase().includes(needle),
    );
  }, [agents, search]);

  async function reloadSelected(message?: string) {
    await loadAgents();
    if (selectedAgentId) await loadDetail(selectedAgentId);
    if (message) setFlash(message);
  }

  async function createAgent(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<AgentRecord>("/api/admin/agents", {
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function addKeywords(raw: string) {
    const added = splitKeywordInput(raw);
    if (added.length === 0) return;
    updatePolicyForm({
      keywords: [...policyForm.keywords, ...added.filter((item) => !policyForm.keywords.includes(item))],
    });
    setKeywordInput("");
  }

  function onKeywordKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" && event.key !== ",") return;
    event.preventDefault();
    addKeywords(keywordInput);
  }

  async function saveDraft(e: FormEvent) {
    e.preventDefault();
    if (!selectedVersion || selectedVersion.status !== "draft") return;
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function versionAction(action: "submit" | "publish" | "rollback") {
    if (!selectedVersion) return;
    const reason = action === "rollback"
      ? await prompt({
        title: "Restore archived version",
        message: "Rollback creates a new published version from this archived snapshot.",
        promptLabel: "Reason",
        promptDefault: "Restore approved version",
        confirmLabel: "Restore",
      })
      : null;
    if (action === "rollback" && !reason?.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/admin/agents/versions/${selectedVersion.id}/${action}`, {
        method: "POST",
        body: action === "rollback" ? JSON.stringify({ reason }) : undefined,
      });
      await reloadSelected(
        action === "submit"
          ? "Version submitted for review."
          : action === "publish"
            ? "Version published."
            : "Version restored.",
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function cloneVersion() {
    if (!detail || !selectedVersion) return;
    const ok = await confirm({
      title: "Clone to draft?",
      message:
        `Create a new editable draft from v${selectedVersion.version_number} ` +
        `(${humanAgentStatus(selectedVersion.status)})? You can discard the draft later if you change your mind.`,
      confirmLabel: "Clone",
      cancelLabel: "Cancel",
    });
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      const created = await api<AgentVersionRecord>(
        `/api/admin/agents/${detail.id}/versions`,
        {
          method: "POST",
          body: JSON.stringify({
            clone_version_id: selectedVersion.id,
            change_summary: `Draft cloned from v${selectedVersion.version_number}`,
          }),
        },
      );
      await reloadSelected("New draft version created.");
      setSelectedVersionId(created.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function discardDraft() {
    if (!detail || !selectedVersion || selectedVersion.status !== "draft") return;
    const ok = await confirm({
      title: "Discard draft?",
      message:
        `Permanently discard draft v${selectedVersion.version_number}? ` +
        "Unsaved edits and draft-only knowledge bindings on this version will be removed.",
      confirmLabel: "Discard draft",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ next_version_id: string }>(
        `/api/admin/agents/versions/${encodeURIComponent(selectedVersion.id)}/discard`,
        { method: "POST" },
      );
      setSelectedVersionId(result.next_version_id);
      await reloadSelected(`Draft v${selectedVersion.version_number} discarded.`);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function openBindModal() {
    setBindSearch("");
    setBindSelected([]);
    setBindOpen(true);
  }

  function toggleBindSelection(knowledgeBaseId: string) {
    setBindSelected((current) =>
      current.includes(knowledgeBaseId)
        ? current.filter((id) => id !== knowledgeBaseId)
        : [...current, knowledgeBaseId],
    );
  }

  async function removeBinding(binding: AgentBindingRecord) {
    if (!selectedVersion || selectedVersion.status !== "draft") return;
    const name = binding.knowledge_base_name || binding.knowledge_base_id;
    const ok = await confirm({
      title: "Remove Knowledge binding?",
      message: `Remove “${name}” from this draft? You can add it again later.`,
      confirmLabel: "Remove",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/admin/agents/bindings/${encodeURIComponent(binding.id)}/revoke`, {
        method: "POST",
        body: JSON.stringify({ reason: "Removed from draft" }),
      });
      await reloadSelected(`Removed “${name}” from this draft.`);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function bindKnowledge() {
    if (!selectedVersion || bindSelected.length === 0) return;
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
      await reloadSelected(
        bound === 1
          ? "Knowledge binding sent for approval."
          : `${bound} Knowledge bindings sent for approval.`,
      );
    } catch (err) {
      if (bound > 0) {
        await reloadSelected(
          `${bound} binding(s) created before an error. ${String(err)}`,
        );
      }
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function setAgentStatus(status: "active" | "archived") {
    if (!detail) return;
    if (status === "archived") {
      const ok = await confirm({
        title: "Archive Agent",
        message: `Archive “${detail.name}”? It will disappear from the user Agent catalog but keep history for audit.`,
        confirmLabel: "Archive",
        danger: true,
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      await api(`/api/admin/agents/${detail.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await reloadSelected(status === "archived" ? "Agent archived." : "Agent activated.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function deleteAgent() {
    if (!detail) return;
    const typed = await prompt({
      title: "Delete Agent permanently?",
      message:
        `This permanently removes “${detail.name}” from Agent Studio and the user catalog. ` +
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
    if (typed == null) return;
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
    if (!reason?.trim()) return;
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  const modelOptions = useMemo(() => {
    const current = policyForm.primaryModelId;
    if (
      current &&
      !models.some((model) => model.id === current || model.external_id === current)
    ) {
      return [...models, { id: current, name: current, external_id: current }];
    }
    return models;
  }, [models, policyForm.primaryModelId]);

  const selectedModelValue =
    modelOptions.find(
      (model) =>
        model.id === policyForm.primaryModelId ||
        model.external_id === policyForm.primaryModelId,
    )?.id || policyForm.primaryModelId;

  const versionBindings = (detail?.bindings || []).filter(
    (binding) => binding.agent_version_id === selectedVersionId,
  );
  const boundKnowledgeIds = useMemo(
    () => new Set(versionBindings.map((binding) => binding.knowledge_base_id)),
    [versionBindings],
  );
  const availableKnowledgeBases = useMemo(() => {
    const needle = bindSearch.trim().toLowerCase();
    return knowledgeBases.filter((knowledgeBase) => {
      if (boundKnowledgeIds.has(knowledgeBase.id)) return false;
      if (!needle) return true;
      return `${knowledgeBase.name} ${knowledgeBase.slug} ${knowledgeBase.sensitivity}`
        .toLowerCase()
        .includes(needle);
    });
  }, [knowledgeBases, boundKnowledgeIds, bindSearch]);
  const selectableVersions = useMemo(
    () =>
      (detail?.versions || []).filter(
        (version) => !(version.status === "archived" && !version.published_at),
      ),
    [detail],
  );

  return (
    <AdminPage
      title="Agent Studio"
      actions={
        <>
          <button type="button" className="btn btn-ghost" onClick={() => void loadAgents()}>
            Refresh
          </button>
          <button type="button" className="btn" onClick={() => setCreateOpen(true)}>
            New Agent
          </button>
        </>
      }
    >
      {error ? <div className="error" role="alert">{error}</div> : null}
      {flash ? <div className="success">{flash}</div> : null}
      <div className="agent-studio-layout" aria-busy={loading}>
        <aside className="agent-studio-list">
          <input
            type="search"
            placeholder="Search Agents…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="agent-studio-list__rows">
            {filteredAgents.map((agent) => (
              <button
                type="button"
                key={agent.id}
                className={agent.id === selectedAgentId ? "is-selected" : ""}
                onClick={() => setSelectedAgentId(agent.id)}
              >
                <span className="agent-avatar" aria-hidden>{agent.icon || "A"}</span>
                <span>
                  <strong>{agent.name}</strong>
                  <small>{agent.slug}</small>
                </span>
                <em className={`agent-status ${agentStatusTone(agent.status)}`}>
                  {humanAgentStatus(agent.status)}
                </em>
              </button>
            ))}
            {!loading && filteredAgents.length === 0 ? (
              <p className="agent-empty">No Agents found.</p>
            ) : null}
          </div>
        </aside>

        <section className="agent-studio-editor">
          {!detail ? (
            <div className="agent-empty-state">
              <h2>Select or create an Agent</h2>
              <p>Agent configuration is versioned and published through maker-checker review.</p>
            </div>
          ) : (
            <>
              <div className="agent-studio-title">
                <div>
                  <h2>{detail.name}</h2>
                  <p>
                    {detail.description || "No description"} · {detail.access_type} access ·{" "}
                    <span className={`agent-status ${agentStatusTone(detail.status)}`}>
                      {humanAgentStatus(detail.status)}
                    </span>
                  </p>
                </div>
                <div className="agent-studio-title-actions">
                  <RowActionsMenu
                    actions={[
                      {
                        label: USAGE_AND_ACTIVITY_LABEL,
                        onClick: () =>
                          navigate(`/admin/agents/${encodeURIComponent(detail.id)}/activity`),
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
                    ]}
                  />
                </div>
              </div>

              <ResourceAccessEditor
                title="Who can see this Agent"
                loadPath={`/api/admin/agents/${encodeURIComponent(detail.id)}/access`}
                savePath={`/api/admin/agents/${encodeURIComponent(detail.id)}/access`}
                disabled={busy}
                onError={setError}
                onSaved={() => void reloadSelected("Agent access updated.")}
              />

              <div className="agent-version-toolbar">
                <label>
                  Version
                  <select
                    value={selectedVersionId}
                    onChange={(e) => setSelectedVersionId(e.target.value)}
                  >
                    {selectableVersions.map((version) => (
                      <option key={version.id} value={version.id}>
                        v{version.version_number} · {humanAgentStatus(version.status)}
                      </option>
                    ))}
                  </select>
                </label>
                <div>
                  <button type="button" className="btn btn-ghost" disabled={!selectedVersion || busy} onClick={() => void cloneVersion()}>
                    Clone to draft
                  </button>
                  {selectedVersion?.status === "draft" ? (
                    <>
                      <button type="button" className="btn" disabled={busy} onClick={() => void versionAction("submit")}>
                        Submit review
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busy}
                        onClick={() => void discardDraft()}
                      >
                        Discard draft
                      </button>
                    </>
                  ) : null}
                  {selectedVersion?.status === "review" ? (
                    <button type="button" className="btn" disabled={busy} onClick={() => void versionAction("publish")}>
                      Publish
                    </button>
                  ) : null}
                  {selectedVersion?.status === "archived" ? (
                    <button type="button" className="btn" disabled={busy} onClick={() => void versionAction("rollback")}>
                      Restore
                    </button>
                  ) : null}
                </div>
              </div>

              {selectedVersion ? (
                <form className="agent-editor-form" onSubmit={saveDraft}>
                  <div className="agent-editor-meta">
                    <span className={`agent-status ${agentStatusTone(selectedVersion.status)}`}>
                      {humanAgentStatus(selectedVersion.status)}
                    </span>
                    <span>Created {readableDate(selectedVersion.created_at)}</span>
                    <code>{selectedVersion.id}</code>
                  </div>
                  <label>
                    System prompt
                    <textarea
                      rows={10}
                      value={editorPrompt}
                      readOnly={selectedVersion.status !== "draft"}
                      onChange={(e) => setEditorPrompt(e.target.value)}
                    />
                  </label>
                  <label>
                    Change summary
                    <input
                      value={editorSummary}
                      readOnly={selectedVersion.status !== "draft"}
                      onChange={(e) => setEditorSummary(e.target.value)}
                    />
                  </label>

                  <fieldset className="agent-policy-fieldset" disabled={selectedVersion.status !== "draft"}>
                    <legend>How this Agent is found and answers</legend>
                    <label>
                      Primary model
                      <select
                        value={selectedModelValue}
                        onChange={(e) => {
                          const model = modelOptions.find((item) => item.id === e.target.value);
                          updatePolicyForm({
                            primaryModelId: model?.external_id || model?.id || e.target.value,
                          });
                        }}
                      >
                        <option value="">Select model…</option>
                        {modelOptions.map((model) => (
                          <option key={model.id} value={model.id}>{model.name}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Keywords
                      <div className="agent-keyword-editor">
                        <div className="agent-chip-list agent-chip-list--editor">
                          {policyForm.keywords.map((keyword) => (
                            <span key={keyword} className="agent-binding-chip">
                              {keyword}
                              {selectedVersion.status === "draft" ? (
                                <button
                                  type="button"
                                  aria-label={`Remove ${keyword}`}
                                  onClick={() =>
                                    updatePolicyForm({
                                      keywords: policyForm.keywords.filter((item) => item !== keyword),
                                    })
                                  }
                                >
                                  ×
                                </button>
                              ) : null}
                            </span>
                          ))}
                          {policyForm.keywords.length === 0 ? (
                            <span className="agent-empty">No keywords yet.</span>
                          ) : null}
                        </div>
                        {selectedVersion.status === "draft" ? (
                          <input
                            value={keywordInput}
                            placeholder="Add a keyword and press Enter"
                            onChange={(e) => setKeywordInput(e.target.value)}
                            onKeyDown={onKeywordKeyDown}
                            onBlur={() => addKeywords(keywordInput)}
                          />
                        ) : null}
                      </div>
                      <small>
                        {selectedVersion.status === "draft"
                          ? "Used for routing. Separate with Enter or comma. Persian and English are both fine."
                          : "This published version is read-only. Use Clone to draft above, then add keywords on the new draft and publish it."}
                      </small>
                    </label>
                    <label>
                      Example questions
                      <textarea
                        rows={4}
                        value={examplesText}
                        readOnly={selectedVersion.status !== "draft"}
                        onChange={(e) => {
                          setExamplesText(e.target.value);
                          updatePolicyForm({ examples: splitExampleInput(e.target.value) });
                        }}
                      />
                      <small>One example per line. These help the router recognize this Agent.</small>
                    </label>
                    <label>
                      Disclaimer (English)
                      <textarea
                        rows={2}
                        value={policyForm.disclaimerEn}
                        readOnly={selectedVersion.status !== "draft"}
                        onChange={(e) => updatePolicyForm({ disclaimerEn: e.target.value })}
                      />
                    </label>
                    <label>
                      Disclaimer (Persian)
                      <textarea
                        rows={2}
                        dir="rtl"
                        value={policyForm.disclaimerFa}
                        readOnly={selectedVersion.status !== "draft"}
                        onChange={(e) => updatePolicyForm({ disclaimerFa: e.target.value })}
                      />
                    </label>
                    <div className="agent-policy-toggles">
                      <label>
                        <input
                          type="checkbox"
                          checked={policyForm.retrievalEnabled}
                          onChange={(e) => updatePolicyForm({ retrievalEnabled: e.target.checked })}
                        />
                        Use Knowledge Base retrieval
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={policyForm.requireEvidence}
                          onChange={(e) => updatePolicyForm({ requireEvidence: e.target.checked })}
                        />
                        Require organizational evidence
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={policyForm.citationsRequired}
                          onChange={(e) => updatePolicyForm({ citationsRequired: e.target.checked })}
                        />
                        Require citations
                      </label>
                    </div>
                  </fieldset>

                  <details className="agent-policy-advanced">
                    <summary>Advanced policy JSON</summary>
                    <label>
                      Policy document
                      <textarea
                        className="agent-json-editor"
                        rows={14}
                        spellCheck={false}
                        value={advancedJson}
                        readOnly={selectedVersion.status !== "draft"}
                        onChange={(e) => {
                          setAdvancedJson(e.target.value);
                          setJsonDirty(true);
                        }}
                        onBlur={() => {
                          if (!jsonDirty || selectedVersion.status !== "draft") return;
                          try {
                            hydratePolicies(
                              policiesFromUnknown(safeJsonObject(advancedJson, "Policies")),
                            );
                            setError("");
                          } catch (err) {
                            setError(String(err));
                          }
                        }}
                      />
                      <small>
                        Escape hatch for tools, guardrails, locale, and other version policies.
                        The form above overwrites model, routing keywords/examples, disclaimer,
                        and retrieval flags on save.
                      </small>
                    </label>
                  </details>
                  {selectedVersion.status === "draft" ? (
                    <div className="agent-inline-form">
                      <button type="submit" className="btn" disabled={busy || !editorPrompt.trim()}>
                        {busy ? "Saving…" : "Save draft"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={busy}
                        onClick={() => void discardDraft()}
                      >
                        Discard draft
                      </button>
                    </div>
                  ) : null}
                </form>
              ) : null}

              <section className="agent-binding-section">
                <div className="agent-section-card__head">
                  <div>
                    <h3>Knowledge bindings</h3>
                    <p>Bindings are version-scoped and require Knowledge approval.</p>
                    {selectedVersion && selectedVersion.status !== "draft" ? (
                      <p>
                        This published version is read-only. Use Clone to draft above, then add
                        Knowledge Bases on the new draft and publish it.
                      </p>
                    ) : null}
                  </div>
                  {selectedVersion?.status === "draft" ? (
                    <button
                      type="button"
                      className="btn"
                      disabled={busy}
                      onClick={openBindModal}
                    >
                      + Add knowledge
                    </button>
                  ) : null}
                </div>
                <div className="agent-chip-list">
                  {versionBindings.map((binding) => (
                    <span key={binding.id} className="agent-binding-chip">
                      {binding.knowledge_base_name || binding.knowledge_base_id}
                      <em className={`agent-status ${agentStatusTone(binding.status)}`}>
                        {humanAgentStatus(binding.status)}
                      </em>
                      {selectedVersion?.status === "draft" ? (
                        <button
                          type="button"
                          aria-label={`Remove ${binding.knowledge_base_name || binding.knowledge_base_id}`}
                          disabled={busy}
                          onClick={() => void removeBinding(binding)}
                        >
                          ×
                        </button>
                      ) : null}
                    </span>
                  ))}
                  {versionBindings.length === 0 ? <span className="agent-empty">No bindings.</span> : null}
                </div>
              </section>
            </>
          )}
        </section>
      </div>

      <Modal
        open={createOpen}
        title="Create Agent draft"
        onClose={() => !busy && setCreateOpen(false)}
        panelClassName="modal-panel--agent"
      >
        <form className="agent-modal-form" onSubmit={createAgent}>
          <label>
            Name
            <input
              required
              value={createName}
              onChange={(e) => {
                setCreateName(e.target.value);
                if (!createSlug) {
                  setCreateSlug(
                    e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
                  );
                }
              }}
            />
          </label>
          <label>
            Slug
            <input required value={createSlug} onChange={(e) => setCreateSlug(e.target.value)} />
          </label>
          <label>
            Description
            <textarea rows={3} value={createDescription} onChange={(e) => setCreateDescription(e.target.value)} />
          </label>
          <label>
            Primary model
            <select required value={createModel} onChange={(e) => setCreateModel(e.target.value)}>
              <option value="">Select model…</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>{model.name}</option>
              ))}
            </select>
          </label>
          <label>
            Access
            <select value={createAccess} onChange={(e) => setCreateAccess(e.target.value as "public" | "private")}>
              <option value="private">Private · explicit grants required</option>
              <option value="public">Public · all active users</option>
            </select>
          </label>
          <label>
            System prompt
            <textarea required rows={8} value={createPrompt} onChange={(e) => setCreatePrompt(e.target.value)} />
          </label>
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setCreateOpen(false)}>Cancel</button>
            <button type="submit" className="btn" disabled={busy || !createModel}>
              {busy ? "Creating…" : "Create draft"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={bindOpen}
        title="Add knowledge"
        onClose={() => !busy && setBindOpen(false)}
        panelClassName="modal-panel--agent"
      >
        <div className="agent-bind-modal">
          <input
            type="search"
            placeholder="Search Knowledge Bases…"
            value={bindSearch}
            onChange={(e) => setBindSearch(e.target.value)}
            disabled={busy}
          />
          <div className="agent-bind-list" role="group" aria-label="Available Knowledge Bases">
            {availableKnowledgeBases.map((knowledgeBase) => {
              const checked = bindSelected.includes(knowledgeBase.id);
              return (
                <label key={knowledgeBase.id} className={checked ? "is-selected" : ""}>
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={busy}
                    onChange={() => toggleBindSelection(knowledgeBase.id)}
                  />
                  <span>
                    <strong>{knowledgeBase.name}</strong>
                    <small>
                      {humanAgentStatus(knowledgeBase.sensitivity)}
                      {knowledgeBase.access_type === "private" ? " · Private" : ""}
                    </small>
                  </span>
                </label>
              );
            })}
            {availableKnowledgeBases.length === 0 ? (
              <p className="agent-empty">
                {knowledgeBases.some((item) => !boundKnowledgeIds.has(item.id))
                  ? "No Knowledge Bases match this search."
                  : "All Knowledge Bases are already bound to this version."}
              </p>
            ) : null}
          </div>
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setBindOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy || bindSelected.length === 0}
              onClick={() => void bindKnowledge()}
            >
              {busy
                ? "Requesting…"
                : bindSelected.length > 1
                  ? `Request binding (${bindSelected.length})`
                  : "Request binding"}
            </button>
          </div>
        </div>
      </Modal>
    </AdminPage>
  );
}
