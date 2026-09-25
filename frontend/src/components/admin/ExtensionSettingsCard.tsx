import { useEffect, useMemo, useState, type FormEvent } from "react";

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

type ExtensionSettings = {
  site_access: SiteAccess;
  allowed_sites: string[];
  blocked_sites: string[];
  page_content_models: string[];
  agent_models: string[];
  agent_max_steps: number;
  agent_auto_mode: boolean;
  agent_review_model: string | null;
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

type Overview = { settings: ExtensionSettings; distribution: Distribution };

type AdminModel = {
  id: number;
  external_id: string;
  display_name?: string | null;
  enabled: boolean;
  provider: string;
  kinds?: string[];
};

/** The form keeps the site lists as the text the administrator types, one pattern per line. */
type Form = Omit<ExtensionSettings, "allowed_sites" | "blocked_sites"> & { allowed_sites: string; blocked_sites: string };

const SETTINGS_PATH = "/api/admin/extension/settings";
const MIN_STEPS = 5;
const MAX_STEPS = 100;

function toForm(settings: ExtensionSettings): Form {
  return { ...settings, allowed_sites: settings.allowed_sites.join("\n"), blocked_sites: settings.blocked_sites.join("\n") };
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
  return Boolean(v.settings && typeof v.settings === "object" && v.distribution && typeof v.distribution === "object");
}

const modelRef = (id: number) => `model::${id}`;

function ModelChecklist({
  label,
  models,
  selected,
  disabled,
  onChange,
}: {
  label: string;
  models: AdminModel[];
  selected: string[];
  disabled: boolean;
  onChange: (next: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const chosen = new Set(selected);
  const q = query.trim().toLowerCase();
  const shown = q
    ? models.filter((m) => `${m.display_name ?? ""} ${m.external_id} ${m.provider}`.toLowerCase().includes(q))
    : models;
  return (
    <div className="api-key-conn-picker">
      {models.length > 8 ? (
        <input
          type="search"
          className="input-block"
          placeholder="Search models…"
          aria-label={`Search ${label.toLowerCase()}`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={disabled}
        />
      ) : null}
      <div className="api-key-conn-picker__list" role="group" aria-label={label}>
        {shown.length === 0 ? (
          <p className="muted-text api-key-form__hint">{models.length ? "No models match this search." : "No enabled text models."}</p>
        ) : (
          shown.map((m) => {
            const ref = modelRef(m.id);
            return (
              <label key={m.id} className="api-key-conn-picker__option">
                <input
                  type="checkbox"
                  checked={chosen.has(ref)}
                  disabled={disabled}
                  onChange={() => onChange(chosen.has(ref) ? selected.filter((x) => x !== ref) : [...selected, ref])}
                />
                <span>
                  {m.display_name || m.external_id}
                  <span className="muted-text"> · {m.provider}</span>
                </span>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}

export default function ExtensionSettingsCard() {
  const readOnly = useReadOnly();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [models, setModels] = useState<AdminModel[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api<Overview>(SETTINGS_PATH), api<AdminModel[]>("/api/admin/models")])
      .then(([loaded, catalog]) => {
        if (cancelled) return;
        if (!isOverview(loaded)) throw new Error("The browser extension settings could not be read.");
        setOverview(loaded);
        setForm(toForm(loaded.settings));
        setModels(Array.isArray(catalog) ? catalog : []);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(formatApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const textModels = useMemo(
    () => models.filter((m) => m.enabled && (!m.kinds?.length || m.kinds.includes("text"))),
    [models],
  );

  function patch(values: Partial<Form>) {
    setForm((current) => (current ? { ...current, ...values } : current));
    setNotice("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form || readOnly) return;
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
          agent_review_model: form.agent_review_model || null,
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
          </div>

          <div className="extension-admin__field">
            <span className="settings-row__title">Models that may receive page content</span>
            <ModelChecklist
              label="Models that may receive page content"
              models={textModels}
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
              models={textModels}
              selected={form.agent_models}
              disabled={locked}
              onChange={(next) => patch({ agent_models: next })}
            />
            <span className="settings-row__hint">None selected: any model the person may use.</span>
          </div>
          <label className="extension-admin__field extension-admin__field--inline">
            <span className="settings-row__title">Most steps per task</span>
            <input
              type="number"
              className="settings-row__control"
              min={MIN_STEPS}
              max={MAX_STEPS}
              value={form.agent_max_steps}
              disabled={locked}
              onChange={(e) => patch({ agent_max_steps: Number(e.target.value || MIN_STEPS) })}
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
          <div className="extension-admin__field">
            <span className="settings-row__title">Review model</span>
            <SearchableModelSelect
              id="extension-review-model"
              ariaLabel="Review model"
              value={form.agent_review_model ?? ""}
              disabled={locked}
              emptyLabel="None"
              placeholder="Search models…"
              options={textModels.map((m) => ({
                value: modelRef(m.id),
                label: `${m.display_name || m.external_id} · ${m.provider}`,
              }))}
              onChange={(next) => patch({ agent_review_model: next || null })}
            />
            <span className="settings-row__hint">Required for Auto mode. Its cost is billed to the person.</span>
          </div>

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
