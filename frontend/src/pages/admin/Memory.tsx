import { FormEvent, type ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";

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
  extract_max_tokens: number;
  extract_monthly_budget_usd: number;
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
  history_completion_enabled: boolean;
  relearn_enabled: boolean;
  context_fit_enabled: boolean;
  context_share_percent: number;
  context_default_tokens: number;
  summary_enabled: boolean;
  summary_model_id: number | null;
  summary_keep_recent: number;
  summary_monthly_budget_usd: number;
  recall_enabled: boolean;
  recall_max_items: number;
  recall_max_chars: number;
  recall_min_similarity: number;
  plan_memory_enabled: boolean;
  plan_ttl_days: number;
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

type FailedJobs = {
  scope: "user" | "project";
  total: number;
  reasons: { reason: string; count: number }[];
  jobs: {
    id: string;
    owner: string;
    reason: string;
    attempts: number;
    failed_at: string | null;
    mined_to: number;
    of: number;
  }[];
};

type RetryResult = { requeued: number; merged: number; covered: number };

type RelearnEstimate = {
  enabled: boolean;
  model_configured: boolean;
  days: number;
  chats: { user: number; project: number };
  messages: number;
  characters: number;
  parts: number;
  estimated_cost_usd: number | null;
  spent_this_month_usd: number;
  monthly_cap_usd: number;
};

type RecallStatus = {
  embedding_model_configured: boolean;
  enabled: boolean;
  indexed_chats: number;
  chunks: number;
  pending: number;
  running: number;
  failed: number;
};

type BackfillEstimate = {
  chats: number;
  messages: number;
  characters: number;
  estimated_cost_usd: number | null;
  enabled: boolean;
};

function describeRecallStatus(s: RecallStatus): string {
  const jobs = [
    s.pending ? `${s.pending.toLocaleString()} queued` : "",
    s.running ? `${s.running.toLocaleString()} running` : "",
    s.failed ? `${s.failed.toLocaleString()} failed` : "",
  ].filter(Boolean);
  return `${s.indexed_chats.toLocaleString()} chats indexed (${s.chunks.toLocaleString()} exchanges)${jobs.length ? `; ${jobs.join(", ")}` : ""}.`;
}

function describeBackfill(e: BackfillEstimate): string {
  if (!e.enabled) return "Recall is off, or no embedding model is saved: turn it on, choose one and save first.";
  if (!e.chats) return "Every chat is indexed already.";
  const cost = e.estimated_cost_usd == null ? "the embedding model has no price" : `about ${formatUsd(e.estimated_cost_usd)}`;
  return `${e.chats.toLocaleString()} chats, ${e.messages.toLocaleString()} messages not indexed yet: ${cost}.`;
}

function describeEstimate(e: RelearnEstimate): string {
  if (!e.enabled) return "Relearning is off: turn on Allow relearning and save first.";
  if (!e.model_configured) return "No extraction model is saved: choose one under Pipeline and save first.";
  const chats = e.chats.user + e.chats.project;
  if (!chats) return `Nothing to read again in the last ${e.days} days.`;
  const cost = e.estimated_cost_usd == null ? "the extraction model has no price" : `about ${formatUsd(e.estimated_cost_usd)}`;
  const cap = e.monthly_cap_usd > 0 ? ` This month: ${formatUsd(e.spent_this_month_usd)} of ${formatUsd(e.monthly_cap_usd)}; extraction pauses at the cap.` : "";
  return `${chats.toLocaleString()} chats (${e.chats.user.toLocaleString()} personal, ${e.chats.project.toLocaleString()} project), ${e.messages.toLocaleString()} messages in ${e.parts.toLocaleString()} parts: ${cost}.${cap}`;
}

/** Days to read again, as typed, brought into 1–90 (30 when nothing is typed). */
function relearnDaysIn(typed: string): number {
  const n = Math.round(Number(typed));
  if (!typed.trim() || !Number.isFinite(n)) return 30;
  return Math.max(1, Math.min(90, n));
}

const FAILED_SCOPES: { scope: FailedJobs["scope"]; label: string }[] = [
  { scope: "user", label: "Personal" },
  { scope: "project", label: "Project" },
];

type MemoryStats = {
  total_memories: number;
  memories_last_7d: number;
  jobs_by_status: Record<string, number>;
  oldest_pending_job_age_seconds: number | null;
  dead_letter_count: number;
  embedding_backlog: number;
  extraction_cost_usd_30d: number;
  extraction_cost_usd_mtd: number;
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
  actions,
}: {
  title: ReactNode;
  hint?: ReactNode;
  children?: ReactNode;
  detail?: ReactNode;
  /** Several controls in the row: on a phone they go under the title instead of squeezing it. */
  actions?: boolean;
}) {
  const classes = ["settings-row-block", detail ? "settings-row-block--open" : "", actions ? "settings-row-block--actions" : ""];
  return (
    <div className={classes.filter(Boolean).join(" ")}>
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
  /** The settings as the server has them: what Estimate, Relearn, Index and Rebuild act on. */
  const [saved, setSaved] = useState<MemorySettings | null>(null);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [models, setModels] = useState<AdminModel[]>([]);
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [purgeUserId, setPurgeUserId] = useState("");
  const [failed, setFailed] = useState<Partial<Record<FailedJobs["scope"], FailedJobs>>>({});
  /** The failed-job lists were asked for (read or not): until then "…", after it "Could not load". */
  const [failedAsked, setFailedAsked] = useState(false);
  const [retrying, setRetrying] = useState<FailedJobs["scope"] | null>(null);
  /** As typed: it is brought into 1–90 when the field is left, or used - not at every key. */
  const [relearnDays, setRelearnDays] = useState("30");
  const [estimate, setEstimate] = useState<RelearnEstimate | null>(null);
  const [relearning, setRelearning] = useState(false);
  const [recallStatus, setRecallStatus] = useState<RecallStatus | null>(null);
  const [recallStatusFailed, setRecallStatusFailed] = useState(false);
  const [backfill, setBackfill] = useState<BackfillEstimate | null>(null);
  const [backfilling, setBackfilling] = useState(false);

  async function load() {
    setError("");
    const [cfg, st, catalog] = await Promise.all([
      api<MemorySettings>("/api/admin/memory/settings"),
      api<MemoryStats>("/api/admin/memory/stats"),
      api<AdminModel[]>("/api/admin/models"),
    ]);
    setSettings(cfg);
    setSaved(cfg);
    setStats(st);
    setModels(Array.isArray(catalog) ? catalog : []);
  }

  /** The figures only: the settings being edited stay as they are. */
  async function loadStats() {
    setStats(await api<MemoryStats>("/api/admin/memory/stats"));
  }

  /** Why jobs failed: read on its own, so the page still opens if this read does not. */
  async function loadFailed() {
    const lists = await Promise.all(
      FAILED_SCOPES.map(({ scope }) =>
        api<FailedJobs>(`/api/admin/memory/failed-jobs?scope=${scope}`).catch(() => null),
      ),
    );
    const next: Partial<Record<FailedJobs["scope"], FailedJobs>> = {};
    for (const list of lists) if (list) next[list.scope] = list;
    setFailed(next);
    setFailedAsked(true);
  }

  async function onRetry(scope: FailedJobs["scope"]) {
    const total = failed[scope]?.total ?? 0;
    const ok = await confirm({
      title: "Run failed jobs again",
      message: `Send ${total} failed ${scope === "user" ? "personal" : "project"} extraction job${total === 1 ? "" : "s"} back to the queue. Each goes on from where its chat was mined to, and is billed as extraction.`,
      confirmLabel: "Run again",
    });
    if (!ok) return;
    setRetrying(scope);
    setError("");
    setFlash("");
    try {
      const result = await api<RetryResult>("/api/admin/memory/failed-jobs/retry", {
        method: "POST",
        body: JSON.stringify({ scope }),
      });
      setFlash(
        `Queued ${result.requeued} again. ${result.merged} handed to a newer job of the same chat, ${result.covered} already mined.`,
      );
      await Promise.all([loadStats(), loadFailed()]);
    } catch (err) {
      setError(String(err));
    } finally {
      setRetrying(null);
    }
  }

  /** The recall index's progress: read on its own, so the page opens whatever it says. */
  async function loadRecallStatus() {
    const status = await api<RecallStatus>("/api/admin/memory/recall/status").catch(() => null);
    setRecallStatus(status);
    setRecallStatusFailed(status === null);
  }

  async function onBackfillEstimate() {
    setError("");
    try {
      setBackfill(await api<BackfillEstimate>("/api/admin/memory/recall/backfill/estimate"));
    } catch (err) {
      setError(String(err));
    }
  }

  async function onBackfill() {
    if (!backfill) return;
    const ok = await confirm({
      title: "Index earlier chats",
      message: `Index the chats from before recall was on, so new chats can read from them. ${describeBackfill(backfill)}`,
      confirmLabel: "Index",
    });
    if (!ok) return;
    setBackfilling(true);
    setError("");
    setFlash("");
    try {
      const result = await api<{ queued: number }>("/api/admin/memory/recall/backfill", { method: "POST" });
      setFlash(`Queued ${result.queued} chats to be indexed.`);
      setBackfill(null);
      await loadRecallStatus();
    } catch (err) {
      setError(String(err));
    } finally {
      setBackfilling(false);
    }
  }

  async function onEstimate() {
    setError("");
    try {
      const days = relearnDaysIn(relearnDays);
      setRelearnDays(String(days));
      setEstimate(await api<RelearnEstimate>(`/api/admin/memory/relearn/estimate?days=${days}`));
    } catch (err) {
      setError(String(err));
    }
  }

  async function onRelearn() {
    if (!estimate) return;
    const ok = await confirm({
      title: "Relearn recent chats",
      message: `Read the last ${estimate.days} days of chats again for memory. ${describeEstimate(estimate)}`,
      confirmLabel: "Relearn",
    });
    if (!ok) return;
    setRelearning(true);
    setError("");
    setFlash("");
    try {
      const result = await api<{ queued: number; merged: number }>("/api/admin/memory/relearn", {
        method: "POST",
        body: JSON.stringify({ days: estimate.days }),
      });
      setFlash(`Queued ${result.queued} chats to be read again; ${result.merged} more join jobs already waiting.`);
      setEstimate(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setRelearning(false);
    }
  }

  useEffect(() => {
    void load().catch((err) => setError(String(err)));
    void loadFailed();
    void loadRecallStatus();
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
      setSaved(saved);
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
      await loadStats();
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
      await loadStats();
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

  /** Whether any of these settings is edited here and not saved yet. */
  function unsaved(...keys: (keyof MemorySettings)[]): boolean {
    if (!saved || !settings) return false;
    return keys.some((key) => JSON.stringify(settings[key]) !== JSON.stringify(saved[key]));
  }
  const relearnUnsaved = unsaved("feature_enabled", "relearn_enabled", "extraction_model_id");
  const recallUnsaved = unsaved("feature_enabled", "recall_enabled", "embedding_model");
  const reindexUnsaved = unsaved("embedding_model");
  const SAVE_FIRST = "Save your changes first: this acts on the saved settings.";

  const saveBar = (
    <>
      <button type="submit" form="memory-settings-form" className="btn" disabled={readOnly || saving || !settings}>
        {saving ? "Saving…" : "Save"}
      </button>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={readOnly || reindexing || !settings || reindexUnsaved}
        title={reindexUnsaved ? SAVE_FIRST : undefined}
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

  function modelLabel(id: number): string {
    const model = models.find((m) => m.id === id);
    return model ? model.display_name || model.external_id : `model ${id}`;
  }

  /** Bring a field below into view and give it the focus. */
  function focusField(id: string) {
    const field = document.getElementById(id);
    field?.scrollIntoView({ block: "center", behavior: "smooth" });
    field?.focus();
  }

  /** Switched on, but with no model to extract with: on paper, not in fact. */
  const inert = settings.feature_enabled && !settings.extraction_model_id;
  const cap = settings.extract_monthly_budget_usd || 0;
  const capped = cap > 0;
  const spentThisMonth = stats?.extraction_cost_usd_mtd ?? 0;

  return (
    <AdminPage title="Memory" actions={saveBar}>
      <div className="memory-admin">
        <p className="muted-text memory-admin__lead">
          Automatic long-term memory for personal chat and shared project facts. Extraction uses the model below
          (system cost).
        </p>
        {inert ? (
          // The master switch reads "on" and the model reads "Not configured",
          // which is a page that looks live and learns nothing. Users see a
          // banner for this in their own Memory panel; the person who can
          // actually fix it was the one not being told.
          <p className="alert alert-warning" role="status">
            <strong>Nothing is being learned.</strong> Automatic memory is on, but no extraction model is selected,
            so every conversation is skipped. Existing memories are still injected and can still be managed. Pick an{" "}
            <strong>Extraction model</strong> below to start.
          </p>
        ) : null}
        {flash ? <p className="alert alert-success">{flash}</p> : null}
        {error ? <p className="alert alert-error" role="alert">{error}</p> : null}

        <section className="settings-section memory-admin__budget" aria-label="Cost control">
          <h2>Cost control</h2>
          <p className="settings-section-desc">
            Extraction is the only thing here that spends money, and it spends it in the background with nobody
            waiting on the answer. It is billed as a system operation and is never held against a user&rsquo;s budget,
            so nothing else stops it. This is what stops it.
          </p>
          <div className="settings-list">
            <FieldRow
              title="Monthly extraction budget"
              hint={
                capped
                  ? `${formatUsd(spentThisMonth)} of ${formatUsd(cap)} used this month. At the cap, extraction pauses and resumes on the 1st; the conversations it skipped stay queued rather than being dropped.`
                  : "0 means no limit. Set a figure to pause extraction for the rest of the month once it is reached."
              }
            >
              <NumberInput
                id="memory-extract-monthly-budget-usd"
                value={settings.extract_monthly_budget_usd}
                step="1"
                min={0}
                disabled={readOnly}
                onChange={(n) => patch({ extract_monthly_budget_usd: n })}
              />
            </FieldRow>
          </div>
          <p className="memory-admin__budget-links">
            {/* The page states a number and stops. These answer the two
                questions that number raises, in the place it raises them. */}
            <Link to="/admin/reports?report=memory_cost_by_user">Spend by user →</Link>
            <Link to="/admin/reports?report=memory_cost_summary">Daily trend →</Link>
          </p>
          {capped && spentThisMonth >= cap ? (
            <p className="alert alert-warning" role="status">
              <strong>Extraction is paused.</strong> The monthly budget is spent. Nothing new is being learned in
              either scope until the 1st, or until you raise the figure above.
            </p>
          ) : null}
        </section>

        <section className="settings-section" aria-label="Setup">
          <h2>Setup</h2>
          <p className="settings-section-desc">Two models make memory work. Both are chosen under Pipeline, below.</p>
          <ol className="memory-admin__steps">
            <li data-done={settings.extraction_model_id ? "true" : "false"}>
              <span>
                <strong>Extraction model</strong> — learns facts from chats.{" "}
                {settings.extraction_model_id ? `Chosen: ${modelLabel(settings.extraction_model_id)}.` : "Not chosen: nothing is learned."}
              </span>
              <button
                type="button"
                className="btn btn-ghost"
                aria-label={`${settings.extraction_model_id ? "Change" : "Choose"} the extraction model`}
                onClick={() => focusField("memory-extraction-model")}
              >
                {settings.extraction_model_id ? "Change" : "Choose"}
              </button>
            </li>
            <li data-done={settings.embedding_model ? "true" : "false"}>
              <span>
                <strong>Embedding model</strong> — finds memories by what they mean, not only by their words, and lets
                new chats read from earlier ones.{" "}
                {settings.embedding_model
                  ? `Chosen: ${settings.embedding_model}. After changing it, Rebuild index.`
                  : "Not chosen: memories are found only by their words, and earlier chats are not recalled."}
              </span>
              <button
                type="button"
                className="btn btn-ghost"
                aria-label={`${settings.embedding_model ? "Change" : "Choose"} the embedding model`}
                onClick={() => focusField("memory-embedding-model")}
              >
                {settings.embedding_model ? "Change" : "Choose"}
              </button>
            </li>
          </ol>
        </section>

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

        <section className="settings-section memory-admin__failed" aria-label="Failed jobs">
          <h2>Failed jobs</h2>
          <p className="settings-section-desc">
            Extraction jobs that failed for good, grouped by why. Fix the cause (a model, an allowance), then run them
            again: each goes on from where its chat was mined to.
          </p>
          <div className="settings-list">
            {FAILED_SCOPES.map(({ scope, label }) => {
              const list = failed[scope];
              const total = list?.total ?? 0;
              return (
                <FieldRow
                  key={scope}
                  title={label}
                  hint={list ? (total ? `${total.toLocaleString()} failed` : "None") : failedAsked ? "Could not load" : "…"}
                  detail={
                    total ? (
                      <ul className="memory-admin__reasons">
                        {list?.reasons.map((item) => (
                          <li key={item.reason}>
                            <strong>{item.count.toLocaleString()}</strong> {item.reason}
                          </li>
                        ))}
                      </ul>
                    ) : null
                  }
                >
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={readOnly || !total || retrying !== null}
                    onClick={() => void onRetry(scope)}
                  >
                    {retrying === scope ? "Queuing…" : "Run again"}
                  </button>
                </FieldRow>
              );
            })}
          </div>
        </section>

        <section className="settings-section" aria-label="Relearn recent chats">
          <h2>Relearn recent chats</h2>
          <p className="settings-section-desc">
            Read the last days of chats again, for what extraction dropped before it read long chats in parts. Only
            chats of people and projects with automatic learning on, never private ones, and nothing said before a
            person&rsquo;s last &ldquo;Delete all&rdquo; or settings change. By hand only, billed as extraction.
          </p>
          <div className="settings-list">
            <FieldRow title="Allow relearning" hint="Off by default. Takes effect when the settings are saved.">
              <Toggle
                label="Allow relearning"
                on={settings.relearn_enabled}
                disabled={readOnly}
                onToggle={() => patch({ relearn_enabled: !settings.relearn_enabled })}
              />
            </FieldRow>
            <FieldRow
              title="Days to read again"
              hint="1–90"
              actions
              detail={
                relearnUnsaved ? (
                  <p className="memory-admin__estimate">{SAVE_FIRST}</p>
                ) : estimate ? (
                  <p className="memory-admin__estimate">{describeEstimate(estimate)}</p>
                ) : null
              }
            >
              <input
                id="memory-relearn-days"
                type="number"
                className="settings-row__control"
                min={1}
                max={90}
                value={relearnDays}
                aria-label="memory relearn days"
                onChange={(e) => {
                  setRelearnDays(e.target.value);
                  setEstimate(null);
                }}
                onBlur={() => setRelearnDays(String(relearnDaysIn(relearnDays)))}
              />
              <button type="button" className="btn btn-ghost" disabled={relearnUnsaved} onClick={() => void onEstimate()}>
                Estimate
              </button>
              <button
                type="button"
                className="btn"
                disabled={
                  readOnly ||
                  relearning ||
                  relearnUnsaved ||
                  !estimate?.enabled ||
                  !estimate.model_configured ||
                  !(estimate.chats.user + estimate.chats.project)
                }
                onClick={() => void onRelearn()}
              >
                {relearning ? "Queuing…" : "Relearn"}
              </button>
            </FieldRow>
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
              <FieldRow
                title="Extractor answer length"
                hint="Tokens, 256–16,000, the model's thinking included. An answer cut off keeps what it finished; one cut off before its first fact is asked again of a smaller part of the chat."
              >
                <NumberInput
                  id="memory-extract-max-tokens"
                  value={settings.extract_max_tokens}
                  step="100"
                  min={256}
                  disabled={readOnly}
                  onChange={(n) => patch({ extract_max_tokens: n })}
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

          <section className="settings-section" aria-label="Chat history">
            <h2>Chat history</h2>
            <p className="settings-section-desc">What the model is given of the chat it is answering in.</p>
            <div className="settings-list">
              <FieldRow
                title="Complete history on the server"
                hint="The browser sends the part of a chat it holds (a chat opened from the list holds its latest page); the server puts the older messages in front before the model answers. Off: the model reads only what the browser holds. Never for a private chat."
              >
                <Toggle
                  label="Complete history on the server"
                  on={settings.history_completion_enabled}
                  disabled={readOnly}
                  onToggle={() => patch({ history_completion_enabled: !settings.history_completion_enabled })}
                />
              </FieldRow>
            </div>
          </section>

          <section className="settings-section" aria-label="Long chats">
            <h2>Long chats</h2>
            <p className="settings-section-desc">
              What happens when a chat is longer than the model&rsquo;s context window. The newest messages always go
              word for word; the oldest give way to a summary, or are left out with a note to the model.
            </p>
            <div className="settings-list">
              <FieldRow
                title="Fit each turn into the model's window"
                hint="Measured before sending, so a long chat never ends in a context-length error. A turn with tools is never cut."
              >
                <Toggle
                  label="Fit each turn into the model's window"
                  on={settings.context_fit_enabled}
                  disabled={readOnly}
                  onToggle={() => patch({ context_fit_enabled: !settings.context_fit_enabled })}
                />
              </FieldRow>
              <FieldRow
                title="Share of the window for the chat"
                hint="Percent, 30–95. A turn that leaves the model room to answer goes whole; one that does not is brought down to this share."
              >
                <NumberInput
                  id="memory-context-share"
                  value={settings.context_share_percent}
                  min={30}
                  disabled={readOnly || !settings.context_fit_enabled}
                  onChange={(n) => patch({ context_share_percent: n })}
                />
              </FieldRow>
              <FieldRow
                title="Window of an unknown model"
                hint="Tokens, for a model neither the catalog nor LiteLLM knows. 0 sends its turns as they are."
              >
                <NumberInput
                  id="memory-context-default"
                  value={settings.context_default_tokens}
                  min={0}
                  step="1000"
                  disabled={readOnly || !settings.context_fit_enabled}
                  onChange={(n) => patch({ context_default_tokens: n })}
                />
              </FieldRow>
              <FieldRow
                title="Summarize long chats"
                hint={
                  settings.summary_model_id
                    ? "Keeps a summary of each long chat's older messages, in the background, for the turns that cannot take them all. Never for private chats."
                    : "Needs a summary model. Without one, the oldest messages are left out with a note."
                }
              >
                <Toggle
                  label="Summarize long chats"
                  on={settings.summary_enabled}
                  disabled={readOnly || !settings.context_fit_enabled}
                  onToggle={() => patch({ summary_enabled: !settings.summary_enabled })}
                />
              </FieldRow>
              <FieldRow title="Summary model" hint="A cheap, fast text model. Cost is billed as chat_summary, never against a budget.">
                <SearchableModelSelect
                  id="memory-summary-model"
                  ariaLabel="Summary model"
                  value={settings.summary_model_id ? String(settings.summary_model_id) : ""}
                  disabled={readOnly}
                  emptyLabel="Not configured"
                  placeholder="Search summary models…"
                  options={textModels.map((m) => ({
                    value: String(m.id),
                    label: `${m.display_name || m.external_id} · ${m.provider}`,
                  }))}
                  onChange={(next) => patch({ summary_model_id: next ? Number(next) : null })}
                />
              </FieldRow>
              <FieldRow title="Newest messages kept word for word" hint="4–200. Also what fitting keeps without a summary.">
                <NumberInput
                  id="memory-summary-keep"
                  value={settings.summary_keep_recent}
                  min={4}
                  disabled={readOnly}
                  onChange={(n) => patch({ summary_keep_recent: n })}
                />
              </FieldRow>
              <FieldRow title="Monthly summary budget" hint="US dollars. 0 means no limit; at the cap, summaries wait for the 1st.">
                <NumberInput
                  id="memory-summary-budget"
                  value={settings.summary_monthly_budget_usd}
                  step="1"
                  min={0}
                  disabled={readOnly}
                  onChange={(n) => patch({ summary_monthly_budget_usd: n })}
                />
              </FieldRow>
            </div>
          </section>

          <section className="settings-section" aria-label="Earlier chats">
            <h2>Earlier chats</h2>
            <p className="settings-section-desc">
              A new turn reads the related parts of the person&rsquo;s other chats: a personal chat from their personal
              chats, a project chat from the same project&rsquo;s. Never private chats or rooms. Each person can turn it
              off for their personal chats, and it is off for them while their memory is off; a project chat follows
              project memory and the project&rsquo;s own memory switch.
            </p>
            {settings.embedding_model ? null : (
              <p className="alert alert-info" role="status">
                Recall needs an embedding model (Pipeline, below). Until one is chosen, nothing is indexed or recalled.
              </p>
            )}
            <div className="settings-list">
              <FieldRow
                title="Recall earlier chats"
                hint={
                  recallStatus
                    ? describeRecallStatus(recallStatus)
                    : recallStatusFailed
                      ? "Could not load how far the index has got."
                      : "On by default once an embedding model is chosen."
                }
              >
                <Toggle
                  label="Recall earlier chats"
                  on={settings.recall_enabled && Boolean(settings.embedding_model)}
                  disabled={readOnly || !settings.embedding_model}
                  onToggle={() => patch({ recall_enabled: !settings.recall_enabled })}
                />
              </FieldRow>
              <FieldRow title="Pieces per turn" hint="1–10 exchanges or chat digests, the most similar first.">
                <NumberInput
                  id="memory-recall-items"
                  value={settings.recall_max_items}
                  min={1}
                  disabled={readOnly}
                  onChange={(n) => patch({ recall_max_items: n })}
                />
              </FieldRow>
              <FieldRow title="Characters per turn" hint="500–12,000, all pieces together.">
                <NumberInput
                  id="memory-recall-chars"
                  value={settings.recall_max_chars}
                  min={500}
                  step="500"
                  disabled={readOnly}
                  onChange={(n) => patch({ recall_max_chars: n })}
                />
              </FieldRow>
              <FieldRow title="Minimum similarity" hint="0–1. Higher recalls less, and only what is closer.">
                <NumberInput
                  id="memory-recall-similarity"
                  value={settings.recall_min_similarity}
                  step="0.05"
                  min={0}
                  disabled={readOnly}
                  onChange={(n) => patch({ recall_min_similarity: n })}
                />
              </FieldRow>
              <FieldRow
                title="Index earlier chats"
                actions
                hint="Chats are indexed as they go on. The ones from before recall was on are indexed only from here."
                detail={
                  recallUnsaved ? (
                    <p className="memory-admin__estimate">{SAVE_FIRST}</p>
                  ) : backfill ? (
                    <p className="memory-admin__estimate">{describeBackfill(backfill)}</p>
                  ) : null
                }
              >
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={recallUnsaved}
                  onClick={() => void onBackfillEstimate()}
                >
                  Estimate
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={readOnly || backfilling || recallUnsaved || !backfill?.enabled || !backfill.chats}
                  onClick={() => void onBackfill()}
                >
                  {backfilling ? "Queuing…" : "Index"}
                </button>
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
                title="Remember ongoing plans and routines"
                hint="A workout plan, a diet, a current project: kept while the person keeps mentioning it."
              >
                <Toggle
                  label="Remember ongoing plans and routines"
                  on={settings.plan_memory_enabled}
                  disabled={readOnly}
                  onToggle={() => patch({ plan_memory_enabled: !settings.plan_memory_enabled })}
                />
              </FieldRow>
              <FieldRow title="Plans last" hint="Days, 7–365, counted again each time a plan is mentioned.">
                <NumberInput
                  id="memory-plan-days"
                  value={settings.plan_ttl_days}
                  min={7}
                  disabled={readOnly || !settings.plan_memory_enabled}
                  onChange={(n) => patch({ plan_ttl_days: n })}
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
              disabled={readOnly || reindexing || reindexUnsaved}
              title={reindexUnsaved ? SAVE_FIRST : undefined}
              onClick={() => void onReindex()}
            >
              {reindexing ? "Reindexing…" : "Rebuild index"}
            </button>
            {reindexUnsaved ? <span className="muted-text">{SAVE_FIRST}</span> : null}
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
