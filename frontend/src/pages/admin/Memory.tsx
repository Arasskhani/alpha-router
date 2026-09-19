import { FormEvent, type ReactNode, useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
import { useReadOnly } from "../../context/ReadOnlyContext";
import {
  embeddingModelIdFromSpec,
  embeddingModelOptionLabel,
  suggestedEmbeddingDimensions,
} from "../../lib/embeddingDimensions";
import SearchableModelSelect from "../../components/admin/SearchableModelSelect";

type MemorySettings = {
  feature_enabled: boolean;
  extraction_model_id: number | null;
  embedding_model: string;
  embedding_dimensions: number | null;
  extract_debounce_seconds: number;
  extract_max_wait_seconds: number;
  extract_min_new_messages: number;
  max_per_user: number;
  inject_max_items: number;
  inject_max_chars: number;
  core_items: number;
  semantic_top_k: number;
  lexical_top_k: number;
  min_similarity: number;
  retrieval_timeout_ms: number;
  allowed_sensitive_categories: string[];
  stale_archive_days: number;
  soft_delete_purge_days: number;
  suppression_days: number;
  project_feature_enabled: boolean;
  project_max_per_project: number;
  project_inject_max_items: number;
  project_inject_max_chars: number;
  project_manual_items: number;
  project_extract_debounce_seconds: number;
  project_extract_max_wait_seconds: number;
  project_extract_min_new_messages: number;
  project_semantic_top_k: number;
  project_lexical_top_k: number;
  project_min_similarity: number;
};

type MemoryStats = {
  total_memories: number;
  memories_last_7d: number;
  jobs_by_status: Record<string, number>;
  oldest_pending_job_age_seconds: number | null;
  dead_letter_count: number;
  embedding_backlog: number;
  extraction_cost_usd_30d: number;
  project_learned_memories: number;
  project_manual_memories: number;
  project_jobs_by_status: Record<string, number>;
  project_dead_letter_count: number;
  project_embedding_backlog: number;
  project_extraction_cost_usd_30d: number;
};

type AdminModel = {
  id: number;
  external_id: string;
  display_name?: string | null;
  enabled: boolean;
  provider: string;
  kinds?: string[];
};

const SENSITIVE_OPTIONS = ["health", "financial", "work", "family", "preference", "identity", "other"];

/** Mirrors PROJECT_DENIED_CATEGORIES in the backend; not admin-configurable. */
const PROJECT_DENIED_CATEGORIES = ["health", "financial", "personal", "family", "identity"];

function formatJobs(byStatus: Record<string, number> | undefined): string {
  const entries = Object.entries(byStatus || {}).filter(([, count]) => count > 0);
  if (!entries.length) return "Idle";
  return entries.map(([status, count]) => `${status} ${count}`).join(" · ");
}

function formatPendingAge(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.round(seconds / 60)}m`;
}

function formatUsd(n: number): string {
  return `$${n.toFixed(n >= 1 ? 2 : 4)}`;
}

function FieldRow({
  title,
  hint,
  children,
  detail,
}: {
  title: ReactNode;
  hint?: ReactNode;
  children?: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className={`settings-row-block${detail ? " settings-row-block--open" : ""}`}>
      <div className="settings-row">
        <div className="settings-row__meta">
          <span className="settings-row__title">{title}</span>
          {hint ? <span className="settings-row__hint">{hint}</span> : null}
        </div>
        {children ? <div className="settings-row__trail">{children}</div> : null}
      </div>
      {detail ? <div className="settings-row__detail">{detail}</div> : null}
    </div>
  );
}

function NumberInput({
  id,
  value,
  disabled,
  step,
  min,
  onChange,
}: {
  id: string;
  value: number;
  disabled?: boolean;
  step?: string;
  min?: number;
  onChange: (n: number) => void;
}) {
  return (
    <input
      id={id}
      type="number"
      className="settings-row__control"
      step={step}
      min={min}
      value={Number.isFinite(value) ? value : 0}
      disabled={disabled}
      aria-label={id.replace(/-/g, " ")}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

function Toggle({
  on,
  disabled,
  label,
  onToggle,
}: {
  on: boolean;
  disabled?: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className={`alpha-router-toggle${on ? " on" : ""}`}
      onClick={onToggle}
      aria-label={label}
      aria-pressed={on}
      disabled={disabled}
    >
      <span className="alpha-router-toggle-knob" />
    </button>
  );
}

function StatusCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export default function MemoryAdmin() {
  const { confirm } = useConfirm();
  const readOnly = useReadOnly();
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [models, setModels] = useState<AdminModel[]>([]);
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [purgeUserId, setPurgeUserId] = useState("");

  async function load() {
    setError("");
    const [cfg, st, catalog] = await Promise.all([
      api<MemorySettings>("/api/admin/memory/settings"),
      api<MemoryStats>("/api/admin/memory/stats"),
      api<AdminModel[]>("/api/admin/models"),
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
    if (!settings?.embedding_model) return;
    if ((settings.embedding_dimensions ?? 0) > 0) return;
    const dims = suggestedEmbeddingDimensions(embeddingModelIdFromSpec(settings.embedding_model));
    setSettings((current) => {
      if (!current?.embedding_model || (current.embedding_dimensions ?? 0) > 0) return current;
      return { ...current, embedding_dimensions: dims };
    });
  }, [settings]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!settings) return;
    setSaving(true);
    setError("");
    setFlash("");
    try {
      const saved = await api<MemorySettings>("/api/admin/memory/settings", {
        method: "PATCH",
        body: JSON.stringify(settings),
      });
      setSettings(saved);
      setFlash("Memory settings saved.");
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  async function onReindex() {
    const ok = await confirm({
      title: "Rebuild memory index",
      message:
        "Re-embed every stored memory into a new Qdrant collection. Chat stays online; this may take a few minutes.",
      confirmLabel: "Reindex",
    });
    if (!ok) return;
    setReindexing(true);
    setError("");
    setFlash("");
    try {
      const result = await api<{ indexed?: number }>("/api/admin/memory/reindex", { method: "POST" });
      setFlash(`Reindexed ${result.indexed ?? 0} memories.`);
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
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
    if (!ok) return;
    setError("");
    setFlash("");
    try {
      const result = await api<{ deleted?: number }>(`/api/admin/memory/purge-user/${id}`, {
        method: "POST",
      });
      setFlash(`Deleted ${result.deleted ?? 0} memories for user ${id}.`);
      setPurgeUserId("");
      await load();
    } catch (err) {
      setError(String(err));
    }
  }

  function patch(partial: Partial<MemorySettings>) {
    if (!settings) return;
    setSettings({ ...settings, ...partial });
  }

  function toggleCategory(cat: string, checked: boolean) {
    if (!settings) return;
    const next = new Set(settings.allowed_sensitive_categories || []);
    if (checked) next.add(cat);
    else next.delete(cat);
    patch({ allowed_sensitive_categories: [...next] });
  }

  const saveBar = (
    <>
      <button type="submit" form="memory-settings-form" className="btn" disabled={readOnly || saving || !settings}>
        {saving ? "Saving…" : "Save"}
      </button>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={readOnly || reindexing || !settings}
        onClick={() => void onReindex()}
      >
        {reindexing ? "Reindexing…" : "Rebuild index"}
      </button>
    </>
  );

  if (!settings) {
    return (
      <AdminPage title="Memory" actions={saveBar}>
        <p className="muted-text">{error || "Loading…"}</p>
      </AdminPage>
    );
  }

  return (
    <AdminPage title="Memory" actions={saveBar}>
      <div className="memory-admin">
        <p className="muted-text memory-admin__lead">
          Automatic long-term memory for personal chat and shared project facts. Extraction uses the model below
          (system cost). Until a model is selected, nothing is learned.
        </p>
        {flash ? <p className="alert alert-success">{flash}</p> : null}
        {error ? <p className="alert alert-error" role="alert">{error}</p> : null}

        <section className="memory-admin__status" aria-label="Memory health">
          <div>
            <h2>User</h2>
            <dl>
              <StatusCell label="Memories" value={stats ? stats.total_memories.toLocaleString() : "…"} />
              <StatusCell label="Last 7 days" value={stats ? stats.memories_last_7d.toLocaleString() : "…"} />
              <StatusCell label="Embed backlog" value={stats ? stats.embedding_backlog.toLocaleString() : "…"} />
              <StatusCell label="Dead letter" value={stats ? stats.dead_letter_count.toLocaleString() : "…"} />
              <StatusCell label="Oldest pending" value={stats ? formatPendingAge(stats.oldest_pending_job_age_seconds) : "…"} />
              <StatusCell label="Extract 30d" value={stats ? formatUsd(stats.extraction_cost_usd_30d) : "…"} />
              <StatusCell label="Jobs" value={stats ? formatJobs(stats.jobs_by_status) : "…"} />
            </dl>
          </div>
          <div>
            <h2>Project</h2>
            <dl>
              <StatusCell label="Learned" value={stats ? stats.project_learned_memories.toLocaleString() : "…"} />
              <StatusCell label="Manual" value={stats ? stats.project_manual_memories.toLocaleString() : "…"} />
              <StatusCell label="Embed backlog" value={stats ? stats.project_embedding_backlog.toLocaleString() : "…"} />
              <StatusCell label="Dead letter" value={stats ? stats.project_dead_letter_count.toLocaleString() : "…"} />
              <StatusCell label="Extract 30d" value={stats ? formatUsd(stats.project_extraction_cost_usd_30d) : "…"} />
              <StatusCell label="Jobs" value={stats ? formatJobs(stats.project_jobs_by_status) : "…"} />
            </dl>
          </div>
        </section>

        <form id="memory-settings-form" onSubmit={(e) => void onSave(e)}>
          <section className="settings-section">
            <h2>Pipeline</h2>
            <p className="settings-section-desc">
              Shared models and housekeeping. Changing the embedding model requires a rebuild.
            </p>
            <div className="settings-list">
              <FieldRow title="Automatic memory" hint="Master switch for user extraction and injection">
                <Toggle
                  label="Automatic memory"
                  on={settings.feature_enabled}
                  disabled={readOnly}
                  onToggle={() => patch({ feature_enabled: !settings.feature_enabled })}
                />
              </FieldRow>
              <FieldRow title="Extraction model" hint="Required. Cost is billed as a system operation">
                <SearchableModelSelect
                  id="memory-extraction-model"
                  ariaLabel="Extraction model"
                  value={settings.extraction_model_id ? String(settings.extraction_model_id) : ""}
                  disabled={readOnly}
                  emptyLabel="Not configured"
                  placeholder="Search extraction models…"
                  options={textModels.map((m) => ({
                    value: String(m.id),
                    label: `${m.display_name || m.external_id} · ${m.provider}`,
                  }))}
                  onChange={(next) =>
                    patch({ extraction_model_id: next ? Number(next) : null })
                  }
                />
              </FieldRow>
              <FieldRow title="Embedding model" hint="Empty = Postgres-only retrieval">
                <SearchableModelSelect
                  id="memory-embedding-model"
                  ariaLabel="Embedding model"
                  value={settings.embedding_model || ""}
                  disabled={readOnly}
                  emptyLabel="Not configured"
                  placeholder="Search embedding models…"
                  options={embeddingModels.map((m) => ({
                    value: `${m.provider}:${m.external_id}`,
                    label: embeddingModelOptionLabel(m.external_id, m.provider),
                  }))}
                  onChange={(spec) => {
                    if (!spec) {
                      patch({ embedding_model: "", embedding_dimensions: null });
                      return;
                    }
                    patch({
                      embedding_model: spec,
                      embedding_dimensions: suggestedEmbeddingDimensions(
                        embeddingModelIdFromSpec(spec),
                      ),
                    });
                  }}
                />
              </FieldRow>
              <FieldRow title="Embedding dimensions" hint="Filled from the model. Override if needed. Rebuild after changing">
                <NumberInput
                  id="memory-embedding-dims"
                  value={settings.embedding_dimensions ?? 0}
                  min={0}
                  disabled={readOnly || !settings.embedding_model}
                  onChange={(n) => patch({ embedding_dimensions: n || null })}
                />
              </FieldRow>
              <FieldRow title="Retrieval timeout" hint="Milliseconds">
                <NumberInput
                  id="memory-retrieval-timeout"
                  value={settings.retrieval_timeout_ms}
                  disabled={readOnly}
                  onChange={(n) => patch({ retrieval_timeout_ms: n })}
                />
              </FieldRow>
              <FieldRow title="Stale archive" hint="Days unused before archive · 0 = off">
                <NumberInput
                  id="memory-stale-archive"
                  value={settings.stale_archive_days}
                  min={0}
                  disabled={readOnly}
                  onChange={(n) => patch({ stale_archive_days: n })}
                />
              </FieldRow>
              <FieldRow title="Soft-delete purge" hint="Days after delete before hard purge">
                <NumberInput
                  id="memory-soft-delete"
                  value={settings.soft_delete_purge_days}
                  disabled={readOnly}
                  onChange={(n) => patch({ soft_delete_purge_days: n })}
                />
              </FieldRow>
              <FieldRow title="Suppression" hint="Days a deleted fact is blocked from re-learning">
                <NumberInput
                  id="memory-suppression"
                  value={settings.suppression_days}
                  disabled={readOnly}
                  onChange={(n) => patch({ suppression_days: n })}
                />
              </FieldRow>
            </div>
          </section>

          <section className="settings-section">
            <h2>User memory</h2>
            <p className="settings-section-desc">Caps, retrieval, and extraction cadence for personal chat.</p>
            <div className="settings-list">
              <FieldRow title="Max per user">
                <NumberInput
                  id="memory-max-per-user"
                  value={settings.max_per_user}
                  disabled={readOnly}
                  onChange={(n) => patch({ max_per_user: n })}
                />
              </FieldRow>
              <FieldRow title="Core items" hint="Always injected when present">
                <NumberInput
                  id="memory-core-items"
                  value={settings.core_items}
                  disabled={readOnly}
                  onChange={(n) => patch({ core_items: n })}
                />
              </FieldRow>
              <FieldRow title="Inject max items">
                <NumberInput
                  id="memory-inject-items"
                  value={settings.inject_max_items}
                  disabled={readOnly}
                  onChange={(n) => patch({ inject_max_items: n })}
                />
              </FieldRow>
              <FieldRow title="Inject max chars">
                <NumberInput
                  id="memory-inject-chars"
                  value={settings.inject_max_chars}
                  disabled={readOnly}
                  onChange={(n) => patch({ inject_max_chars: n })}
                />
              </FieldRow>
              <FieldRow title="Semantic top-k">
                <NumberInput
                  id="memory-semantic-k"
                  value={settings.semantic_top_k}
                  disabled={readOnly}
                  onChange={(n) => patch({ semantic_top_k: n })}
                />
              </FieldRow>
              <FieldRow title="Lexical top-k">
                <NumberInput
                  id="memory-lexical-k"
                  value={settings.lexical_top_k}
                  disabled={readOnly}
                  onChange={(n) => patch({ lexical_top_k: n })}
                />
              </FieldRow>
              <FieldRow title="Min similarity" hint="0–1">
                <NumberInput
                  id="memory-min-sim"
                  value={settings.min_similarity}
                  step="0.01"
                  disabled={readOnly}
                  onChange={(n) => patch({ min_similarity: n })}
                />
              </FieldRow>
              <FieldRow title="Debounce" hint="Seconds after a turn before extract">
                <NumberInput
                  id="memory-debounce"
                  value={settings.extract_debounce_seconds}
                  disabled={readOnly}
                  onChange={(n) => patch({ extract_debounce_seconds: n })}
                />
              </FieldRow>
              <FieldRow title="Max wait" hint="Seconds before a forced extract">
                <NumberInput
                  id="memory-max-wait"
                  value={settings.extract_max_wait_seconds}
                  disabled={readOnly}
                  onChange={(n) => patch({ extract_max_wait_seconds: n })}
                />
              </FieldRow>
              <FieldRow title="Min new messages">
                <NumberInput
                  id="memory-min-messages"
                  value={settings.extract_min_new_messages}
                  disabled={readOnly}
                  onChange={(n) => patch({ extract_min_new_messages: n })}
                />
              </FieldRow>
              <FieldRow
                title="Sensitive categories"
                hint={`User memory only. Empty list drops all sensitive facts. Project memory always drops ${PROJECT_DENIED_CATEGORIES.join(", ")}.`}
                detail={
                  <div className="memory-admin__chips">
                    {SENSITIVE_OPTIONS.map((cat) => (
                      <label key={cat}>
                        <input
                          type="checkbox"
                          checked={(settings.allowed_sensitive_categories || []).includes(cat)}
                          disabled={readOnly}
                          onChange={(e) => toggleCategory(cat, e.target.checked)}
                        />
                        {cat}
                      </label>
                    ))}
                  </div>
                }
              />
            </div>
          </section>

          <section className="settings-section">
            <h2>Project memory</h2>
            <p className="settings-section-desc">
              Shared team facts from project AI chats. Personal memory is never injected there.
            </p>
            <div className="settings-list">
              <FieldRow title="Automatic project memory" hint="Organization-wide kill switch">
                <Toggle
                  label="Automatic project memory"
                  on={settings.project_feature_enabled}
                  disabled={readOnly}
                  onToggle={() => patch({ project_feature_enabled: !settings.project_feature_enabled })}
                />
              </FieldRow>
              <FieldRow title="Max per project">
                <NumberInput
                  id="project-max"
                  value={settings.project_max_per_project}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_max_per_project: n })}
                />
              </FieldRow>
              <FieldRow title="Manual facts injected" hint="Owner-authored facts always included">
                <NumberInput
                  id="project-manual"
                  value={settings.project_manual_items}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_manual_items: n })}
                />
              </FieldRow>
              <FieldRow title="Inject max items">
                <NumberInput
                  id="project-inject-items"
                  value={settings.project_inject_max_items}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_inject_max_items: n })}
                />
              </FieldRow>
              <FieldRow title="Inject max chars">
                <NumberInput
                  id="project-inject-chars"
                  value={settings.project_inject_max_chars}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_inject_max_chars: n })}
                />
              </FieldRow>
              <FieldRow title="Semantic top-k">
                <NumberInput
                  id="project-semantic-k"
                  value={settings.project_semantic_top_k}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_semantic_top_k: n })}
                />
              </FieldRow>
              <FieldRow title="Lexical top-k">
                <NumberInput
                  id="project-lexical-k"
                  value={settings.project_lexical_top_k}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_lexical_top_k: n })}
                />
              </FieldRow>
              <FieldRow title="Min similarity" hint="0–1">
                <NumberInput
                  id="project-min-sim"
                  value={settings.project_min_similarity}
                  step="0.01"
                  disabled={readOnly}
                  onChange={(n) => patch({ project_min_similarity: n })}
                />
              </FieldRow>
              <FieldRow title="Debounce" hint="Seconds">
                <NumberInput
                  id="project-debounce"
                  value={settings.project_extract_debounce_seconds}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_extract_debounce_seconds: n })}
                />
              </FieldRow>
              <FieldRow title="Max wait" hint="Seconds">
                <NumberInput
                  id="project-max-wait"
                  value={settings.project_extract_max_wait_seconds}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_extract_max_wait_seconds: n })}
                />
              </FieldRow>
              <FieldRow title="Min new messages">
                <NumberInput
                  id="project-min-messages"
                  value={settings.project_extract_min_new_messages}
                  disabled={readOnly}
                  onChange={(n) => patch({ project_extract_min_new_messages: n })}
                />
              </FieldRow>
            </div>
          </section>

          <div className="dialog-actions">
            <button type="submit" className="btn" disabled={readOnly || saving}>
              {saving ? "Saving…" : "Save settings"}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={readOnly || reindexing}
              onClick={() => void onReindex()}
            >
              {reindexing ? "Reindexing…" : "Rebuild index"}
            </button>
          </div>
        </form>

        <section className="settings-section">
          <h2>Support</h2>
          <p className="settings-section-desc">Compliance purge for a single user. This cannot be undone.</p>
          <div className="settings-list">
            <FieldRow title="Purge user memories" hint="Permanently deletes every memory for this user id">
              <input
                id="memory-purge-user"
                className="settings-row__control"
                inputMode="numeric"
                value={purgeUserId}
                placeholder="User id"
                disabled={readOnly}
                aria-label="User id to purge"
                onChange={(e) => setPurgeUserId(e.target.value)}
              />
              <button
                type="button"
                className="settings-row__action settings-row__action--danger"
                disabled={readOnly}
                onClick={() => void onPurgeUser()}
              >
                Purge
              </button>
            </FieldRow>
          </div>
        </section>
      </div>
    </AdminPage>
  );
}
