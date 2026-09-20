import { FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { localDateKey } from "./activity/formatters";
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
import { normalizeVoiceLang, type VoiceLang } from "../lib/voiceInput";
import { COMMON_TIMEZONES, detectBrowserTimezone } from "../lib/timezones";
import { BROWSER_EVENT_NAMES } from "../lib/brand";
import { broadcastChatRefresh } from "../lib/chatLeader";
import { requestReplyNotifyPermission } from "../lib/replyReadyNotify";
import {
  deleteAllUserMemories,
  deleteUserMemory,
  exportUserMemories,
  fetchUserMemoriesBundle,
  updateUserMemory,
  type UserMemory,
} from "../lib/userMemories";
import { EMPTY_WORK_PROFILE, fetchWorkProfile, type WorkProfile } from "../lib/workProfile";
import { useConfirm } from "../context/ConfirmContext";
import Modal from "./Modal";
import PersonalApiKeyPanel from "./PersonalApiKeyPanel";
import ThemeSegmentedControl from "./ThemeSegmentedControl";

type TabId = "general" | "work-profile" | "memory" | "data-control" | "security" | "api-keys";

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
  { id: "work-profile", label: "Work profile" },
  { id: "memory", label: "Memory" },
  { id: "data-control", label: "Data Control" },
  { id: "security", label: "Security" },
  { id: "api-keys", label: "API Key" },
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
            <GeneralPanel theme={theme} setTheme={onThemeChange} />
          )}
          {tab === "work-profile" && <WorkProfilePanel />}
          {tab === "memory" && <MemoryPanel />}
          {tab === "data-control" && <DataControlPanel />}
          {tab === "security" && <SecurityPanel />}
          {tab === "api-keys" && <PersonalApiKeyPanel />}
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
  dimmed,
  stacked,
}: {
  title: ReactNode;
  hint?: ReactNode;
  children?: ReactNode;
  detail?: ReactNode;
  dimmed?: boolean;
  stacked?: boolean;
}) {
  return (
    <div
      className={`settings-row-block${detail ? " settings-row-block--open" : ""}${dimmed ? " is-dimmed" : ""}${stacked ? " settings-row-block--stacked" : ""}`}
    >
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

function SettingsToggle({
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

function GeneralPanel({
  theme,
  setTheme,
}: {
  theme: UserTheme;
  setTheme?: (theme: UserTheme) => void;
}) {
  const [timezone, setTimezone] = useState("UTC");
  const [voiceLang, setVoiceLang] = useState<VoiceLang>("auto");
  const [transcriptionModel, setTranscriptionModel] = useState("");
  const [transcriptionOptions, setTranscriptionOptions] = useState<
    Array<{ id: string; name: string }>
  >([]);
  const [persianFont, setPersianFont] = useState("");
  const [replyNotifyAway, setReplyNotifyAway] = useState(false);
  const [replyNotifySound, setReplyNotifySound] = useState(true);
  const [notifyPermissionHint, setNotifyPermissionHint] = useState("");
  const [loading, setLoading] = useState(true);
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
        setVoiceLang(normalizeVoiceLang(prefs.voice_recording_language));
        setTranscriptionModel(prefs.transcription_model || "");
        setPersianFont(normalizePersianFontId(prefs.persian_font));
        setReplyNotifyAway(!!prefs.reply_notify_away);
        setReplyNotifySound(prefs.reply_notify_sound !== false);
        if (
          prefs.reply_notify_away &&
          typeof Notification !== "undefined" &&
          Notification.permission === "denied"
        ) {
          setNotifyPermissionHint(
            "Browser notifications are blocked. You’ll still get an in-app toast when another chat is open.",
          );
        }
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

  // Only models this user may actually use: the endpoint already filters by ACL.
  useEffect(() => {
    let cancelled = false;
    api<Array<{ id: string; name: string; kinds?: string[] }>>("/api/chat/models")
      .then((rows) => {
        if (cancelled) return;
        setTranscriptionOptions(
          (rows || [])
            .filter((m) => (m.kinds || []).includes("transcription"))
            .map((m) => ({ id: m.id, name: m.name }))
            .sort((a, b) => a.name.localeCompare(b.name)),
        );
      })
      .catch(() => {
        if (!cancelled) setTranscriptionOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function persistPrefs(updates: {
    timezone?: string;
    voice_recording_language?: VoiceLang;
    transcription_model?: string;
    persian_font?: string;
    reply_notify_away?: boolean;
    reply_notify_sound?: boolean;
  }) {
    setError("");
    try {
      if (updates.persian_font !== undefined) {
        updates = { ...updates, persian_font: normalizePersianFontId(updates.persian_font) };
        applyPersianFontToChat(updates.persian_font);
      }
      await saveUserPrefs(updates);
      window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.userPrefsSaved));
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function onReplyNotifyAwayChange(checked: boolean) {
    setReplyNotifyAway(checked);
    setNotifyPermissionHint("");
    void persistPrefs({ reply_notify_away: checked });
    if (!checked) return;
    const permission = await requestReplyNotifyPermission();
    if (permission === "denied") {
      setNotifyPermissionHint(
        "Browser notifications are blocked. You’ll still get an in-app toast when another chat is open.",
      );
    } else if (permission === "unsupported") {
      setNotifyPermissionHint(
        "This browser does not support OS notifications. In-app toasts still work when another chat is open.",
      );
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
    <div className="settings-section">
      <h2>General</h2>
      <p className="settings-section-desc">Account preferences and appearance.</p>

      <div className="settings-list">
        <SettingsRow title="Time zone">
          <select
            value={timezone}
            onChange={(e) => {
              const value = e.target.value;
              setTimezone(value);
              void persistPrefs({ timezone: value });
            }}
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
            onChange={(e) => {
              const value = normalizeVoiceLang(e.target.value);
              setVoiceLang(value);
              void persistPrefs({ voice_recording_language: value });
            }}
            className="settings-row__control"
          >
            <option value="auto">Auto — detect</option>
            <option value="en">English</option>
            <option value="fa">Persian</option>
          </select>
        </SettingsRow>

        {transcriptionOptions.length ? (
          <SettingsRow title="Transcription model" hint="Used by the microphone button">
            <select
              value={transcriptionModel}
              onChange={(e) => {
                const value = e.target.value;
                setTranscriptionModel(value);
                void persistPrefs({ transcription_model: value });
              }}
              className="settings-row__control"
            >
              <option value="">System default</option>
              {transcriptionOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </SettingsRow>
        ) : null}

        <SettingsRow title="Persian font" hint="Chat messages and composer">
          <select
            value={persianFont}
            onChange={(e) => {
              const value = e.target.value;
              setPersianFont(value);
              void persistPrefs({ persian_font: value });
            }}
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

        <SettingsRow
          title="Chat notification"
          hint="Only when the tab is in the background or you are in another chat"
          detail={
            <>
              <div className="settings-inline-check">
                <SettingsToggle
                  on={replyNotifySound}
                  disabled={!replyNotifyAway}
                  label="Play sound"
                  onToggle={() => {
                    if (!replyNotifyAway) return;
                    const next = !replyNotifySound;
                    setReplyNotifySound(next);
                    void persistPrefs({ reply_notify_sound: next });
                  }}
                />
                <span>Play sound</span>
              </div>
              {notifyPermissionHint ? (
                <p className="settings-row__hint" style={{ margin: "0.45rem 0 0" }}>
                  {notifyPermissionHint}
                </p>
              ) : null}
            </>
          }
        >
          <SettingsToggle
            on={replyNotifyAway}
            label="Notify when a chat finishes only when away"
            onToggle={() => void onReplyNotifyAwayChange(!replyNotifyAway)}
          />
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

      {error && <p className="settings-error" role="alert">{error}</p>}
    </div>
  );
}

function relativeTime(ms: number | null | undefined): string {
  if (!ms) return "";
  const delta = Date.now() - ms;
  const minutes = Math.round(delta / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  return `${months}mo ago`;
}

function WorkProfilePanel() {
  const [profile, setProfile] = useState<WorkProfile>(EMPTY_WORK_PROFILE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Its own endpoint: this screen has nothing to do with Memory and
        // must not go dark when the memory feature does.
        const loaded = await fetchWorkProfile();
        if (cancelled) return;
        setProfile(loaded);
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

  if (loading) return <p className="muted">Loading your work profile…</p>;

  const hasProfile = !!(
    profile.company || profile.department || profile.job_title || profile.reporting_to
  );

  return (
    <div className="settings-section">
      <h2>Work profile</h2>
      <p className="settings-section-desc">
        Where you sit in the organization, read from your account&apos;s user properties and kept by your
        administrator. These are added alongside chat history in non-private chats and never replace it. Private chats
        never receive them.
      </p>
      <div className="settings-list">
        <SettingsRow title="Company">
          <span className="settings-row__readonly">{profile.company || "—"}</span>
        </SettingsRow>
        <SettingsRow title="Department">
          <span className="settings-row__readonly">{profile.department || "—"}</span>
        </SettingsRow>
        <SettingsRow title="Job title">
          <span className="settings-row__readonly">{profile.job_title || "—"}</span>
        </SettingsRow>
        <SettingsRow title="Manager">
          <span className="settings-row__readonly">{profile.reporting_to || "—"}</span>
        </SettingsRow>
      </div>
      {!hasProfile ? (
        <p className="muted" style={{ marginTop: "0.45rem" }}>
          No company, department, job title, or manager is set on your account yet.
        </p>
      ) : null}
      {error ? <p className="settings-error" role="alert">{error}</p> : null}
    </div>
  );
}

function MemoryPanel() {
  const { confirm } = useConfirm();
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [autoCapture, setAutoCapture] = useState(true);
  const [memories, setMemories] = useState<UserMemory[]>([]);
  const [featureEnabled, setFeatureEnabled] = useState(true);
  const [extractionConfigured, setExtractionConfigured] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [prefs, bundle] = await Promise.all([
      fetchUserPrefsFromServer(),
      fetchUserMemoriesBundle({ limit: 200, offset: 0 }),
    ]);
    setMemoryEnabled(prefs.memory_enabled !== false);
    setAutoCapture(prefs.memory_auto_capture !== false);
    setMemories(bundle.memories);
    setFeatureEnabled(bundle.feature_enabled);
    setExtractionConfigured(bundle.extraction_configured);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refresh();
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

  async function onToggleMemory(checked: boolean) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await saveUserPrefs({ memory_enabled: checked });
      setMemoryEnabled(checked);
      window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.userPrefsSaved));
      setMessage(checked ? "Memories will be referenced in chat." : "Memory referencing is off.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onToggleCapture(checked: boolean) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await saveUserPrefs({ memory_auto_capture: checked });
      setAutoCapture(checked);
      window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.userPrefsSaved));
      setMessage(checked ? "New memories can be learned from chat." : "Automatic learning is off.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onToggleItem(item: UserMemory, enabled: boolean) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await updateUserMemory(item.id, { enabled });
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteItem(id: string) {
    const ok = await confirm({
      title: "Delete memory",
      message: "Delete this memory? It will not be learned again from old chats.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await deleteUserMemory(id);
      await refresh();
      setMessage("Memory deleted.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onExport() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await exportUserMemories();
      setMessage("Memories exported.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteAll() {
    const count = memories.length;
    if (count === 0) {
      setError("");
      setMessage("No memories to delete.");
      return;
    }
    const countLabel = count === 1 ? "1 memory" : `${count.toLocaleString()} memories`;
    const step1 = await confirm({
      title: "Delete all memories — step 1 of 3",
      message:
        `This permanently deletes every saved memory for your account (currently ${countLabel}). ` +
        "Your chat history is not removed. Continue?",
      confirmLabel: "Continue",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!step1) return;
    const step2 = await confirm({
      title: "Delete all memories — step 2 of 3",
      message:
        "Alpha Router will stop using these facts in future chats. Deleted memories are blocked from being " +
        "learned again from the same old conversations, and anything you deleted one by one stays blocked. " +
        "This cannot be undone. Proceed?",
      confirmLabel: "I understand — continue",
      cancelLabel: "Stop",
      danger: true,
    });
    if (!step2) return;
    const step3 = await confirm({
      title: "Delete all memories — final confirmation",
      message:
        `Final step: permanently delete all ${countLabel} now. There is no undo inside Alpharouter. ` +
        "Confirm only if you are certain.",
      confirmLabel: "Delete all memories now",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!step3) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const deleted = await deleteAllUserMemories();
      await refresh();
      setMessage(deleted ? `Deleted ${deleted} memor${deleted === 1 ? "y" : "ies"}.` : "No memories to delete.");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="muted">Loading memory…</p>;

  return (
    <div className="settings-section">
      <h2>Memory</h2>
      <p className="settings-section-desc">
        Durable facts learned from non-private chats. They are added alongside chat history and never replace it.
        Private chats never use memories, and learning is silent.
      </p>

      {!featureEnabled || !extractionConfigured ? (
        <p className="settings-memory-banner">
          Automatic memory is currently unavailable
          {!featureEnabled ? " (disabled by your administrator)" : " (not configured yet)"}. Existing memories can still
          be viewed, disabled, or deleted.
        </p>
      ) : null}

      <div className="settings-list">
        <SettingsRow
          title="Use my memories in chat"
          hint="Reference saved facts in non-private chats"
        >
          <SettingsToggle
            on={memoryEnabled}
            disabled={busy}
            label="Use my memories in chat"
            onToggle={() => void onToggleMemory(!memoryEnabled)}
          />
        </SettingsRow>
        <SettingsRow
          title="Automatically learn new things about me"
          hint="Learn durable facts from non-private chats. Private chats are excluded."
        >
          <SettingsToggle
            on={autoCapture}
            disabled={busy}
            label="Automatically learn new things about me"
            onToggle={() => void onToggleCapture(!autoCapture)}
          />
        </SettingsRow>
      </div>

      <h3 className="settings-subsection-title">What Alpha Router remembers</h3>
      <div className="settings-list" role="list">
        {memories.length === 0 ? (
          <div className="settings-row">
            <span className="settings-row__hint">
              No memories yet. After a few non-private conversations, durable facts about you will appear here
              automatically.
            </span>
          </div>
        ) : (
          memories.map((item) => (
            <SettingsRow
              key={item.id}
              dimmed={!item.enabled}
              stacked
              title={item.content}
              hint={
                <>
                  <span className="settings-memory-chip">{item.category || "other"}</span>
                  {relativeTime(item.created_at) ? <span>{relativeTime(item.created_at)}</span> : null}
                  {item.source_session_id ? (
                    <a href={`/app/chat?session=${encodeURIComponent(item.source_session_id)}`}>
                      {item.source_session_title || "Open source chat"}
                    </a>
                  ) : item.source_session_title ? (
                    <span>From {item.source_session_title}</span>
                  ) : null}
                </>
              }
            >
              <button
                type="button"
                className="settings-row__action"
                disabled={busy}
                onClick={() => void onToggleItem(item, !item.enabled)}
              >
                {item.enabled ? "Disable" : "Enable"}
              </button>
              <button
                type="button"
                className="settings-row__action settings-row__action--danger"
                disabled={busy}
                onClick={() => void onDeleteItem(item.id)}
              >
                Delete
              </button>
            </SettingsRow>
          ))
        )}
      </div>

      <h3 className="settings-subsection-title">Danger zone</h3>
      <div className="settings-list">
        <SettingsRow title="Export my memories" hint="Download every saved fact as JSON">
          <button type="button" className="settings-row__action" disabled={busy} onClick={() => void onExport()}>
            Export
          </button>
        </SettingsRow>
        <SettingsRow
          title="Delete all memories"
          hint="Permanently delete every memory. Old chats will not be re-learned."
        >
          <button
            type="button"
            className="settings-row__action settings-row__action--danger"
            disabled={busy}
            onClick={() => void onDeleteAll()}
          >
            Delete all
          </button>
        </SettingsRow>
      </div>

      {error && <p className="settings-error" role="alert">{error}</p>}
      {message && <p className="settings-success">{message}</p>}
    </div>
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
      const stamp = localDateKey(new Date()); // the user's own calendar day, not UTC
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

      {error && <p className="settings-error" role="alert">{error}</p>}
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
  if (!status) return <p className="settings-error" role="alert">{error || "Unable to load security settings."}</p>;

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

      {error && <p className="settings-error" role="alert">{error}</p>}
      {message && <p className="settings-success">{message}</p>}
    </div>
  );
}
