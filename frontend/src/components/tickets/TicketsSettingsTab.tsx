import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";

import DeleteTicketsDialog, { deleteAllTickets, type DeleteTarget } from "./DeleteTicketsDialog";
import { useConfirm } from "../../context/ConfirmContext";
import {
  AUTO_REPLY_PLACEHOLDERS,
  IMAGE_TYPE_CEILING,
  PRIORITIES,
  PRIORITY_LABELS,
  TICKETS_BASE,
  ticketsRequest,
  type Priority,
  type StaffMeta,
  type TicketSettings,
} from "../../lib/tickets";
import { SETTINGS_BOUNDS, isValidEmail, normalizeCategory, validateSettings } from "../../lib/ticketsAdmin";

type Props = {
  settings: TicketSettings | null;
  meta: StaffMeta | null;
  /** Super Admin: everyone else with the menu reads the same page. */
  canEdit: boolean;
  /** Why the settings could not be read; with "Try again". */
  loadError?: string;
  onRetry?: () => void;
  onSaved: (settings: TicketSettings) => void;
};

const TYPE_LABELS: Record<string, string> = { png: "PNG", jpg: "JPG / JPEG", webp: "WEBP", gif: "GIF" };

const ROLES: [string, boolean][] = [
  ["See, reply, internal notes", true],
  ["Status, priority, category, close", true],
  ["Assign to me, assign to someone else", true],
  ["Overview", true],
  ["Settings, automatic reply", false],
  ["Delete one ticket, delete by filter, delete all", false],
];

function Switch({
  on,
  label,
  disabled,
  onChange,
}: {
  on: boolean;
  label: string;
  disabled: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`tickets-switch${on ? " is-on" : ""}`}
      disabled={disabled}
      onClick={() => onChange(!on)}
    >
      <span className="tickets-switch__knob" aria-hidden />
    </button>
  );
}

function FieldError({ text }: { text?: string }) {
  return text ? (
    <p className="tickets-field-error" role="alert">
      {text}
    </p>
  ) : null;
}

/** "Delete closed tickets after (days)" with its number box and its error. */
function NumberField({
  label,
  value,
  error,
  bounds,
  disabled,
  onChange,
}: {
  label: ReactNode;
  value: number;
  error?: string;
  bounds: [number, number];
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div>
      <label className="tickets-field">
        <span>{label}</span>
        <input
          type="number"
          className={`input-block${error ? " is-invalid" : ""}`}
          min={bounds[0]}
          max={bounds[1]}
          step={1}
          value={Number.isNaN(value) ? "" : value}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          onChange={(e) => onChange(e.target.value === "" ? Number.NaN : Number(e.target.value))}
        />
      </label>
      <FieldError text={error} />
    </div>
  );
}

/**
 * Tickets › Settings: every Super Admin setting, read-only for everyone else
 * with the menu. The server checks the same bounds again on Save.
 */
export default function TicketsSettingsTab({ settings, meta, canEdit, loadError, onRetry, onSaved }: Props) {
  const confirmer = useConfirm();
  const [form, setForm] = useState<TicketSettings | null>(settings);
  const [base, setBase] = useState<TicketSettings | null>(settings);
  const [emailDraft, setEmailDraft] = useState("");
  const [emailError, setEmailError] = useState("");
  const [categoryDraft, setCategoryDraft] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ index: number; value: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const replyRef = useRef<HTMLTextAreaElement>(null);

  const errors = useMemo(() => (form ? validateSettings(form) : {}), [form]);
  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(base), [form, base]);

  if (!form) {
    return loadError ? (
      <div className="alert alert-error tickets-settings-error" role="alert">
        <span>The settings could not be read: {loadError}</span>{" "}
        {onRetry ? (
          <button type="button" className="btn btn-ghost btn-sm btn-readonly-ok" onClick={onRetry}>
            Try again
          </button>
        ) : null}
      </div>
    ) : (
      <p className="muted-text">Loading the settings…</p>
    );
  }
  const locked = !canEdit;
  const set = (patch: Partial<TicketSettings>) => {
    setForm({ ...form, ...patch });
    setNotice("");
  };

  function addEmail() {
    if (!form) return;
    const value = emailDraft.trim().replace(/,$/, "");
    if (!value) return;
    if (!isValidEmail(value)) {
      setEmailError(`Not a valid address: ${value}`);
      return;
    }
    if (form.notify_emails.some((e) => e.toLowerCase() === value.toLowerCase())) {
      setEmailDraft("");
      setEmailError("");
      return;
    }
    if (form.notify_emails.length >= 20) {
      setEmailError("At most 20 addresses.");
      return;
    }
    set({ notify_emails: [...form.notify_emails, value] });
    setEmailDraft("");
    setEmailError("");
  }

  function onEmailKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addEmail();
    }
  }

  function addCategory() {
    if (!form || categoryDraft == null) return;
    const name = normalizeCategory(categoryDraft);
    if (name) set({ categories: [...form.categories, name] });
    setCategoryDraft(null);
  }

  function renameCategory() {
    if (!form || !renaming) return;
    const name = normalizeCategory(renaming.value);
    if (name) set({ categories: form.categories.map((c, i) => (i === renaming.index ? name : c)) });
    setRenaming(null);
  }

  function insertPlaceholder(token: string) {
    if (!form) return;
    const el = replyRef.current;
    const text = form.auto_reply_text;
    const start = el?.selectionStart ?? text.length;
    const end = el?.selectionEnd ?? text.length;
    set({ auto_reply_text: `${text.slice(0, start)}${token}${text.slice(end)}` });
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + token.length, start + token.length);
    });
  }

  async function save() {
    if (!form || Object.keys(errors).length) return;
    setSaving(true);
    setError("");
    try {
      const saved = await ticketsRequest<TicketSettings>(`${TICKETS_BASE}/settings`, {
        method: "PUT",
        body: JSON.stringify({ ...form, categories: form.categories.map(normalizeCategory) }),
      });
      setForm(saved);
      setBase(saved);
      setNotice("Settings saved.");
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function deleteAll() {
    try {
      const deleted = await deleteAllTickets(confirmer);
      if (deleted != null) setNotice(`${deleted} ${deleted === 1 ? "ticket was" : "tickets were"} deleted.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const errorCount = Object.keys(errors).length;
  return (
    <div className="tickets-settings-wrap">
      {locked ? (
        <p className="alert alert-info tickets-settings-readonly">
          Only a Super Admin can change these settings. You can read them here.
        </p>
      ) : null}
      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="tickets-settings">
        <section className="tickets-card">
          <h3>
            Tickets
            <Switch on={form.enabled} label="Tickets on" disabled={locked} onChange={(on) => set({ enabled: on })} />
          </h3>
          <p className="muted-text">
            When off, Support disappears from every account and nothing new can be sent. Existing tickets stay.
          </p>
          <NumberField
            label="Tickets a person may open per hour"
            value={form.per_hour}
            bounds={SETTINGS_BOUNDS.per_hour}
            error={errors.per_hour}
            disabled={locked}
            onChange={(v) => set({ per_hour: v })}
          />
          <NumberField
            label="Open tickets a person may have at once"
            value={form.max_open}
            bounds={SETTINGS_BOUNDS.max_open}
            error={errors.max_open}
            disabled={locked}
            onChange={(v) => set({ max_open: v })}
          />
          <NumberField
            label="Reopen a resolved ticket within (days)"
            value={form.reopen_days}
            bounds={SETTINGS_BOUNDS.reopen_days}
            error={errors.reopen_days}
            disabled={locked}
            onChange={(v) => set({ reopen_days: v })}
          />
          <NumberField
            label="Close tickets waiting for the user after (days)"
            value={form.auto_close_days}
            bounds={SETTINGS_BOUNDS.auto_close_days}
            error={errors.auto_close_days}
            disabled={locked}
            onChange={(v) => set({ auto_close_days: v })}
          />
          <NumberField
            label="Delete closed tickets and their images after (days)"
            value={form.retention_days}
            bounds={SETTINGS_BOUNDS.retention_days}
            error={errors.retention_days}
            disabled={locked}
            onChange={(v) => set({ retention_days: v })}
          />
          <p className="tickets-hint">
            Only closed tickets are ever deleted by time; 0 keeps them. Open tickets are never deleted on their own.
          </p>
        </section>

        <section className="tickets-card">
          <h3>Email notifications</h3>
          <p className="muted-text">
            Sent through the SMTP server set in <Link to="/admin/smtp">SMTP Server</Link>.
          </p>
          <div>
            <div className="tickets-card__label">Send new tickets to</div>
            <div className="tickets-chips">
              {form.notify_emails.map((email) => (
                <span key={email} className="tickets-chip" dir="ltr">
                  {email}
                  {locked ? null : (
                    <button
                      type="button"
                      className="tickets-chip__x"
                      aria-label={`Remove ${email}`}
                      onClick={() => set({ notify_emails: form.notify_emails.filter((e) => e !== email) })}
                    >
                      ✕
                    </button>
                  )}
                </span>
              ))}
              {locked ? (
                form.notify_emails.length ? null : <span className="muted-text">Nobody</span>
              ) : (
                <input
                  className="input-block tickets-chip-input"
                  placeholder="Add an address"
                  aria-label="Add an address"
                  dir="ltr"
                  value={emailDraft}
                  onChange={(e) => {
                    setEmailDraft(e.target.value);
                    setEmailError("");
                  }}
                  onKeyDown={onEmailKey}
                  onBlur={addEmail}
                />
              )}
            </div>
            <FieldError text={emailError || errors.notify_emails} />
          </div>
          <label className="tickets-check">
            <input
              type="checkbox"
              checked={form.notify_on_user_reply}
              disabled={locked}
              onChange={(e) => set({ notify_on_user_reply: e.target.checked })}
            />
            <span>Also email them when a user replies</span>
          </label>
          <label className="tickets-field">
            <span>Only for priority at least</span>
            <select
              className="input-block"
              value={form.notify_min_priority}
              disabled={locked}
              onChange={(e) => set({ notify_min_priority: e.target.value as Priority })}
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {PRIORITY_LABELS[p]}
                </option>
              ))}
            </select>
          </label>
          <label className="tickets-check">
            <input
              type="checkbox"
              checked={form.email_assignee}
              disabled={locked}
              onChange={(e) => set({ email_assignee: e.target.checked })}
            />
            <span>
              Email a person when someone else assigns a ticket to them{" "}
              <span className="muted-text">(never for “Assign to me”)</span>
            </span>
          </label>
          <label className="tickets-check">
            <input
              type="checkbox"
              checked={form.email_user}
              disabled={locked}
              onChange={(e) => set({ email_user: e.target.checked })}
            />
            <span>
              Email the user when support replies or changes the status of their ticket{" "}
              <span className="muted-text">(off: they see the number on Support in the app)</span>
            </span>
          </label>
          <p className="tickets-hint">
            Emails carry the number, title, priority, the person and a link; never the images. Internal notes are never
            emailed.
          </p>
        </section>

        <section className="tickets-card">
          <h3>Images</h3>
          <div>
            <div className="tickets-card__label">Accepted types</div>
            <div className="tickets-chips" role="group" aria-label="Accepted types">
              {IMAGE_TYPE_CEILING.map((type) => {
                const on = form.image_types.includes(type);
                return (
                  <button
                    key={type}
                    type="button"
                    className={`tickets-chip tickets-chip--toggle${on ? " is-on" : ""}`}
                    aria-pressed={on}
                    disabled={locked}
                    onClick={() =>
                      set({ image_types: on ? form.image_types.filter((t) => t !== type) : [...form.image_types, type] })
                    }
                  >
                    {TYPE_LABELS[type]} {on ? "✓" : ""}
                  </button>
                );
              })}
              <span className="tickets-chip tickets-chip--off" title="Never allowed">
                SVG
              </span>
              <span className="tickets-chip tickets-chip--off" title="Never allowed">
                HEIC
              </span>
            </div>
            <p className="tickets-hint">
              SVG, HTML, executables and every non-image type are always refused; they cannot be added here.
            </p>
            <FieldError text={errors.image_types} />
          </div>
          <NumberField
            label="Largest image (MB)"
            value={form.max_image_mb}
            bounds={SETTINGS_BOUNDS.max_image_mb}
            error={errors.max_image_mb}
            disabled={locked}
            onChange={(v) => set({ max_image_mb: v })}
          />
          <NumberField
            label="Images per message"
            value={form.max_images}
            bounds={SETTINGS_BOUNDS.max_images}
            error={errors.max_images}
            disabled={locked}
            onChange={(v) => set({ max_images: v })}
          />
          <NumberField
            label="Largest side (px)"
            value={form.max_side_px}
            bounds={SETTINGS_BOUNDS.max_side_px}
            error={errors.max_side_px}
            disabled={locked}
            onChange={(v) => set({ max_side_px: v })}
          />
          <p className="tickets-hint">
            Every image is checked for what it really is, scanned for malware and saved again as a clean copy (no location
            or camera data).
          </p>
        </section>

        <section className="tickets-card">
          <h3>
            Automatic first reply
            <Switch
              on={form.auto_reply_enabled}
              label="Automatic first reply on"
              disabled={locked}
              onChange={(on) => set({ auto_reply_enabled: on })}
            />
          </h3>
          <p className="muted-text">
            Added to every new ticket at once, as “Support team · automatic reply”. It does not change the status and
            does not count as a first reply in reports.
          </p>
          <textarea
            ref={replyRef}
            className={`input-block tickets-reply-text${errors.auto_reply_text ? " is-invalid" : ""}`}
            rows={4}
            dir="auto"
            aria-label="Automatic reply text"
            value={form.auto_reply_text}
            disabled={locked}
            maxLength={2000}
            onChange={(e) => set({ auto_reply_text: e.target.value })}
          />
          <FieldError text={errors.auto_reply_text} />
          {locked ? null : (
            <div className="tickets-chips">
              <span className="muted-text tickets-chips__lead">Insert:</span>
              {AUTO_REPLY_PLACEHOLDERS.map((token) => (
                <button key={token} type="button" className="tickets-chip" onClick={() => insertPlaceholder(token)}>
                  {token}
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="tickets-card">
          <h3>Categories</h3>
          <div className="tickets-chips">
            {form.categories.map((category, index) =>
              renaming?.index === index ? (
                <input
                  // eslint-disable-next-line jsx-a11y/no-autofocus -- the chip the administrator just chose to rename
                  autoFocus
                  key={`rename-${index}`}
                  className="input-block tickets-chip-input"
                  aria-label={`Rename ${category}`}
                  value={renaming.value}
                  maxLength={40}
                  onChange={(e) => setRenaming({ index, value: e.target.value })}
                  onBlur={renameCategory}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      renameCategory();
                    }
                    if (e.key === "Escape") setRenaming(null);
                  }}
                />
              ) : (
                <span key={`${category}-${index}`} className="tickets-chip" dir="auto">
                  {locked ? (
                    category
                  ) : (
                    <button
                      type="button"
                      className="tickets-chip__name"
                      title="Rename"
                      onClick={() => setRenaming({ index, value: category })}
                    >
                      {category}
                    </button>
                  )}
                  {locked || form.categories.length <= 1 ? null : (
                    <button
                      type="button"
                      className="tickets-chip__x"
                      aria-label={`Remove ${category}`}
                      onClick={() => set({ categories: form.categories.filter((_, i) => i !== index) })}
                    >
                      ✕
                    </button>
                  )}
                </span>
              ),
            )}
            {locked ? null : categoryDraft == null ? (
              form.categories.length < 20 ? (
                <button type="button" className="tickets-chip" onClick={() => setCategoryDraft("")}>
                  + Add
                </button>
              ) : null
            ) : (
              <input
                // eslint-disable-next-line jsx-a11y/no-autofocus -- the field the administrator just opened
                autoFocus
                className="input-block tickets-chip-input"
                placeholder="New category"
                aria-label="New category"
                value={categoryDraft}
                maxLength={40}
                onChange={(e) => setCategoryDraft(e.target.value)}
                onBlur={addCategory}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCategory();
                  }
                  if (e.key === "Escape") setCategoryDraft(null);
                }}
              />
            )}
          </div>
          <FieldError text={errors.categories} />
          <p className="tickets-hint">
            Renaming a category does not change tickets that already have it. Click a name to rename it.
          </p>
          <h3 className="tickets-card__sub">Who does what</h3>
          <table className="tickets-table tickets-roles">
            <thead>
              <tr>
                <th>
                  <span className="sr-only">Action</span>
                </th>
                <th>Support</th>
                <th>Super Admin</th>
              </tr>
            </thead>
            <tbody>
              {ROLES.map(([label, support]) => (
                <tr key={label}>
                  <td>{label}</td>
                  <td className={support ? undefined : "muted-text"}>{support ? "✓" : "—"}</td>
                  <td>✓</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="tickets-hint">Read Only Super Admin sees everything and changes nothing.</p>
        </section>

        {canEdit ? (
          <section className="tickets-card tickets-card--danger">
            <h3>Delete tickets</h3>
            <p className="muted-text">
              Super Admin only. Each step shows how many tickets and images go, asks you to type a confirmation the server
              checks again, and is recorded in Admin Logs.
            </p>
            <div className="tickets-actions tickets-actions--start">
              <button
                type="button"
                className="btn btn-ghost tickets-danger-ghost"
                onClick={() => setDeleteTarget({ kind: "filter", filter: { statuses: ["resolved", "closed"] } })}
              >
                Delete by filter…
              </button>
              <button type="button" className="btn btn-danger" onClick={() => void deleteAll()}>
                Delete all tickets…
              </button>
            </div>
          </section>
        ) : null}
      </div>

      {canEdit ? (
        <div className="tickets-savebar">
          <span className={`tickets-savebar__state${notice ? " is-saved" : ""}`} aria-live="polite">
            {notice
              ? notice
              : errorCount
                ? `${errorCount} ${errorCount === 1 ? "field needs" : "fields need"} a fix before saving.`
                : dirty
                  ? "Unsaved changes."
                  : "No changes."}
          </span>
          <button type="button" className="btn btn-ghost" disabled={!dirty || saving} onClick={() => setForm(base)}>
            Discard
          </button>
          <button type="button" className="btn" disabled={!dirty || saving || errorCount > 0} onClick={() => void save()}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      ) : null}

      <DeleteTicketsDialog
        target={deleteTarget}
        options={{
          categories: meta?.categories ?? form.categories,
          departments: meta?.departments ?? [],
          assignees: meta?.assignees ?? [],
        }}
        onClose={() => setDeleteTarget(null)}
        onDeleted={(deleted) => {
          setDeleteTarget(null);
          setNotice(`${deleted} ${deleted === 1 ? "ticket was" : "tickets were"} deleted.`);
        }}
      />
    </div>
  );
}
