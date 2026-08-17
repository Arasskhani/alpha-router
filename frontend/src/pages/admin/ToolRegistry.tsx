import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import AdminPage from "../../components/AdminPage";
import Modal from "../../components/Modal";
import {
  ToolRecord,
  ToolVersionRecord,
  agentStatusTone,
  humanAgentStatus,
  safeJsonObject,
} from "../../lib/agentPlatform";

const emptySchema = JSON.stringify(
  { type: "object", properties: {}, additionalProperties: false },
  null,
  2,
);

export default function ToolRegistry() {
  const [tools, setTools] = useState<ToolRecord[]>([]);
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
  const [effectType, setEffectType] = useState<"read_only" | "side_effecting">("read_only");
  const [inputSchema, setInputSchema] = useState(emptySchema);
  const [outputSchema, setOutputSchema] = useState(emptySchema);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await api<ToolRecord[]>("/api/admin/agents/tools");
      setTools(rows);
      setSelectedToolId((current) =>
        current && rows.some((row) => row.id === current) ? current : rows[0]?.id || "",
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedTool = useMemo(
    () => tools.find((tool) => tool.id === selectedToolId) || null,
    [tools, selectedToolId],
  );
  const selectedVersion = useMemo(
    () => selectedTool?.versions.find((version) => version.id === selectedVersionId) || null,
    [selectedTool, selectedVersionId],
  );

  useEffect(() => {
    if (!selectedTool) {
      setSelectedVersionId("");
      return;
    }
    setSelectedVersionId((current) =>
      current && selectedTool.versions.some((version) => version.id === current)
        ? current
        : selectedTool.versions.find((version) => version.status === "draft")?.id
          || selectedTool.active_version_id
          || selectedTool.versions[0]?.id
          || "",
    );
  }, [selectedTool]);

  async function createTool(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<ToolRecord>("/api/admin/agents/tools", {
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function lifecycle(action: "submit" | "publish" | "rollback") {
    if (!selectedVersion) return;
    const reason = action === "rollback"
      ? window.prompt("Rollback reason:", "Restore approved tool contract")
      : null;
    if (action === "rollback" && !reason?.trim()) return;
    setBusy(true);
    try {
      await api(`/api/admin/agents/tool-versions/${selectedVersion.id}/${action}`, {
        method: "POST",
        body: action === "rollback" ? JSON.stringify({ reason }) : undefined,
      });
      await load();
      setFlash(
        action === "submit"
          ? "Tool submitted for review."
          : action === "publish"
            ? "Tool contract published."
            : "Tool contract restored.",
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function cloneContract(version: ToolVersionRecord) {
    if (!selectedTool) return;
    setBusy(true);
    try {
      const created = await api<ToolVersionRecord>(
        `/api/admin/agents/tools/${selectedTool.id}/versions`,
        {
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
        },
      );
      await load();
      setSelectedVersionId(created.id);
      setFlash("New tool contract draft created.");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminPage
      title="Tool Registry"
      actions={
        <>
          <button type="button" className="btn btn-ghost" onClick={() => void load()}>Refresh</button>
          <button type="button" className="btn" onClick={() => setCreateOpen(true)}>Register Tool</button>
        </>
      }
    >
      <p className="agent-page-lead">
        Versioned JSON contracts, effect classification, explicit approvals, and model compatibility.
      </p>
      {error ? <div className="error">{error}</div> : null}
      {flash ? <div className="success">{flash}</div> : null}
      <div className="tool-registry-layout" aria-busy={loading}>
        <div className="tool-registry-table table-wrap">
          <table>
            <thead><tr><th>Tool</th><th>Status</th><th>Effect</th><th>Handler</th></tr></thead>
            <tbody>
              {tools.map((tool) => {
                const active = tool.versions.find((version) => version.id === tool.active_version_id)
                  || tool.versions[0];
                return (
                  <tr
                    key={tool.id}
                    className={tool.id === selectedToolId ? "is-selected" : ""}
                    onClick={() => setSelectedToolId(tool.id)}
                  >
                    <td><strong>{tool.name}</strong><small className="agent-table-sub">{tool.slug}</small></td>
                    <td><span className={`agent-status ${agentStatusTone(tool.status)}`}>{humanAgentStatus(tool.status)}</span></td>
                    <td>{active ? humanAgentStatus(active.effect_type) : "—"}</td>
                    <td><code>{active?.handler_key || "—"}</code></td>
                  </tr>
                );
              })}
              {!loading && tools.length === 0 ? <tr><td colSpan={4}>No registered tools.</td></tr> : null}
            </tbody>
          </table>
        </div>

        <aside className="tool-contract-panel">
          {!selectedTool || !selectedVersion ? (
            <div className="agent-empty-state"><h2>Select a tool</h2><p>Inspect immutable contracts and lifecycle evidence.</p></div>
          ) : (
            <>
              <div className="agent-studio-title">
                <div><h2>{selectedTool.name}</h2><p>{selectedTool.description || "No description"}</p></div>
                <span className={`agent-status ${agentStatusTone(selectedVersion.status)}`}>{humanAgentStatus(selectedVersion.status)}</span>
              </div>
              <label>
                Contract version
                <select value={selectedVersionId} onChange={(e) => setSelectedVersionId(e.target.value)}>
                  {selectedTool.versions.map((version) => (
                    <option key={version.id} value={version.id}>v{version.version_number} · {humanAgentStatus(version.status)}</option>
                  ))}
                </select>
              </label>
              <dl className="agent-definition-list">
                <div><dt>Handler</dt><dd><code>{selectedVersion.handler_key}</code></dd></div>
                <div><dt>Effect</dt><dd>{humanAgentStatus(selectedVersion.effect_type)}</dd></div>
                <div><dt>User approval</dt><dd>{humanAgentStatus(selectedVersion.approval_mode)}</dd></div>
                <div><dt>Timeout</dt><dd>{selectedVersion.timeout_seconds}s</dd></div>
                <div><dt>Retries</dt><dd>{selectedVersion.max_retries}</dd></div>
              </dl>
              <details className="agent-contract-details">
                <summary>Input schema</summary>
                <pre>{JSON.stringify(selectedVersion.input_schema, null, 2)}</pre>
              </details>
              <details className="agent-contract-details">
                <summary>Output schema</summary>
                <pre>{JSON.stringify(selectedVersion.output_schema, null, 2)}</pre>
              </details>
              <div className="agent-action-row">
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void cloneContract(selectedVersion)}>Clone draft</button>
                {selectedVersion.status === "draft" ? <button type="button" className="btn" disabled={busy} onClick={() => void lifecycle("submit")}>Submit review</button> : null}
                {selectedVersion.status === "review" ? <button type="button" className="btn" disabled={busy} onClick={() => void lifecycle("publish")}>Publish</button> : null}
                {selectedVersion.status === "archived" ? <button type="button" className="btn" disabled={busy} onClick={() => void lifecycle("rollback")}>Restore</button> : null}
              </div>
            </>
          )}
        </aside>
      </div>

      <Modal open={createOpen} title="Register Tool" onClose={() => !busy && setCreateOpen(false)} panelClassName="modal-panel--agent modal-panel--agent-wide">
        <form className="agent-modal-form agent-modal-form--tool" onSubmit={createTool}>
          <label>Name<input required value={name} onChange={(e) => {
            setName(e.target.value);
            if (!slug) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""));
          }} /></label>
          <label>Slug<input required value={slug} onChange={(e) => setSlug(e.target.value)} /></label>
          <label className="agent-form-wide">Description<textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
          <label>Handler key<input required placeholder="service.action" value={handlerKey} onChange={(e) => setHandlerKey(e.target.value)} /></label>
          <label>Effect<select value={effectType} onChange={(e) => setEffectType(e.target.value as "read_only" | "side_effecting")}>
            <option value="read_only">Read only</option><option value="side_effecting">Side effecting · approval required</option>
          </select></label>
          <label className="agent-form-wide">Input JSON Schema<textarea rows={10} className="agent-json-editor" spellCheck={false} value={inputSchema} onChange={(e) => setInputSchema(e.target.value)} /></label>
          <label className="agent-form-wide">Output JSON Schema<textarea rows={10} className="agent-json-editor" spellCheck={false} value={outputSchema} onChange={(e) => setOutputSchema(e.target.value)} /></label>
          <div className="dialog-actions agent-form-wide">
            <button type="button" className="btn btn-ghost" onClick={() => setCreateOpen(false)}>Cancel</button>
            <button className="btn" disabled={busy}>{busy ? "Registering…" : "Register draft"}</button>
          </div>
        </form>
      </Modal>
    </AdminPage>
  );
}
