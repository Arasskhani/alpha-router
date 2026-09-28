import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { api, formatApiError } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import CopyValue from "../CopyValue";
import SearchableModelSelect from "./SearchableModelSelect";

/**
 * The browser extension's settings, on the Chat Tools page.
 *
 * Who may use the extension and its agent is the two rows above it in the
 * tools table (Browser extension, Browser agent). This is the rest: which
 * sites it may read and act on, which models may receive page content, the
 * agent's limits, and what IT needs to install it for everyone.
 */

type SiteAccess = "per_site" | "all_sites";

/** The relaxable approvals, in the order the card shows them, with what each says. */
const APPROVALS: { key: string; label: string; hint: string }[] = [
  { key: "send", label: "Sending messages and emails", hint: "A send button, a reply, a post; Enter in a message box." },
  { key: "submit", label: "Submitting forms", hint: "Pressing a form's send button." },
  { key: "delete", label: "Deleting", hint: "Delete, remove, discard (deleting for good is never allowed)." },
  { key: "leave_sites", label: "Going to another site", hint: "A link, an address or a tab on a site other than the one it is on." },
  { key: "downloads", label: "Downloads", hint: "Saving a file (a program is never downloaded)." },
  { key: "uploads", label: "Uploads", hint: "Choosing or dropping a file into the page." },
  { key: "dialogs", label: "The page's dialogs", hint: "A confirm or prompt the page opens; relaxed, a confirm is accepted and a prompt dismissed." },
];
const APPROVAL_KEYS = APPROVALS.map((a) => a.key);

type AgentMode = "ask" | "plan" | "auto";

type ExtensionSettings = {
  site_access: SiteAccess;
  allowed_sites: string[];
  blocked_sites: string[];
  read_only_sites: string[];
  protected_sites: string[];
  internal_sites: string[];
  internal_models: string[];
  screenshot_models: string[];
  page_content_models: string[];
  agent_models: string[];
  agent_max_steps: number;
  agent_auto_mode: boolean;
  agent_review_model: string | null;
  agent_recommended_model: string | null;
  full_control: boolean;
  enabled: boolean;
  relaxed_approvals: string[];
  require_newest_package: boolean;
  min_browser_version: number;
  internal_connections: number[];
  external_screenshots: boolean;
  plan_mode: boolean;
  agent_default_mode: AgentMode;
  agent_max_minutes: number;
  agent_max_tabs: number;
  agent_runs_per_day: number | null;
  screenshot_max_side: number;
  screenshots_kept: number;
  screenshot_after_action: boolean;
  save_runs: boolean;
  private_runs: boolean;
};

/** A connection the card can offer to tick as inside the organisation. */
type ConnectionChoice = {
  id: number;
  name: string;
  provider: string | null;
  host: string;
  active: boolean;
  looks_internal: boolean;
  state: "ok" | "deleted";
};

type Distribution = {
  available: boolean;
  reason: string | null;
  version: string | null;
  extension_id: string | null;
  update_url: string | null;
  gpo_value: string | null;
  key_status: "ok" | "not_created" | "unreadable";
  key_message: string | null;
};

/** A model the card can offer, or one the settings name that is no longer on offer. */
type ModelChoice = {
  ref: string;
  label: string;
  provider: string | null;
  state: "ok" | "disabled" | "not_chat" | "deleted";
  connection_id?: number | null;
  /** Whether it reads images: only such a model can see screenshots, or be probed. */
  vision?: boolean;
};

/** The last browser_control probe of a model: could it point at a button on a made-up page? */
type ProbeResult = {
  model_ref: string;
  ran_at: string;
  vision: boolean;
  tool_calling: boolean;
  hits: number;
  trials: number;
  passed: boolean;
  detail: string;
};

type Overview = {
  settings: ExtensionSettings;
  models: ModelChoice[];
  connections?: ConnectionChoice[];
  distribution: Distribution;
  probes?: Record<string, ProbeResult>;
};

const PROBE_PATH = "/api/admin/extension/probe";

/**
 * The form keeps what the administrator types: the site lists one pattern per
 * line, and the steps as text, so the field can be cleared and typed again.
 */
/** The numbers the card takes as text, each with its range and what to call it when it is out of range. */
const NUMBERS = {
  agent_max_steps: { min: 5, max: 100, label: "Most steps per task" },
  agent_max_minutes: { min: 1, max: 180, label: "Most minutes per task" },
  agent_max_tabs: { min: 1, max: 50, label: "Most tabs per task" },
  agent_runs_per_day: { min: 1, max: 1000, label: "Runs per person per day", optional: true },
  screenshot_max_side: { min: 800, max: 1600, label: "A screenshot's longest side" },
  screenshots_kept: { min: 1, max: 4, label: "Screenshots kept" },
  min_browser_version: { min: 116, max: 999, label: "Minimum browser version" },
} as const;
type NumberKey = keyof typeof NUMBERS;

type Form = Omit<
  ExtensionSettings,
  "allowed_sites" | "blocked_sites" | "read_only_sites" | "protected_sites" | "internal_sites" | NumberKey
> & {
  allowed_sites: string;
  blocked_sites: string;
  read_only_sites: string;
  protected_sites: string;
  internal_sites: string;
} & Record<NumberKey, string>;

const SETTINGS_PATH = "/api/admin/extension/settings";
const MIN_STEPS = NUMBERS.agent_max_steps.min;
const MAX_STEPS = NUMBERS.agent_max_steps.max;

function toForm(settings: ExtensionSettings): Form {
  return {
    ...settings,
    allowed_sites: settings.allowed_sites.join("\n"),
    blocked_sites: settings.blocked_sites.join("\n"),
    read_only_sites: settings.read_only_sites.join("\n"),
    protected_sites: settings.protected_sites.join("\n"),
    internal_sites: settings.internal_sites.join("\n"),
    agent_max_steps: String(settings.agent_max_steps),
    agent_max_minutes: String(settings.agent_max_minutes ?? 20),
    agent_max_tabs: String(settings.agent_max_tabs ?? 10),
    agent_runs_per_day: settings.agent_runs_per_day == null ? "" : String(settings.agent_runs_per_day),
    screenshot_max_side: String(settings.screenshot_max_side ?? 1280),
    screenshots_kept: String(settings.screenshots_kept ?? 3),
    min_browser_version: String(settings.min_browser_version ?? 116),
  };
}

/** A number the card took as text, checked against its range; a message when it is not usable. */
export function numberField(key: NumberKey, raw: string): { value: number | null } | { error: string } {
  const spec = NUMBERS[key];
  const text = raw.trim();
  if (!text && "optional" in spec && spec.optional) return { value: null };
  const value = Number(text || Number.NaN);
  if (!Number.isInteger(value) || value < spec.min || value > spec.max) {
    const empty = "optional" in spec && spec.optional ? ", or empty" : "";
    return { error: `${spec.label} must be a whole number from ${spec.min} to ${spec.max}${empty}.` };
  }
  return { value };
}

export function siteLines(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function isOverview(value: unknown): value is Overview {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<Overview>;
  return Boolean(
    v.settings &&
      typeof v.settings === "object" &&
      Array.isArray(v.models) &&
      v.distribution &&
      typeof v.distribution === "object",
  );
}

/** Why a model the settings name is not on offer any more. */
const UNAVAILABLE: Record<Exclude<ModelChoice["state"], "ok">, string> = {
  disabled: "turned off",
  not_chat: "not a chat model",
  deleted: "no longer exists",
};

function choiceLabel(choice: ModelChoice): string {
  return choice.provider ? `${choice.label} · ${choice.provider}` : choice.label;
}

/** The choice a selected ref stands for, even when the server no longer lists it. */
function choiceFor(ref: string, models: ModelChoice[]): ModelChoice {
  return models.find((m) => m.ref === ref) ?? { ref, label: ref, provider: null, state: "deleted" };
}

function unavailableNote(choice: ModelChoice): string | null {
  return choice.state === "ok" ? null : UNAVAILABLE[choice.state];
}

/** Enter in a search box filters; it must not submit the settings form around it. */
function keepEnterHere(event: KeyboardEvent<HTMLInputElement>) {
  if (event.key === "Enter") event.preventDefault();
}

function ModelChecklist({
  label,
  models,
  selected,
  disabled,
  onChange,
}: {
  label: string;
  models: ModelChoice[];
  selected: string[];
  disabled: boolean;
  onChange: (next: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const chosen = new Set(selected);
  const offered = models.filter((m) => m.state === "ok");
  // Selected but no longer on offer: shown first, whatever the search, so a
  // restriction nobody could see can be seen and removed.
  const stale = selected.filter((ref) => !offered.some((m) => m.ref === ref)).map((ref) => choiceFor(ref, models));
  const q = query.trim().toLowerCase();
  const shown = q ? offered.filter((m) => `${m.label} ${m.ref} ${m.provider ?? ""}`.toLowerCase().includes(q)) : offered;
  const toggle = (ref: string) => onChange(chosen.has(ref) ? selected.filter((x) => x !== ref) : [...selected, ref]);
  return (
    <div className="api-key-conn-picker">
      {offered.length > 8 ? (
        <input
          type="search"
          className="input-block"
          placeholder="Search models…"
          aria-label={`Search ${label.toLowerCase()}`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={keepEnterHere}
          disabled={disabled}
        />
      ) : null}
      <div className="api-key-conn-picker__list" role="group" aria-label={label}>
        {stale.map((m) => (
          <label key={m.ref} className="api-key-conn-picker__option extension-admin__stale-model">
            <input type="checkbox" checked disabled={disabled} onChange={() => toggle(m.ref)} />
            <span>
              {choiceLabel(m)}
              <span className="muted-text"> — {unavailableNote(m)}; still limits the choice until removed</span>
            </span>
          </label>
        ))}
        {shown.length === 0 ? (
          <p className="muted-text api-key-form__hint">{offered.length ? "No models match this search." : "No enabled chat models."}</p>
        ) : (
          shown.map((m) => (
            <label key={m.ref} className="api-key-conn-picker__option">
              <input type="checkbox" checked={chosen.has(m.ref)} disabled={disabled} onChange={() => toggle(m.ref)} />
              <span>
                {m.label}
                {m.provider ? <span className="muted-text"> · {m.provider}</span> : null}
              </span>
            </label>
          ))
        )}
      </div>
    </div>
  );
}

function ConnectionChecklist({
  connections,
  selected,
  disabled,
  onChange,
}: {
  connections: ConnectionChoice[];
  selected: number[];
  disabled: boolean;
  onChange: (next: number[]) => void;
}) {
  const chosen = new Set(selected);
  const toggle = (id: number) => onChange(chosen.has(id) ? selected.filter((x) => x !== id) : [...selected, id].sort((a, b) => a - b));
  const suggested = connections.filter((c) => c.state === "ok" && c.looks_internal && !chosen.has(c.id)).map((c) => c.id);
  if (!connections.length) return <p className="muted-text api-key-form__hint">No connections yet.</p>;
  return (
    <div className="api-key-conn-picker">
      <div className="api-key-conn-picker__list" role="group" aria-label="Connections inside the organisation">
        {connections.map((c) => (
          <label key={c.id} className={`api-key-conn-picker__option${c.state === "deleted" ? " extension-admin__stale-model" : ""}`}>
            <input type="checkbox" checked={chosen.has(c.id)} disabled={disabled} onChange={() => toggle(c.id)} />
            <span>
              {c.name}
              {c.provider ? <span className="muted-text"> · {c.provider}</span> : null}
              {c.host ? <span className="muted-text"> · {c.host}</span> : null}
              {c.state === "deleted" ? <span className="muted-text"> — no longer exists; still counts until removed</span> : null}
              {c.looks_internal ? <span className="extension-admin__tag"> looks internal</span> : null}
              {!c.active && c.state === "ok" ? <span className="muted-text"> (inactive)</span> : null}
            </span>
          </label>
        ))}
      </div>
      {suggested.length ? (
        <button type="button" className="btn btn--ghost" disabled={disabled} onClick={() => onChange([...selected, ...suggested].sort((a, b) => a - b))}>
          Tick the {suggested.length === 1 ? "one" : String(suggested.length)} that {suggested.length === 1 ? "looks" : "look"} internal
        </button>
      ) : null}
    </div>
  );
}

function probeSummary(result: ProbeResult | undefined): { text: string; tone: "ok" | "bad" | "none" } {
  if (!result) return { text: "Not probed yet", tone: "none" };
  const when = new Date(result.ran_at);
  const date = Number.isNaN(when.getTime()) ? "" : ` (${when.toLocaleDateString()})`;
  if (!result.vision) return { text: `Reads no images${date}`, tone: "bad" };
  if (!result.tool_calling) return { text: `No tool call${date}`, tone: "bad" };
  return { text: `${result.passed ? "Passed" : "Failed"}: ${result.hits} of ${result.trials}${date}`, tone: result.passed ? "ok" : "bad" };
}

function ProbeTable({
  models,
  probes,
  probing,
  disabled,
  onProbe,
}: {
  models: ModelChoice[];
  probes: Record<string, ProbeResult>;
  probing: string | null;
  disabled: boolean;
  onProbe: (ref: string) => void;
}) {
  const candidates = models.filter((m) => m.state === "ok" && m.vision);
  if (!candidates.length) return <p className="muted-text api-key-form__hint">No enabled chat model reads images.</p>;
  return (
    <table className="extension-admin__probes">
      <thead>
        <tr>
          <th scope="col">Model</th>
          <th scope="col">Last probe</th>
          <th scope="col">
            <span className="sr-only">Run</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((m) => {
          const summary = probeSummary(probes[m.ref]);
          return (
            <tr key={m.ref}>
              <td>{choiceLabel(m)}</td>
              <td className={`extension-admin__probe extension-admin__probe--${summary.tone}`} title={probes[m.ref]?.detail}>
                {summary.text}
              </td>
              <td>
                {disabled ? null : (
                  <button type="button" className="btn btn--ghost" disabled={probing !== null} onClick={() => onProbe(m.ref)}>
                    {probing === m.ref ? "Probing…" : "Run probe"}
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function ExtensionSettingsCard() {
  const readOnly = useReadOnly();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  // One request: the models come with the settings, so the card works for an
  // administrator who may manage Chat Tools but not the Models menu.
  useEffect(() => {
    let cancelled = false;
    api<Overview>(SETTINGS_PATH)
      .then((loaded) => {
        if (cancelled) return;
        if (!isOverview(loaded)) throw new Error("The browser extension settings could not be read.");
        setOverview(loaded);
        setForm(toForm(loaded.settings));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const models = overview?.models ?? [];
  const connections = overview?.connections ?? [];
  const probes = overview?.probes ?? {};
  const [probing, setProbing] = useState<string | null>(null);

  /** Run the browser_control probe on one model; the result replaces the last one shown. */
  async function probe(ref: string) {
    if (readOnly || probing) return;
    setProbing(ref);
    setError("");
    setNotice("");
    try {
      const result = await api<ProbeResult>(`${PROBE_PATH}/${encodeURIComponent(ref)}`, { method: "POST" });
      setOverview((current) => (current ? { ...current, probes: { ...(current.probes ?? {}), [ref]: result } } : current));
    } catch (err) {
      setError(`The probe could not run: ${formatApiError(err)}`);
    } finally {
      setProbing(null);
    }
  }

  function patch(values: Partial<Form>) {
    setForm((current) => (current ? { ...current, ...values } : current));
    setNotice("");
  }

  /** The approvals are shown as "always ask": ticked means it asks (not relaxed). */
  function setAsks(key: string, asks: boolean) {
    setForm((current) => {
      if (!current) return current;
      const relaxed = new Set(current.relaxed_approvals);
      if (asks) relaxed.delete(key);
      else relaxed.add(key);
      return { ...current, relaxed_approvals: APPROVAL_KEYS.filter((k) => relaxed.has(k)) };
    });
    setNotice("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form || readOnly) return;
    const numbers: Partial<Record<NumberKey, number | null>> = {};
    for (const key of Object.keys(NUMBERS) as NumberKey[]) {
      const checked = numberField(key, form[key]);
      if ("error" in checked) {
        setNotice("");
        setError(checked.error);
        return;
      }
      numbers[key] = checked.value;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await api<Overview>(SETTINGS_PATH, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          allowed_sites: siteLines(form.allowed_sites),
          blocked_sites: siteLines(form.blocked_sites),
          read_only_sites: siteLines(form.read_only_sites),
          protected_sites: siteLines(form.protected_sites),
          internal_sites: siteLines(form.internal_sites),
          ...numbers,
          agent_review_model: form.agent_review_model || null,
          agent_recommended_model: form.agent_recommended_model || null,
        }),
      });
      if (!isOverview(saved)) throw new Error("The browser extension settings could not be read back.");
      setOverview(saved);
      setForm(toForm(saved.settings));
      setNotice("Browser extension settings saved.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const locked = readOnly || saving;
  const distribution = overview?.distribution;
  const offered = models.filter((m) => m.state === "ok");
  const review = form?.agent_review_model ? choiceFor(form.agent_review_model, models) : null;
  const reviewNote = review ? unavailableNote(review) : null;
  // The model the Agent tab starts with: one of the agent's models when they are listed.
  const recommendedOptions = offered
    .filter((m) => !form?.agent_models.length || form.agent_models.includes(m.ref))
    .map((m) => ({ value: m.ref, label: choiceLabel(m) }));
  const reviewOptions = [
    // A review model that is no longer on offer is still shown by name, so the
    // administrator sees what is set and why it has to change.
    ...(review && reviewNote ? [{ value: review.ref, label: `${choiceLabel(review)} (${reviewNote})` }] : []),
    ...offered.map((m) => ({ value: m.ref, label: choiceLabel(m) })),
  ];

  return (
    <section className="settings-section extension-admin" aria-labelledby="extension-admin-title">
      <h2 id="extension-admin-title">Browser extension</h2>
      <p className="settings-section-desc">
        Who may use the extension and its agent is set in the table above (Browser extension, Browser agent). These
        settings apply to everyone who uses it. Changes are recorded in Admin Logs.
      </p>
      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="alert alert-success" role="status">
          {notice}
        </p>
      ) : null}
      {!form ? (
        error ? null : <p className="muted-text">Loading…</p>
      ) : (
        <form onSubmit={(e) => void save(e)}>
          <label className="extension-admin__choice">
            <input
              type="checkbox"
              checked={form.enabled}
              disabled={locked}
              onChange={(e) => patch({ enabled: e.target.checked })}
            />
            <span>
              <strong>Browser extension on for the organisation</strong>
              <span className="muted-text">
                Turning it off stops the extension for everyone at once and refuses new connections, whatever the Chat
                Tools grants say.
              </span>
            </span>
          </label>

          <label className="extension-admin__choice">
            <input
              type="checkbox"
              checked={form.require_newest_package}
              disabled={locked}
              onChange={(e) => patch({ require_newest_package: e.target.checked })}
            />
            <span>
              <strong>Require the newest package for the agent</strong>
              <span className="muted-text">
                A browser on an older package - or one that has not said which it runs - gets no agent step until
                the person downloads the package again and loads it. Chat and page questions still work.
              </span>
            </span>
          </label>
          <label className="extension-admin__field extension-admin__field--inline">
            <span className="settings-row__title">
              Minimum browser version
              <span className="settings-row__hint">
                Chrome or Edge major version the package needs; raising it releases a new package. 116 is the
                extension's own minimum.
              </span>
            </span>
            <input
              type="number"
              className="settings-row__control"
              min={NUMBERS.min_browser_version.min}
              max={NUMBERS.min_browser_version.max}
              step={1}
              value={form.min_browser_version}
              disabled={locked}
              onChange={(e) => patch({ min_browser_version: e.target.value })}
            />
          </label>

          <fieldset className="extension-admin__group" disabled={locked}>
            <legend>Site access</legend>
            <label className="extension-admin__choice">
              <input
                type="radio"
                name="extension-site-access"
                checked={form.site_access === "per_site"}
                onChange={() => patch({ site_access: "per_site" })}
              />
              <span>
                <strong>Ask per site</strong>
                <span className="muted-text">Chrome asks each person the first time the extension reads a site.</span>
              </span>
            </label>
            <label className="extension-admin__choice">
              <input
                type="radio"
                name="extension-site-access"
                checked={form.site_access === "all_sites"}
                onChange={() => patch({ site_access: "all_sites" })}
              />
              <span>
                <strong>All sites</strong>
                <span className="muted-text">
                  Granted when the extension is installed, silently with Group Policy. Changing this releases a new
                  version of the extension, and installed copies update to it.
                </span>
              </span>
            </label>
          </fieldset>

          <div className="extension-admin__sites">
            <label className="extension-admin__field">
              <span className="settings-row__title">Allowed sites</span>
              <textarea
                className="input-block mono"
                rows={4}
                value={form.allowed_sites}
                disabled={locked}
                placeholder={"One per line: example.com, or *.example.com for all its subdomains"}
                onChange={(e) => patch({ allowed_sites: e.target.value })}
              />
              <span className="settings-row__hint">Empty: every site except the blocked ones.</span>
            </label>
            <label className="extension-admin__field">
              <span className="settings-row__title">Blocked sites</span>
              <textarea
                className="input-block mono"
                rows={4}
                value={form.blocked_sites}
                disabled={locked}
                placeholder={"One per line: bank.example, *.hr.example"}
                onChange={(e) => patch({ blocked_sites: e.target.value })}
              />
              <span className="settings-row__hint">
                Always wins over the allowed list. The extension checks these before it reads or does anything, and
                the server checks every page it is sent.
              </span>
            </label>
            <label className="extension-admin__field">
              <span className="settings-row__title">Read-only sites</span>
              <textarea
                className="input-block mono"
                rows={3}
                value={form.read_only_sites}
                disabled={locked}
                placeholder={"One per line: wiki.example.com"}
                onChange={(e) => patch({ read_only_sites: e.target.value })}
              />
              <span className="settings-row__hint">The agent reads these, and never acts on them.</span>
            </label>
            <label className="extension-admin__field">
              <span className="settings-row__title">Protected sites</span>
              <textarea
                className="input-block mono"
                rows={3}
                value={form.protected_sites}
                disabled={locked}
                placeholder={"One per line: *.shaparak.ir, bank.example"}
                onChange={(e) => patch({ protected_sites: e.target.value })}
              />
              <span className="settings-row__hint">
                The agent never acts here at all: payment gateways, banks — whatever must stay the person's own.
              </span>
            </label>
          </div>

          <div className="extension-admin__field">
            <span className="settings-row__title">Models that may receive page content</span>
            <ModelChecklist
              label="Models that may receive page content"
              models={models}
              selected={form.page_content_models}
              disabled={locked}
              onChange={(next) => patch({ page_content_models: next })}
            />
            <span className="settings-row__hint">None selected: any model the person may use.</span>
          </div>

          <h3 className="settings-subsection-title">Browser agent</h3>
          <div className="extension-admin__field">
            <span className="settings-row__title">Models the agent may use</span>
            <ModelChecklist
              label="Models the agent may use"
              models={models}
              selected={form.agent_models}
              disabled={locked}
              onChange={(next) => patch({ agent_models: next })}
            />
            <span className="settings-row__hint">
              None selected: the models that passed the browser control check below - models that see the page and
              land their clicks - and, until one has, any model the person may use. The agent sends what it reads on
              pages to its model, so the model must also be one that may receive page content.
            </span>
          </div>
          <div className="extension-admin__field">
            <span className="settings-row__title">Recommended agent model</span>
            <SearchableModelSelect
              id="extension-recommended-model"
              ariaLabel="Recommended agent model"
              value={form.agent_recommended_model ?? ""}
              disabled={locked}
              emptyLabel="The best in the check"
              placeholder="Search models…"
              options={recommendedOptions}
              onChange={(next) => patch({ agent_recommended_model: next || null })}
            />
            <span className="settings-row__hint">What the Agent tab starts with, unless the person chose another.</span>
          </div>
          <label className="extension-admin__field extension-admin__field--inline">
            <span className="settings-row__title">Most steps per task</span>
            <input
              type="number"
              className="settings-row__control"
              min={MIN_STEPS}
              max={MAX_STEPS}
              step={1}
              value={form.agent_max_steps}
              disabled={locked}
              onChange={(e) => patch({ agent_max_steps: e.target.value })}
            />
          </label>
          <label className="extension-admin__choice">
            <input
              type="checkbox"
              checked={form.agent_auto_mode}
              disabled={locked}
              onChange={(e) => patch({ agent_auto_mode: e.target.checked })}
            />
            <span>
              <strong>Auto mode</strong>
              <span className="muted-text">
                Lets the agent act without asking on allowed sites. Every action is first checked against the
                person's request by the review model, and anything it doubts is asked about. Payments are never
                made; sending, submitting, deleting, confirming, transferring and downloading always ask first.
              </span>
            </span>
          </label>
          <label className="extension-admin__choice">
            <input
              type="checkbox"
              checked={form.full_control}
              disabled={locked}
              onChange={(e) => patch({ full_control: e.target.checked })}
            />
            <span>
              <strong>Full control</strong>
              <span className="muted-text">
                Lets the agent use a real mouse and keyboard on the page and see it in screenshots, for people who
                also have the Browser Control tool and a model that reads images. It adds the debugger permission
                to the extension package, so people load the new package; Chrome shows its debugging bar while the
                agent runs. The same rules apply as for every other action.
              </span>
            </span>
          </label>
          <div className="extension-admin__field">
            <span className="settings-row__title">Review model</span>
            <SearchableModelSelect
              id="extension-review-model"
              ariaLabel="Review model"
              value={form.agent_review_model ?? ""}
              disabled={locked}
              emptyLabel="None"
              placeholder="Search models…"
              options={reviewOptions}
              onChange={(next) => patch({ agent_review_model: next || null })}
            />
            {reviewNote ? (
              <span className="settings-row__hint extension-admin__warning">
                The review model is {reviewNote}: choose another, or None.
              </span>
            ) : null}
            <span className="settings-row__hint">Required for Auto mode. Its cost is billed to the person.</span>
          </div>
          <label className="extension-admin__choice">
            <input
              type="checkbox"
              checked={form.plan_mode}
              disabled={locked}
              onChange={(e) => patch({ plan_mode: e.target.checked, ...(form.agent_default_mode === "plan" && !e.target.checked ? { agent_default_mode: "ask" as const } : {}) })}
            />
            <span>
              <strong>Plan mode</strong>
              <span className="muted-text">
                The agent looks first, proposes a plan and the sites it means to work on, and once the person
                approves it works those sites without asking at every step. The always-ask list still asks.
              </span>
            </span>
          </label>
          <label className="extension-admin__field extension-admin__field--inline">
            <span className="settings-row__title">
              Default mode
              <span className="settings-row__hint">What a run starts in; each person may choose another that is on.</span>
            </span>
            <select
              className="settings-row__control"
              aria-label="Default mode"
              value={form.agent_default_mode}
              disabled={locked}
              onChange={(e) => patch({ agent_default_mode: e.target.value as AgentMode })}
            >
              <option value="ask">Ask</option>
              <option value="plan" disabled={!form.plan_mode}>
                Plan
              </option>
              <option value="auto" disabled={!form.agent_auto_mode}>
                Auto
              </option>
            </select>
          </label>

          <h3 className="settings-subsection-title">Limits per run</h3>
          <div className="extension-admin__limits">
            <label className="extension-admin__field extension-admin__field--inline">
              <span className="settings-row__title">
                Most minutes per task
                <span className="settings-row__hint">A run past it ends at its next step.</span>
              </span>
              <input
                type="number"
                className="settings-row__control"
                min={NUMBERS.agent_max_minutes.min}
                max={NUMBERS.agent_max_minutes.max}
                step={1}
                value={form.agent_max_minutes}
                disabled={locked}
                onChange={(e) => patch({ agent_max_minutes: e.target.value })}
              />
            </label>
            <label className="extension-admin__field extension-admin__field--inline">
              <span className="settings-row__title">
                Most tabs per task
                <span className="settings-row__hint">Tabs the agent may open itself.</span>
              </span>
              <input
                type="number"
                className="settings-row__control"
                min={NUMBERS.agent_max_tabs.min}
                max={NUMBERS.agent_max_tabs.max}
                step={1}
                value={form.agent_max_tabs}
                disabled={locked}
                onChange={(e) => patch({ agent_max_tabs: e.target.value })}
              />
            </label>
            <label className="extension-admin__field extension-admin__field--inline">
              <span className="settings-row__title">
                Runs per person per day
                <span className="settings-row__hint">Empty: no limit. Counted from the runs in Admin Logs, by UTC day.</span>
              </span>
              <input
                type="number"
                className="settings-row__control"
                min={NUMBERS.agent_runs_per_day.min}
                max={NUMBERS.agent_runs_per_day.max}
                step={1}
                placeholder="No limit"
                value={form.agent_runs_per_day}
                disabled={locked}
                onChange={(e) => patch({ agent_runs_per_day: e.target.value })}
              />
            </label>
            <label className="extension-admin__field extension-admin__field--inline">
              <span className="settings-row__title">
                A screenshot&apos;s longest side
                <span className="settings-row__hint">Pixels. Smaller is cheaper; larger reads small text better.</span>
              </span>
              <input
                type="number"
                className="settings-row__control"
                min={NUMBERS.screenshot_max_side.min}
                max={NUMBERS.screenshot_max_side.max}
                step={1}
                value={form.screenshot_max_side}
                disabled={locked}
                onChange={(e) => patch({ screenshot_max_side: e.target.value })}
              />
            </label>
            <label className="extension-admin__field extension-admin__field--inline">
              <span className="settings-row__title">
                Screenshots kept
                <span className="settings-row__hint">How many of the latest stay in the run&apos;s conversation.</span>
              </span>
              <input
                type="number"
                className="settings-row__control"
                min={NUMBERS.screenshots_kept.min}
                max={NUMBERS.screenshots_kept.max}
                step={1}
                value={form.screenshots_kept}
                disabled={locked}
                onChange={(e) => patch({ screenshots_kept: e.target.value })}
              />
            </label>
          </div>
          <label className="extension-admin__choice">
            <input
              type="checkbox"
              checked={form.screenshot_after_action}
              disabled={locked}
              onChange={(e) => patch({ screenshot_after_action: e.target.checked })}
            />
            <span>
              <strong>A screenshot after every change</strong>
              <span className="muted-text">
                Each step that clicked, typed, pressed a key, dragged or scrolled ends with a fresh screenshot, so the model
                sees what its action did. Turn off to send fewer images.
              </span>
            </span>
          </label>
          <p className="settings-row__hint">
            The cursor, the coloured border and Chrome&apos;s debugging bar while the agent works, the toolbar badge,
            and the pause when a person takes over the page are always on: nothing here can hide a run.
          </p>

          <h3 className="settings-subsection-title">Full control: data location</h3>
          <label className="extension-admin__field">
            <span className="settings-row__title">Internal sites</span>
            <textarea
              className="input-block mono"
              rows={3}
              value={form.internal_sites}
              disabled={locked}
              placeholder={"One per line: *.corp.example, intranet"}
              onChange={(e) => patch({ internal_sites: e.target.value })}
            />
            <span className="settings-row__hint">
              The organisation's own sites. Their pages and screenshots go only to the models chosen below.
            </span>
          </label>
          <div className="extension-admin__field">
            <span className="settings-row__title">Models that may see internal sites</span>
            <ModelChecklist
              label="Models that may see internal sites"
              models={models}
              selected={form.internal_models}
              disabled={locked}
              onChange={(next) => patch({ internal_models: next })}
            />
            <span className="settings-row__hint">
              None selected: any model the person may use. A model not here cannot read an internal site or see its
              screenshots.
            </span>
          </div>
          <div className="extension-admin__field">
            <span className="settings-row__title">Connections inside the organisation</span>
            <ConnectionChecklist
              connections={connections}
              selected={form.internal_connections}
              disabled={locked}
              onChange={(next) => patch({ internal_connections: next })}
            />
            <span className="settings-row__hint">
              Every model on a ticked connection may see internal sites, like a model chosen above. A connection whose
              address is private (10.x, 172.16-31.x, 192.168.x, localhost, a single-word intranet name) is marked as
              one that looks internal; tick it only if its models run inside the organisation.
            </span>
          </div>
          <label className="extension-admin__choice">
            <input
              type="checkbox"
              checked={form.external_screenshots}
              disabled={locked}
              onChange={(e) => patch({ external_screenshots: e.target.checked })}
            />
            <span>
              <strong>Screenshots of other sites may go to models outside the organisation</strong>
              <span className="muted-text">
                Turned off, every screenshot goes only to models inside the organisation (the connections ticked and
                the models chosen above). Without any of those, nothing is inside and this changes nothing.
              </span>
            </span>
          </label>
          <div className="extension-admin__field">
            <span className="settings-row__title">Models that may see screenshots</span>
            <ModelChecklist
              label="Models that may see screenshots"
              models={models}
              selected={form.screenshot_models}
              disabled={locked}
              onChange={(next) => patch({ screenshot_models: next })}
            />
            <span className="settings-row__hint">
              None selected: any model. A model not here works from the page's text and references, without screenshots.
            </span>
          </div>
          <div className="extension-admin__field">
            <span className="settings-row__title">Can it point? The browser_control probe</span>
            <span className="settings-row__hint">
              Shows a model three made-up pages with three buttons each and asks it to click one by its label, with the
              agent&apos;s own tool. A model that cannot read the screenshot, or answers in words instead of a click,
              will waste clicks and approvals under full control. Three small vision calls, billed to you.
            </span>
            <ProbeTable models={models} probes={probes} probing={probing} disabled={readOnly} onProbe={(ref) => void probe(ref)} />
          </div>

          <h3 className="settings-subsection-title">Full control: always ask before</h3>
          <p className="settings-row__hint">
            Each is on by default. Turn one off to let the agent do it as an ordinary action (in Auto mode, still
            checked by the reviewer). Payments, trades, creating accounts, deleting for good, identity and card fields,
            giving a program access to an account and typing personal details always ask or are refused, and cannot be
            turned off here.
          </p>
          <div className="extension-admin__approvals">
            {APPROVALS.map((approval) => (
              <label key={approval.key} className="extension-admin__choice">
                <input
                  type="checkbox"
                  checked={!form.relaxed_approvals.includes(approval.key)}
                  disabled={locked}
                  onChange={(e) => setAsks(approval.key, e.target.checked)}
                />
                <span>
                  <strong>{approval.label}</strong>
                  <span className="muted-text">{approval.hint}</span>
                </span>
              </label>
            ))}
          </div>

          <h3 className="settings-subsection-title">Privacy and audit</h3>
          <label className="extension-admin__choice">
            <input type="checkbox" checked={form.save_runs} disabled={locked} onChange={(e) => patch({ save_runs: e.target.checked })} />
            <span>
              <strong>Save finished runs to the person&apos;s chat history</strong>
              <span className="muted-text">The task, the answer and the list of steps - never screenshots or page text.</span>
            </span>
          </label>
          <label className="extension-admin__choice">
            <input type="checkbox" checked={form.private_runs} disabled={locked} onChange={(e) => patch({ private_runs: e.target.checked })} />
            <span>
              <strong>People may mark a run private</strong>
              <span className="muted-text">A private run is not saved to their history. Its steps still go to Admin Logs.</span>
            </span>
          </label>
          <p className="settings-row__hint">
            Never stored, whatever is set here: screenshots, page text, what the agent typed, and code. Admin Logs
            holds the site (the host, never a page&apos;s full address), the action and how it ended; how long the
            rows stay is the <Link to="/admin/retention-policy">retention policy</Link>.
          </p>

          {readOnly ? null : (
            <div className="dialog-actions">
              <button type="submit" className="btn" disabled={saving}>
                {saving ? "Saving…" : "Save extension settings"}
              </button>
            </div>
          )}
        </form>
      )}

      {distribution ? (
        <div className="extension-admin__it">
          <h3 className="settings-subsection-title">Install for everyone (Group Policy)</h3>
          {distribution.key_status === "unreadable" ? (
            <p className="alert alert-error" role="alert">
              The extension's signing key cannot be read: {distribution.key_message ?? "unknown error"}. Browsers
              cannot be sent this extension until it is fixed.
            </p>
          ) : null}
          {distribution.available && distribution.extension_id && distribution.update_url && distribution.gpo_value ? (
            <>
              <p className="settings-section-desc">
                Add the policy value to ExtensionInstallForcelist (Chrome: Google Chrome → Extensions; Edge:
                Microsoft Edge → Extensions). Browsers then install the extension from this server and keep it up
                to date. Current version: {distribution.version ?? "—"}.
              </p>
              <CopyValue label="Extension ID" value={distribution.extension_id} />
              <CopyValue label="Update URL" value={distribution.update_url} />
              <CopyValue label="Policy value" value={distribution.gpo_value} />
            </>
          ) : (
            <p className="muted-text">{distribution.reason ?? "The extension is not available for download yet."}</p>
          )}
        </div>
      ) : null}
    </section>
  );
}
