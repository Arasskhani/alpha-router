import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, authFetch, formatApiError } from "../api";
import { fetchUserPrefsFromServer, saveUserPrefs, type UserTheme } from "../lib/chatStorage";
import { COMMON_TIMEZONES, detectBrowserTimezone } from "../lib/timezones";
import Modal from "./Modal";

type TabId = "general" | "data-control" | "security";

type SecurityStatus = {
  auth_provider: string;
  is_local: boolean;
  totp_enabled: boolean;
  password_change_available: boolean;
  two_factor_available: boolean;
};

type TwoFaSetup = {
  secret: string;
  otpauth_uri: string;
  qr_png_base64: string | null;
};

type ImportResult = {
  imported: number;
  skipped: number;
  format: string;
  message?: string;
};

const TABS: { id: TabId; label: string }[] = [
  { id: "general", label: "General" },
  { id: "data-control", label: "Data Control" },
  { id: "security", label: "Security" },
];

type Props = {
  open: boolean;
  onClose: () => void;
  theme: UserTheme;
  onThemeChange: (theme: UserTheme) => void;
};

export default function SettingsModal({ open, onClose, theme, onThemeChange }: Props) {
  const [tab, setTab] = useState<TabId>("general");

  useEffect(() => {
    if (open) setTab("general");
  }, [open]);

  return (
    <Modal
      open={open}
      title="Settings"
      onClose={onClose}
      panelClassName="modal-panel--settings"
      bodyClassName="modal-body--settings"
    >
      <div className="settings-shell settings-shell--modal">
        <aside className="settings-nav" aria-label="Settings sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`settings-nav-item${tab === item.id ? " active" : ""}`}
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? "page" : undefined}
            >
              {item.label}
            </button>
          ))}
        </aside>

        <section className="settings-panel" aria-live="polite">
          {tab === "general" && <GeneralPanel theme={theme} setTheme={onThemeChange} />}
          {tab === "data-control" && <DataControlPanel />}
          {tab === "security" && <SecurityPanel />}
        </section>
      </div>
    </Modal>
  );
}

function GeneralPanel({
  theme,
  setTheme,
}: {
  theme: UserTheme;
  setTheme?: (theme: UserTheme) => void;
}) {
  const [timezone, setTimezone] = useState("UTC");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const prefs = await fetchUserPrefsFromServer();
        if (cancelled) return;
        const tz = prefs.timezone?.trim() || detectBrowserTimezone();
        setTimezone(tz);
      } catch (err) {
        if (!cancelled) setError(formatApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      await saveUserPrefs({ timezone, language: "en" });
      setMessage("Preferences saved.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const zoneOptions = useMemo(() => {
    const values = new Set(COMMON_TIMEZONES.map((z) => z.value));
    if (timezone && !values.has(timezone)) {
      return [{ value: timezone, label: timezone }, ...COMMON_TIMEZONES];
    }
    return COMMON_TIMEZONES;
  }, [timezone]);

  if (loading) return <p className="muted">Loading preferences…</p>;

  return (
    <form className="settings-section" onSubmit={onSave}>
      <h2>General</h2>
      <p className="settings-section-desc">Time zone, language, and appearance for your account.</p>

      <label className="settings-field">
        <span className="settings-label">Time Zone</span>
        <select value={timezone} onChange={(e) => setTimezone(e.target.value)} className="settings-input">
          {zoneOptions.map((z) => (
            <option key={z.value} value={z.value}>
              {z.label}
            </option>
          ))}
        </select>
      </label>

      <label className="settings-field">
        <span className="settings-label">Language</span>
        <select value="en" disabled className="settings-input" aria-disabled="true">
          <option value="en">English (default)</option>
        </select>
        <span className="settings-hint">Additional languages will be available in a future release.</span>
      </label>

      <fieldset className="settings-field settings-theme-block">
        <legend className="settings-label">Theme</legend>
        <div className="settings-theme-card">
          <div className="settings-theme-name">
            <strong>Alpha Router</strong>
            <span className="settings-hint">Default theme</span>
          </div>
          <div className="settings-theme-toggle" role="group" aria-label="Color mode">
            <button
              type="button"
              className={`btn${theme === "light" ? "" : " btn-ghost"}`}
              aria-pressed={theme === "light"}
              onClick={() => setTheme?.("light")}
            >
              Light
            </button>
            <button
              type="button"
              className={`btn${theme === "dark" ? "" : " btn-ghost"}`}
              aria-pressed={theme === "dark"}
              onClick={() => setTheme?.("dark")}
            >
              Dark
            </button>
          </div>
        </div>
      </fieldset>

      {error && <p className="settings-error">{error}</p>}
      {message && <p className="settings-success">{message}</p>}

      <div className="settings-actions">
        <button type="submit" className="btn" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

function DataControlPanel() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function onExport() {
    setExporting(true);
    setMessage("");
    setError("");
    try {
      const res = await authFetch("/api/user/settings/chats/export");
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Export failed (${res.status})`);
      }
      const blob = await res.blob();
      const stamp = new Date().toISOString().slice(0, 10);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `alpha-router-chats-${stamp}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setMessage("Export downloaded. Private-mode chats stored only on this device are not included.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setExporting(false);
    }
  }

  async function onImportFile(file: File | null) {
    if (!file) return;
    setImporting(true);
    setMessage("");
    setError("");
    try {
      const text = await file.text();
      let payload: unknown;
      try {
        payload = JSON.parse(text);
      } catch {
        throw new Error("Invalid JSON file");
      }
      const result = await api<ImportResult>("/api/user/settings/chats/import", {
        method: "POST",
        body: JSON.stringify({ data: payload }),
      });
      setMessage(
        result.message
          || `Imported ${result.imported} chat(s)`
            + (result.skipped ? `, skipped ${result.skipped}` : "")
            + ` (${result.format}).`,
      );
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="settings-section">
      <h2>Data Control</h2>
      <p className="settings-section-desc">
        Export your chats as standard JSON, or import from ChatGPT, Open WebUI, or a prior Alpha Router export.
      </p>

      <div className="settings-card">
        <h3>Export chats</h3>
        <p className="settings-hint">
          Downloads a <code>alpha-router-chats</code> JSON file of chats stored on the server for your account.
        </p>
        <button type="button" className="btn" disabled={exporting} onClick={() => void onExport()}>
          {exporting ? "Exporting…" : "Export JSON"}
        </button>
      </div>

      <div className="settings-card">
        <h3>Import chats</h3>
        <p className="settings-hint">
          Accepts Alpha Router, ChatGPT, or Open WebUI JSON exports. Imported chats are created as new sessions.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="settings-file"
          disabled={importing}
          onChange={(e) => void onImportFile(e.target.files?.[0] ?? null)}
        />
        {importing && <p className="muted">Importing…</p>}
      </div>

      {error && <p className="settings-error">{error}</p>}
      {message && <p className="settings-success">{message}</p>}
    </div>
  );
}

function SecurityPanel() {
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pwdSaving, setPwdSaving] = useState(false);

  const [setup, setSetup] = useState<TwoFaSetup | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [busy2fa, setBusy2fa] = useState(false);

  async function refreshStatus() {
    const data = await api<SecurityStatus>("/api/user/settings/security");
    setStatus(data);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refreshStatus();
      } catch (err) {
        if (!cancelled) setError(formatApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onChangePassword(e: FormEvent) {
    e.preventDefault();
    setPwdSaving(true);
    setMessage("");
    setError("");
    try {
      await api("/api/user/settings/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage("Password updated. Other sessions have been signed out.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setPwdSaving(false);
    }
  }

  async function start2faSetup() {
    setBusy2fa(true);
    setError("");
    setMessage("");
    setBackupCodes(null);
    try {
      const data = await api<TwoFaSetup>("/api/user/settings/2fa/setup", { method: "POST" });
      setSetup(data);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy2fa(false);
    }
  }

  async function enable2fa(e: FormEvent) {
    e.preventDefault();
    setBusy2fa(true);
    setError("");
    setMessage("");
    try {
      const data = await api<{ backup_codes: string[] }>("/api/user/settings/2fa/enable", {
        method: "POST",
        body: JSON.stringify({ code: totpCode.trim() }),
      });
      setBackupCodes(data.backup_codes);
      setSetup(null);
      setTotpCode("");
      await refreshStatus();
      setMessage("Two-factor authentication enabled. Store your backup codes in a safe place.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy2fa(false);
    }
  }

  async function disable2fa(e: FormEvent) {
    e.preventDefault();
    setBusy2fa(true);
    setError("");
    setMessage("");
    try {
      await api("/api/user/settings/2fa/disable", {
        method: "POST",
        body: JSON.stringify({
          password: disablePassword,
          code: disableCode.trim() || undefined,
        }),
      });
      setDisablePassword("");
      setDisableCode("");
      setBackupCodes(null);
      await refreshStatus();
      setMessage("Two-factor authentication disabled.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy2fa(false);
    }
  }

  if (loading) return <p className="muted">Loading security settings…</p>;
  if (!status) return <p className="settings-error">{error || "Unable to load security settings."}</p>;

  const localOnlyHint = "Managed by your identity provider. Change this in LDAP/SAML/OIDC, not in Alpha Router.";

  return (
    <div className="settings-section">
      <h2>Security</h2>
      <p className="settings-section-desc">
        Password and two-factor authentication for local accounts.
        {status.auth_provider !== "local" && (
          <> Signed in via <strong>{status.auth_provider}</strong>.</>
        )}
      </p>

      <div className={`settings-card${status.two_factor_available ? "" : " settings-card--disabled"}`}>
        <h3>Two-factor authentication</h3>
        {!status.two_factor_available ? (
          <p className="settings-hint">{localOnlyHint}</p>
        ) : status.totp_enabled ? (
          <>
            <p className="settings-success">Enabled (authenticator app).</p>
            <form className="settings-stack" onSubmit={disable2fa}>
              <label className="settings-field">
                <span className="settings-label">Current password</span>
                <input
                  type="password"
                  className="settings-input"
                  autoComplete="current-password"
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  required
                />
              </label>
              <label className="settings-field">
                <span className="settings-label">Authenticator or backup code</span>
                <input
                  type="text"
                  className="settings-input"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={disableCode}
                  onChange={(e) => setDisableCode(e.target.value)}
                  required
                />
              </label>
              <button type="submit" className="btn btn-ghost" disabled={busy2fa}>
                {busy2fa ? "Working…" : "Disable 2FA"}
              </button>
            </form>
          </>
        ) : (
          <>
            <p className="settings-hint">Protect your local account with an authenticator app (TOTP).</p>
            {!setup ? (
              <button type="button" className="btn" disabled={busy2fa} onClick={() => void start2faSetup()}>
                {busy2fa ? "Preparing…" : "Enable 2FA"}
              </button>
            ) : (
              <form className="settings-stack" onSubmit={enable2fa}>
                {setup.qr_png_base64 && (
                  <img
                    className="settings-qr"
                    src={`data:image/png;base64,${setup.qr_png_base64}`}
                    alt="QR code for authenticator setup"
                  />
                )}
                <p className="settings-hint">
                  Scan the QR code, or enter this secret manually: <code>{setup.secret}</code>
                </p>
                <label className="settings-field">
                  <span className="settings-label">Verification code</span>
                  <input
                    type="text"
                    className="settings-input"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value)}
                    required
                  />
                </label>
                <button type="submit" className="btn" disabled={busy2fa}>
                  {busy2fa ? "Verifying…" : "Confirm and enable"}
                </button>
              </form>
            )}
          </>
        )}
        {backupCodes && backupCodes.length > 0 && (
          <div className="settings-backup-codes">
            <h4>Backup codes (save now — shown once)</h4>
            <ul>
              {backupCodes.map((code) => (
                <li key={code}>
                  <code>{code}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className={`settings-card${status.password_change_available ? "" : " settings-card--disabled"}`}>
        <h3>Change password</h3>
        {!status.password_change_available ? (
          <p className="settings-hint">{localOnlyHint}</p>
        ) : (
          <form className="settings-stack" onSubmit={onChangePassword}>
            <label className="settings-field">
              <span className="settings-label">Current password</span>
              <input
                type="password"
                className="settings-input"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                disabled={!status.password_change_available}
              />
            </label>
            <label className="settings-field">
              <span className="settings-label">New password</span>
              <input
                type="password"
                className="settings-input"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                disabled={!status.password_change_available}
              />
            </label>
            <label className="settings-field">
              <span className="settings-label">Confirm new password</span>
              <input
                type="password"
                className="settings-input"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                disabled={!status.password_change_available}
              />
            </label>
            <button type="submit" className="btn" disabled={pwdSaving || !status.password_change_available}>
              {pwdSaving ? "Updating…" : "Update password"}
            </button>
          </form>
        )}
      </div>

      {error && <p className="settings-error">{error}</p>}
      {message && <p className="settings-success">{message}</p>}
    </div>
  );
}
