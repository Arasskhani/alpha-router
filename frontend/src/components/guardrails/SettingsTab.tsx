import { type FormEvent, useEffect, useState } from "react";

import { api, formatApiError } from "../../api";
import { useReadOnly } from "../../context/ReadOnlyContext";
import { GUARDRAILS_BASE, lines, type GuardrailSettings } from "../../lib/guardrails";

/** What Guardrails does when it cannot check a text, gives back, keeps and tells. */
export default function SettingsTab() {
  const readOnly = useReadOnly();
  const [form, setForm] = useState<GuardrailSettings | null>(null);
  const [emails, setEmails] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api<GuardrailSettings>(`${GUARDRAILS_BASE}/settings`)
      .then((s) => {
        setForm(s);
        setEmails(s.alert_emails.join("\n"));
      })
      .catch((err) => setError(formatApiError(err)));
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const saved = await api<GuardrailSettings>(`${GUARDRAILS_BASE}/settings`, {
        method: "PUT",
        body: JSON.stringify({ ...form, alert_emails: lines(emails) }),
      });
      setForm(saved);
      setEmails(saved.alert_emails.join("\n"));
      setNotice("Settings saved.");
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  if (!form) return error ? <p className="alert alert-error">{error}</p> : <p className="muted-text">Loading…</p>;
  return (
    <form className="card guardrails-settings" onSubmit={save}>
      {error ? <p className="alert alert-error">{error}</p> : null}
      {notice ? <p className="alert alert-success">{notice}</p> : null}
      <fieldset className="guardrails-fieldset" disabled={readOnly}>
        <legend>When a text cannot be checked</legend>
        <label className="guardrails-inline">
          <input type="radio" name="fail" checked={form.fail_closed} onChange={() => setForm({ ...form, fail_closed: true })} /> Block
          the request (recommended)
        </label>
        <label className="guardrails-inline">
          <input type="radio" name="fail" checked={!form.fail_closed} onChange={() => setForm({ ...form, fail_closed: false })} />{" "}
          Send it, and record that it was not checked
        </label>
      </fieldset>
      <fieldset className="guardrails-fieldset" disabled={readOnly}>
        <legend>Masked values in replies</legend>
        <label className="guardrails-inline">
          <input
            type="checkbox"
            checked={form.restore_replies}
            onChange={(e) => setForm({ ...form, restore_replies: e.target.checked })}
          />{" "}
          Give masked values back to the person in the reply (the model never sees them)
        </label>
      </fieldset>
      <fieldset className="guardrails-fieldset" disabled={readOnly}>
        <legend>Events</legend>
        <label className="connection-form__label">
          Keep events for (days)
          <input
            type="number"
            min={7}
            max={3650}
            className="input-block guardrails-number"
            value={form.event_retention_days}
            onChange={(e) => setForm({ ...form, event_retention_days: Number(e.target.value) })}
          />
        </label>
        <label className="connection-form__label">
          Email blocked requests to (one address per line)
          <textarea className="input-block" rows={3} dir="ltr" value={emails} onChange={(e) => setEmails(e.target.value)} />
          <span className="muted-text connection-form__hint">At most one email per rule every ten minutes. Uses the SMTP server.</span>
        </label>
      </fieldset>
      <p className="muted-text">
        Who may change Guardrails: Super Admin. Read Only Super Admin sees it. Every change is recorded in Admin Logs.
      </p>
      {readOnly ? null : (
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      )}
    </form>
  );
}
