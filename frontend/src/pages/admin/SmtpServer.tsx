import { FormEvent, useEffect, useRef, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api, formatApiError } from "../../api";
import { useAdminWriteLock } from "../../lib/adminWriteLock";
import {
  PASSWORD_AGAIN,
  PASSWORD_MASK,
  SMTP_SECURITY_OPTIONS,
  STANDARD_PORTS,
  describeTestResult,
  passwordReuseProblem,
  portAfterSecurityChange,
  portHint,
  validateSmtpForm,
  type SmtpSecurity,
  type SmtpTestResult,
} from "../../lib/smtpSettings";

/** The settings as the server returns them. */
type SavedSmtp = {
  host: string;
  port: number;
  username: string | null;
  /** The mask when a password is saved, else null. Never the password. */
  password: string | null;
  from_address: string;
  security: SmtpSecurity;
  verify_certificate: boolean;
};

type Form = {
  host: string;
  port: string;
  security: SmtpSecurity;
  username: string;
  /** Only what is typed here; empty keeps the saved password. */
  password: string;
  from_address: string;
  verify_certificate: boolean;
};

type Notice = { kind: "ok" | "error"; text: string };

const EMPTY: Form = {
  host: "",
  port: String(STANDARD_PORTS.starttls),
  security: "starttls",
  username: "",
  password: "",
  from_address: "",
  verify_certificate: true,
};

/** What "Send test email to me" answers. */
type TestEmailResult = { ok: boolean; to?: string; error?: string };

function formFrom(saved: SavedSmtp): Form {
  return {
    host: saved.host ?? "",
    port: String(saved.port ?? STANDARD_PORTS[saved.security ?? "starttls"]),
    security: saved.security ?? "starttls",
    username: saved.username ?? "",
    password: "",
    from_address: saved.from_address ?? "",
    verify_certificate: saved.verify_certificate !== false,
  };
}

function sameForm(a: Form, b: Form): boolean {
  return (Object.keys(a) as (keyof Form)[]).every((key) => a[key] === b[key]);
}

export default function SmtpServer() {
  const { readOnly, writeLockProps } = useAdminWriteLock();
  const [saved, setSaved] = useState<SavedSmtp | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [testResult, setTestResult] = useState<SmtpTestResult | null>(null);
  const [mailing, setMailing] = useState(false);
  const [mailNotice, setMailNotice] = useState<Notice | null>(null);
  // Counts edits, so an answer to a request made before the latest one can tell it is stale.
  const revision = useRef(0);

  useEffect(() => {
    let live = true;
    api<SavedSmtp | null>("/api/admin/smtp")
      .then((row) => {
        if (!live || !row) return;
        setSaved(row);
        setForm(formFrom(row));
      })
      .catch((err) => live && setLoadError(formatApiError(err)));
    return () => {
      live = false;
    };
  }, []);

  /** Results describe the values they were made with; an edit makes them stale. */
  function clearResults() {
    setNotice(null);
    setTestResult(null);
    setMailNotice(null);
  }

  function update(patch: Partial<Form>) {
    revision.current += 1;
    setForm((f) => ({ ...f, ...patch }));
    clearResults();
  }

  function changeSecurity(next: SmtpSecurity) {
    revision.current += 1;
    setForm((f) => ({ ...f, security: next, port: portAfterSecurityChange(f.port, next) }));
    clearResults();
  }

  const passwordSaved = saved?.password === PASSWORD_MASK;
  // The server reads the mask as "keep the saved one", so typing it is typing nothing.
  const typedPassword = form.password !== PASSWORD_MASK ? form.password : "";
  // A saved password stays with its server and username and is never sent over
  // a less secure connection; the server refuses a Save that would, so say so first.
  const passwordProblem =
    saved && passwordSaved && form.username.trim() && !typedPassword ? passwordReuseProblem(saved, form) : null;
  const port = Number(form.port);
  const hint = Number.isInteger(port) ? portHint(form.security, port) : null;
  // The test email goes out the way every other email does: with the saved settings, not the form.
  let mailBlocked: string | null = null;
  if (!saved) mailBlocked = "Save the settings first: the test email is sent with the saved settings.";
  else if (!sameForm(form, formFrom(saved))) {
    mailBlocked = "Save your changes first: the test email is sent with the saved settings.";
  }

  function body() {
    return {
      host: form.host.trim(),
      port: Number(form.port),
      security: form.security,
      verify_certificate: form.verify_certificate,
      username: form.username.trim() || null,
      password: form.password || null,
      from_address: form.from_address.trim(),
    };
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const invalid = validateSmtpForm(form) ?? (passwordProblem ? PASSWORD_AGAIN[passwordProblem] : null);
    if (invalid) {
      setNotice({ kind: "error", text: invalid });
      return;
    }
    const started = revision.current;
    setSaving(true);
    setNotice(null);
    try {
      await api("/api/admin/smtp", { method: "PUT", body: JSON.stringify(body()) });
      const row = await api<SavedSmtp | null>("/api/admin/smtp");
      const editedMeanwhile = revision.current !== started;
      if (row) {
        setSaved(row);
        // What was typed while saving stays on the form, as an unsaved change.
        if (!editedMeanwhile) setForm(formFrom(row));
      }
      setNotice({
        kind: "ok",
        text: editedMeanwhile ? "SMTP settings saved, without the changes made while saving." : "SMTP settings saved.",
      });
    } catch (err) {
      setNotice({ kind: "error", text: formatApiError(err) });
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    const invalid = validateSmtpForm(form);
    if (invalid) {
      setTestResult({ ok: false, error: invalid });
      return;
    }
    const started = revision.current;
    setTesting(true);
    setTestResult(null);
    // A result for values that have been edited since would read as a pass (or a failure) for the new ones.
    const show = (result: SmtpTestResult) => revision.current === started && setTestResult(result);
    try {
      show(await api<SmtpTestResult>("/api/admin/smtp/test", { method: "POST", body: JSON.stringify(body()) }));
    } catch (err) {
      show({ ok: false, error: formatApiError(err) });
    } finally {
      setTesting(false);
    }
  }

  async function sendTestEmail() {
    setMailing(true);
    setMailNotice(null);
    try {
      const result = await api<TestEmailResult>("/api/admin/smtp/test-email", { method: "POST" });
      setMailNotice(
        result.ok
          ? {
              kind: "ok",
              text: `The mail server accepted a test email for ${result.to}. If it does not arrive, look in the spam folder.`,
            }
          : { kind: "error", text: result.error || "The test email could not be sent." },
      );
    } catch (err) {
      setMailNotice({ kind: "error", text: formatApiError(err) });
    } finally {
      setMailing(false);
    }
  }

  return (
    <AdminPage title="SMTP Server">
      <p className="muted-text">
        Outbound mail for API keys sent to their owners, sign-in and certificate alerts, and project invitations.
      </p>
      {loadError ? (
        <p className="alert alert-error" role="alert">
          {loadError}
        </p>
      ) : null}

      <form className="card smtp-form" onSubmit={save} aria-label="SMTP settings" noValidate>
        <div className="smtp-field">
          <label htmlFor="smtp-host">Server</label>
          <input
            id="smtp-host"
            value={form.host}
            onChange={(e) => update({ host: e.target.value })}
            placeholder="mail.example.com"
            autoComplete="off"
            spellCheck={false}
            required
          />
        </div>

        <div className="smtp-field-row">
          <div className="smtp-field">
            <label htmlFor="smtp-security">Connection security</label>
            <select
              id="smtp-security"
              value={form.security}
              onChange={(e) => changeSecurity(e.target.value as SmtpSecurity)}
            >
              {SMTP_SECURITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="smtp-field">
            <label htmlFor="smtp-port">Port</label>
            <input
              id="smtp-port"
              type="number"
              min={1}
              max={65535}
              value={form.port}
              onChange={(e) => update({ port: e.target.value })}
            />
          </div>
        </div>
        {hint ? (
          <p className="smtp-hint smtp-hint--warn" role="note">
            {hint}
          </p>
        ) : null}
        {form.security === "none" ? (
          <p className="alert alert-warning smtp-warning">
            <strong>No encryption.</strong> The password and every message cross the network in plain text. Use this
            only for a relay on a network you trust.
          </p>
        ) : null}

        <div className="smtp-field-row">
          <div className="smtp-field">
            <label htmlFor="smtp-username">Username</label>
            <input
              id="smtp-username"
              value={form.username}
              onChange={(e) => update({ username: e.target.value })}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <div className="smtp-field">
            <label htmlFor="smtp-password">Password</label>
            <input
              id="smtp-password"
              type="password"
              value={form.password}
              onChange={(e) => update({ password: e.target.value })}
              placeholder={passwordSaved ? "Saved — leave blank to keep it" : ""}
              // Not the administrator's own sign-in: stop the browser offering it here.
              autoComplete="new-password"
              aria-describedby="smtp-password-hint"
            />
          </div>
        </div>
        <p id="smtp-password-hint" className={`smtp-hint${passwordProblem ? " smtp-hint--warn" : ""}`}>
          {passwordProblem
            ? PASSWORD_AGAIN[passwordProblem]
            : "Leave the username empty for a relay that needs no login."}
        </p>

        <div className="smtp-field">
          <label htmlFor="smtp-from">From address</label>
          <input
            id="smtp-from"
            // Not type="email": that refuses a name before the address.
            type="text"
            inputMode="email"
            value={form.from_address}
            onChange={(e) => update({ from_address: e.target.value })}
            placeholder="reports@example.com"
            autoComplete="off"
            spellCheck={false}
            aria-describedby="smtp-from-hint"
            required
          />
        </div>
        <p id="smtp-from-hint" className="smtp-hint">
          An address, or a name and an address: Alpharouter &lt;reports@example.com&gt;.
        </p>

        <label className="smtp-check" htmlFor="smtp-self-signed">
          <input
            id="smtp-self-signed"
            type="checkbox"
            checked={!form.verify_certificate}
            onChange={(e) => update({ verify_certificate: !e.target.checked })}
            // The write lock only greys inputs out; a click on this label would still toggle the box.
            disabled={form.security === "none" || readOnly}
          />
          <span>
            Allow a self-signed certificate
            <span className="smtp-hint">
              For a server whose certificate no public authority signed. The connection stays encrypted, but the
              server&apos;s identity is not checked.
            </span>
          </span>
        </label>
        {form.security !== "none" && !form.verify_certificate ? (
          <p className="alert alert-warning smtp-warning">
            <strong>Certificate not checked.</strong> Anyone able to intercept the connection could pose as the mail
            server and collect the password. Use this only on a network you trust.
          </p>
        ) : null}

        {testResult ? (
          <p
            className={`alert ${testResult.ok ? "alert-success" : "alert-error"} smtp-result`}
            role={testResult.ok ? "status" : "alert"}
          >
            {describeTestResult(testResult)}
          </p>
        ) : null}
        {notice ? (
          <p
            className={`alert ${notice.kind === "ok" ? "alert-success" : "alert-error"} smtp-result`}
            role={notice.kind === "ok" ? "status" : "alert"}
          >
            {notice.text}
          </p>
        ) : null}
        {mailNotice ? (
          <p
            className={`alert ${mailNotice.kind === "ok" ? "alert-success" : "alert-error"} smtp-result smtp-mail-result`}
            role={mailNotice.kind === "ok" ? "status" : "alert"}
          >
            {mailNotice.text}
          </p>
        ) : null}

        <div className="dialog-actions">
          <button
            type="submit"
            className="btn"
            disabled={saving || readOnly || !!passwordProblem}
            title={writeLockProps.title ?? (passwordProblem ? "Enter the password again first." : undefined)}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <div className="dialog-actions-end">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => void test()}
              disabled={testing || readOnly}
              title={writeLockProps.title}
            >
              {testing ? "Testing…" : "Test connection"}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => void sendTestEmail()}
              disabled={mailing || readOnly || !!mailBlocked}
              title={writeLockProps.title ?? mailBlocked ?? undefined}
              aria-describedby={mailBlocked && !readOnly ? "smtp-mail-hint" : undefined}
            >
              {mailing ? "Sending…" : "Send test email to me"}
            </button>
          </div>
        </div>
        {mailBlocked && !readOnly ? (
          <p id="smtp-mail-hint" className="smtp-hint smtp-actions-hint">
            {mailBlocked}
          </p>
        ) : null}
      </form>
    </AdminPage>
  );
}
