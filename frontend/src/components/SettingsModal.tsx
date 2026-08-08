import { FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api, authFetch, formatApiError } from "../api";
import { fetchUserPrefsFromServer, saveUserPrefs, type UserTheme } from "../lib/chatStorage";
import {
  applyPersianFontToChat,
  listPersianFontOptions,
  normalizePersianFontId,
} from "../lib/persianFonts";
import {
  colorModeOf,
  composeTheme,
  namedThemeLabel,
  namedThemeOf,
  type ColorMode,
  type NamedTheme,
} from "../lib/themeCache";
import { COMMON_TIMEZONES, detectBrowserTimezone } from "../lib/timezones";
import { BROWSER_EVENT_NAMES } from "../lib/brand";
import { broadcastChatRefresh } from "../lib/chatLeader";
import Modal from "./Modal";
import ThemeSegmentedControl from "./ThemeSegmentedControl";

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

const NAMED_THEME_OPTIONS: NamedTheme[] = ["default", "mint", "dark-mint"];

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
              <span>{item.label}</span>
            </button>
          ))}
        </aside>

        <section className="settings-panel" aria-live="polite">
          {tab === "general" && (
            <GeneralPanel theme={theme} setTheme={onThemeChange} onSaved={onClose} />
          )}
          {tab === "data-control" && <DataControlPanel />}
          {tab === "security" && <SecurityPanel />}
        </section>
      </div>
    </Modal>
  );
}

function SettingsRow({
  title,
  hint,
  children,
  detail,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className={`settings-row-block${detail ? " settings-row-block--open" : ""}`}>
      <div className="settings-row">
        <div className="settings-row__meta">
          <span className="settings-row__title">{title}</span>
          {hint ? <span className="settings-row__hint">{hint}</span> : null}
        </div>
        <div className="settings-row__trail">{children}</div>
      </div>
      {detail ? <div className="settings-row__detail">{detail}</div> : null}
    </div>
  );
}

function GeneralPanel({
  theme,
  setTheme,
  onSaved,
}: {
  theme: UserTheme;
  setTheme?: (theme: UserTheme) => void;
  onSaved?: () => void;
}) {
  const [timezone, setTimezone] = useState("UTC");
  const [voiceLang, setVoiceLang] = useState("en");
  const [persianFont, setPersianFont] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const persianFontOptions = useMemo(() => listPersianFontOptions(), []);

  const named = namedThemeOf(theme);
  const mode = colorModeOf(theme);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const prefs = await fetchUserPrefsFromServer();
        if (cancelled) return;
        const tz = prefs.timezone?.trim() || detectBrowserTimezone();
        setTimezone(tz);
        setVoiceLang(prefs.voice_recording_language === "fa" ? "fa" : "en");
        setPersianFont(normalizePersianFontId(prefs.persian_font));
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
      const fontId = normalizePersianFontId(persianFont);
      await saveUserPrefs({
        timezone,
        language: "en",
        voice_recording_language: voiceLang,
        persian_font: fontId,
      });
      applyPersianFontToChat(fontId);
      setMessage("Preferences saved.");
      window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.userPrefsSaved));
      onSaved?.();
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

  const setNamed = (next: NamedTheme) => {
    if (!setTheme) return;
    if (next === "dark-mint") {
      setTheme("dark-mint");
      return;
    }
    if (next === "mint") {
      setTheme(mode === "system" ? "mint-system" : "mint");
      return;
    }
    setTheme(mode);
  };

  const setMode = (next: ColorMode) => {
    if (!setTheme) return;
    if (named === "default") {
      setTheme(composeTheme("default", next));
      return;
    }
    setTheme(composeTheme("mint", next));
  };

  if (loading) return <p className="muted">Loading preferences…</p>;

  return (
    <form className="settings-section" onSubmit={onSave}>
      <h2>General</h2>
      <p className="settings-section-desc">Account preferences and appearance.</p>

      <div className="settings-list">
        <SettingsRow title="Time zone">
          <select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="settings-row__control"
          >
            {zoneOptions.map((z) => (
              <option key={z.value} value={z.value}>
                {z.label}
              </option>
            ))}
          </select>
        </SettingsRow>

        <SettingsRow title="Language" hint="More languages coming later">
          <select value="en" disabled className="settings-row__control" aria-disabled="true">
            <option value="en">English</option>
          </select>
        </SettingsRow>

        <SettingsRow title="Voice language" hint="Used for voice transcription">
          <select
            value={voiceLang}
            onChange={(e) => setVoiceLang(e.target.value)}
            className="settings-row__control"
          >
            <option value="en">English</option>
            <option value="fa">Persian</option>
          </select>
        </SettingsRow>

        <SettingsRow title="Persian font" hint="Chat messages and composer">
          <select
            value={persianFont}
            onChange={(e) => setPersianFont(e.target.value)}
            className="settings-row__control"
          >
            <option value="">System default</option>
            {persianFontOptions.map((font) => (
              <option key={font.id} value={font.id}>
                {font.label}
              </option>
            ))}
          </select>
        </SettingsRow>

        <SettingsRow title="Theme">
          <select
            value={named}
            aria-label="Theme"
            className="settings-row__control"
            onChange={(e) => setNamed(e.target.value as NamedTheme)}
          >
            {NAMED_THEME_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {namedThemeLabel(opt)}
              </option>
            ))}
          </select>
        </SettingsRow>

        <SettingsRow title="Appearance">
          <ThemeSegmentedControl value={mode} onChange={setMode} className="settings-row__segment" />
        </SettingsRow>
      </div>

      {error && <p className="settings-error">{error}</p>}
      {message && <p className="settings-success">{message}</p>}

      <div className="settings-actions">
        <button type="submit" className="btn btn-sm btn-ghost" disabled={saving}>
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
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
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
      setMessage("Export downloaded. Private-mode chats on this device are not included.");
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
      const added = result.imported ?? 0;
      setMessage(
        result.message
          || `Added ${added} chat(s)`
            + (result.skipped ? `, skipped ${result.skipped}` : "")
            + ` (${result.format}). Existing chats were kept.`,
      );
      // Import is additive on the server — refresh the sidebar without wiping locals.
      broadcastChatRefresh({ at: Date.now(), imported: added });
      window.dispatchEvent(
        new CustomEvent(BROWSER_EVENT_NAMES.chatsImported, {
          detail: { imported: added, skipped: result.skipped ?? 0, format: result.format },
        }),
      );
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setImporting(false);
      setSelectedFile(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="settings-section">
      <h2>Data Control</h2>
      <p className="settings-section-desc">
        Export or import chats (Alpharouter, ChatGPT, or Open WebUI JSON).
        Import adds chats; it does not replace your existing history.
      </p>

      <div className="settings-list">
        <SettingsRow title="Export chats" hint="Server-stored chats as alpha-router-chats JSON">
          <button
            type="button"
            className="settings-row__action"
            disabled={exporting}
            onClick={() => void onExport()}
          >
            {exporting ? "Exporting…" : "Export"}
          </button>
        </SettingsRow>

        <SettingsRow
          title="Import chats"
          hint={selectedFile ? selectedFile.name : "Alpharouter, ChatGPT, or Open WebUI JSON"}
        >
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="settings-file-input"
            disabled={importing}
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setSelectedFile(f);
              void onImportFile(f);
            }}
          />
          <button
            type="button"
            className="settings-row__action"
            disabled={importing}
            onClick={() => fileRef.current?.click()}
          >
            {importing ? "Importing…" : "Import"}
          </button>
        </SettingsRow>
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

  const [pwdOpen, setPwdOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pwdSaving, setPwdSaving] = useState(false);

  const [setup, setSetup] = useState<TwoFaSetup | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [disableOpen, setDisableOpen] = useState(false);
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
      setPwdOpen(false);
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
    setDisableOpen(false);
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
      setDisableOpen(false);
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

  const localOnlyHint = "Managed by your identity provider.";

  return (
    <div className="settings-section">
      <h2>Security</h2>
      <p className="settings-section-desc">
        Password and two-factor authentication for local accounts.
        {status.auth_provider !== "local" && (
          <> Signed in via <strong>{status.auth_provider}</strong>.</>
        )}
      </p>

      <div className="settings-list">
        <SettingsRow
          title="Two-factor authentication"
          hint={
            !status.two_factor_available
              ? localOnlyHint
              : status.totp_enabled
                ? "Enabled · authenticator app"
                : "Protect your account with TOTP"
          }
          detail={
            (status.two_factor_available && status.totp_enabled && disableOpen && (
              <form className="settings-inline-form" onSubmit={disable2fa}>
                <input
                  type="password"
                  className="settings-row__control"
                  placeholder="Current password"
                  autoComplete="current-password"
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  required
                />
                <input
                  type="text"
                  className="settings-row__control"
                  placeholder="Authenticator or backup code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={disableCode}
                  onChange={(e) => setDisableCode(e.target.value)}
                  required
                />
                <button type="submit" className="btn btn-sm btn-ghost" disabled={busy2fa}>
                  {busy2fa ? "Working…" : "Confirm disable"}
                </button>
              </form>
            ))
            || (status.two_factor_available && !status.totp_enabled && setup && (
              <form className="settings-inline-form" onSubmit={enable2fa}>
                {setup.qr_png_base64 && (
                  <img
                    className="settings-qr"
                    src={`data:image/png;base64,${setup.qr_png_base64}`}
                    alt="QR code for authenticator setup"
                  />
                )}
                <p className="settings-row__hint">
                  Scan the QR, or enter secret <code>{setup.secret}</code>
                </p>
                <input
                  type="text"
                  className="settings-row__control"
                  placeholder="Verification code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  required
                />
                <button type="submit" className="btn btn-sm btn-ghost" disabled={busy2fa}>
                  {busy2fa ? "Verifying…" : "Confirm"}
                </button>
              </form>
            ))
            || (backupCodes && backupCodes.length > 0 && (
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
            ))
            || null
          }
        >
          {!status.two_factor_available ? (
            <span className="settings-row__value">Unavailable</span>
          ) : status.totp_enabled ? (
            <button
              type="button"
              className="settings-row__action settings-row__action--danger"
              disabled={busy2fa}
              onClick={() => {
                setDisableOpen((v) => !v);
                setSetup(null);
              }}
            >
              {disableOpen ? "Cancel" : "Disable"}
            </button>
          ) : setup ? (
            <button
              type="button"
              className="settings-row__action"
              disabled={busy2fa}
              onClick={() => setSetup(null)}
            >
              Cancel
            </button>
          ) : (
            <button
              type="button"
              className="settings-row__action"
              disabled={busy2fa}
              onClick={() => void start2faSetup()}
            >
              {busy2fa ? "Preparing…" : "Enable"}
            </button>
          )}
        </SettingsRow>

        <SettingsRow
          title="Password"
          hint={!status.password_change_available ? localOnlyHint : "Change your local password"}
          detail={
            status.password_change_available && pwdOpen ? (
              <form className="settings-inline-form" onSubmit={onChangePassword}>
                <input
                  type="password"
                  className="settings-row__control"
                  placeholder="Current password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                />
                <input
                  type="password"
                  className="settings-row__control"
                  placeholder="New password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
                <input
                  type="password"
                  className="settings-row__control"
                  placeholder="Confirm new password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                />
                <button type="submit" className="btn btn-sm btn-ghost" disabled={pwdSaving}>
                  {pwdSaving ? "Updating…" : "Update"}
                </button>
              </form>
            ) : null
          }
        >
          {!status.password_change_available ? (
            <span className="settings-row__value">Unavailable</span>
          ) : (
            <button
              type="button"
              className="settings-row__action"
              onClick={() => setPwdOpen((v) => !v)}
            >
              {pwdOpen ? "Cancel" : "Change"}
            </button>
          )}
        </SettingsRow>
      </div>

      {error && <p className="settings-error">{error}</p>}
      {message && <p className="settings-success">{message}</p>}
    </div>
  );
}
