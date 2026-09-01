import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, authFetch, formatApiError } from "../api";
import { fetchUserPrefsFromServer, saveUserPrefs } from "../lib/chatStorage";
import { applyPersianFontToChat, listPersianFontOptions, normalizePersianFontId, } from "../lib/persianFonts";
import { colorModeOf, composeTheme, namedThemeLabel, namedThemeOf, } from "../lib/themeCache";
import { COMMON_TIMEZONES, detectBrowserTimezone } from "../lib/timezones";
import { BROWSER_EVENT_NAMES } from "../lib/brand";
import { broadcastChatRefresh } from "../lib/chatLeader";
import { requestReplyNotifyPermission } from "../lib/replyReadyNotify";
import { deleteAllUserMemories, deleteUserMemory, exportUserMemories, fetchUserMemoriesBundle, updateUserMemory, } from "../lib/userMemories";
import { useConfirm } from "../context/ConfirmContext";
import Modal from "./Modal";
import PersonalApiKeyPanel from "./PersonalApiKeyPanel";
import ThemeSegmentedControl from "./ThemeSegmentedControl";
const TABS = [
    { id: "general", label: "General" },
    { id: "personalization", label: "Personalization" },
    { id: "memory", label: "Memory" },
    { id: "data-control", label: "Data Control" },
    { id: "security", label: "Security" },
    { id: "api-keys", label: "API Key" },
];
const NAMED_THEME_OPTIONS = ["default", "mint", "dark-mint"];
export default function SettingsModal({ open, onClose, theme, onThemeChange }) {
    const [tab, setTab] = useState("general");
    useEffect(() => {
        if (open)
            setTab("general");
    }, [open]);
    return (_jsx(Modal, { open: open, title: "Settings", onClose: onClose, panelClassName: "modal-panel--settings", bodyClassName: "modal-body--settings", children: _jsxs("div", { className: "settings-shell settings-shell--modal", children: [_jsx("aside", { className: "settings-nav", "aria-label": "Settings sections", children: TABS.map((item) => (_jsx("button", { type: "button", className: `settings-nav-item${tab === item.id ? " active" : ""}`, onClick: () => setTab(item.id), "aria-current": tab === item.id ? "page" : undefined, children: _jsx("span", { children: item.label }) }, item.id))) }), _jsxs("section", { className: "settings-panel", "aria-live": "polite", children: [tab === "general" && (_jsx(GeneralPanel, { theme: theme, setTheme: onThemeChange })), tab === "personalization" && _jsx(PersonalizationPanel, {}), tab === "memory" && _jsx(MemoryPanel, {}), tab === "data-control" && _jsx(DataControlPanel, {}), tab === "security" && _jsx(SecurityPanel, {}), tab === "api-keys" && _jsx(PersonalApiKeyPanel, {})] })] }) }));
}
function SettingsRow({ title, hint, children, detail, dimmed, stacked, }) {
    return (_jsxs("div", { className: `settings-row-block${detail ? " settings-row-block--open" : ""}${dimmed ? " is-dimmed" : ""}${stacked ? " settings-row-block--stacked" : ""}`, children: [_jsxs("div", { className: "settings-row", children: [_jsxs("div", { className: "settings-row__meta", children: [_jsx("span", { className: "settings-row__title", children: title }), hint ? _jsx("span", { className: "settings-row__hint", children: hint }) : null] }), children ? _jsx("div", { className: "settings-row__trail", children: children }) : null] }), detail ? _jsx("div", { className: "settings-row__detail", children: detail }) : null] }));
}
function SettingsToggle({ on, disabled, label, onToggle, }) {
    return (_jsx("button", { type: "button", className: `alpha-router-toggle${on ? " on" : ""}`, onClick: onToggle, "aria-label": label, "aria-pressed": on, disabled: disabled, children: _jsx("span", { className: "alpha-router-toggle-knob" }) }));
}
function GeneralPanel({ theme, setTheme, }) {
    const [timezone, setTimezone] = useState("UTC");
    const [voiceLang, setVoiceLang] = useState("en");
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
                if (cancelled)
                    return;
                const tz = prefs.timezone?.trim() || detectBrowserTimezone();
                setTimezone(tz);
                setVoiceLang(prefs.voice_recording_language === "fa" ? "fa" : "en");
                setPersianFont(normalizePersianFontId(prefs.persian_font));
                setReplyNotifyAway(!!prefs.reply_notify_away);
                setReplyNotifySound(prefs.reply_notify_sound !== false);
                if (prefs.reply_notify_away &&
                    typeof Notification !== "undefined" &&
                    Notification.permission === "denied") {
                    setNotifyPermissionHint("Browser notifications are blocked. You’ll still get an in-app toast when another chat is open.");
                }
            }
            catch (err) {
                if (!cancelled)
                    setError(formatApiError(err));
            }
            finally {
                if (!cancelled)
                    setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);
    async function persistPrefs(updates) {
        setError("");
        try {
            if (updates.persian_font !== undefined) {
                updates = { ...updates, persian_font: normalizePersianFontId(updates.persian_font) };
                applyPersianFontToChat(updates.persian_font);
            }
            await saveUserPrefs(updates);
            window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.userPrefsSaved));
        }
        catch (err) {
            setError(formatApiError(err));
        }
    }
    async function onReplyNotifyAwayChange(checked) {
        setReplyNotifyAway(checked);
        setNotifyPermissionHint("");
        void persistPrefs({ reply_notify_away: checked });
        if (!checked)
            return;
        const permission = await requestReplyNotifyPermission();
        if (permission === "denied") {
            setNotifyPermissionHint("Browser notifications are blocked. You’ll still get an in-app toast when another chat is open.");
        }
        else if (permission === "unsupported") {
            setNotifyPermissionHint("This browser does not support OS notifications. In-app toasts still work when another chat is open.");
        }
    }
    const zoneOptions = useMemo(() => {
        const values = new Set(COMMON_TIMEZONES.map((z) => z.value));
        if (timezone && !values.has(timezone)) {
            return [{ value: timezone, label: timezone }, ...COMMON_TIMEZONES];
        }
        return COMMON_TIMEZONES;
    }, [timezone]);
    const setNamed = (next) => {
        if (!setTheme)
            return;
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
    const setMode = (next) => {
        if (!setTheme)
            return;
        if (named === "default") {
            setTheme(composeTheme("default", next));
            return;
        }
        setTheme(composeTheme("mint", next));
    };
    if (loading)
        return _jsx("p", { className: "muted", children: "Loading preferences\u2026" });
    return (_jsxs("div", { className: "settings-section", children: [_jsx("h2", { children: "General" }), _jsx("p", { className: "settings-section-desc", children: "Account preferences and appearance." }), _jsxs("div", { className: "settings-list", children: [_jsx(SettingsRow, { title: "Time zone", children: _jsx("select", { value: timezone, onChange: (e) => {
                                const value = e.target.value;
                                setTimezone(value);
                                void persistPrefs({ timezone: value });
                            }, className: "settings-row__control", children: zoneOptions.map((z) => (_jsx("option", { value: z.value, children: z.label }, z.value))) }) }), _jsx(SettingsRow, { title: "Language", hint: "More languages coming later", children: _jsx("select", { value: "en", disabled: true, className: "settings-row__control", "aria-disabled": "true", children: _jsx("option", { value: "en", children: "English" }) }) }), _jsx(SettingsRow, { title: "Voice language", hint: "Used for voice transcription", children: _jsxs("select", { value: voiceLang, onChange: (e) => {
                                const value = e.target.value;
                                setVoiceLang(value);
                                void persistPrefs({ voice_recording_language: value });
                            }, className: "settings-row__control", children: [_jsx("option", { value: "en", children: "English" }), _jsx("option", { value: "fa", children: "Persian" })] }) }), _jsx(SettingsRow, { title: "Persian font", hint: "Chat messages and composer", children: _jsxs("select", { value: persianFont, onChange: (e) => {
                                const value = e.target.value;
                                setPersianFont(value);
                                void persistPrefs({ persian_font: value });
                            }, className: "settings-row__control", children: [_jsx("option", { value: "", children: "System default" }), persianFontOptions.map((font) => (_jsx("option", { value: font.id, children: font.label }, font.id)))] }) }), _jsx(SettingsRow, { title: "Chat notification", hint: "Only when the tab is in the background or you are in another chat", detail: _jsxs(_Fragment, { children: [_jsxs("div", { className: "settings-inline-check", children: [_jsx(SettingsToggle, { on: replyNotifySound, disabled: !replyNotifyAway, label: "Play sound", onToggle: () => {
                                                if (!replyNotifyAway)
                                                    return;
                                                const next = !replyNotifySound;
                                                setReplyNotifySound(next);
                                                void persistPrefs({ reply_notify_sound: next });
                                            } }), _jsx("span", { children: "Play sound" })] }), notifyPermissionHint ? (_jsx("p", { className: "settings-row__hint", style: { margin: "0.45rem 0 0" }, children: notifyPermissionHint })) : null] }), children: _jsx(SettingsToggle, { on: replyNotifyAway, label: "Notify when a chat finishes only when away", onToggle: () => void onReplyNotifyAwayChange(!replyNotifyAway) }) }), _jsx(SettingsRow, { title: "Theme", children: _jsx("select", { value: named, "aria-label": "Theme", className: "settings-row__control", onChange: (e) => setNamed(e.target.value), children: NAMED_THEME_OPTIONS.map((opt) => (_jsx("option", { value: opt, children: namedThemeLabel(opt) }, opt))) }) }), _jsx(SettingsRow, { title: "Appearance", children: _jsx(ThemeSegmentedControl, { value: mode, onChange: setMode, className: "settings-row__segment" }) })] }), error && _jsx("p", { className: "settings-error", children: error })] }));
}
function relativeTime(ms) {
    if (!ms)
        return "";
    const delta = Date.now() - ms;
    const minutes = Math.round(delta / 60000);
    if (minutes < 1)
        return "just now";
    if (minutes < 60)
        return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24)
        return `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days < 30)
        return `${days}d ago`;
    const months = Math.round(days / 30);
    return `${months}mo ago`;
}
function PersonalizationPanel() {
    const [profile, setProfile] = useState({
        company: null,
        department: null,
        job_title: null,
        reporting_to: null,
    });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const bundle = await fetchUserMemoriesBundle({ limit: 1, offset: 0 });
                if (cancelled)
                    return;
                setProfile(bundle.profile);
            }
            catch (err) {
                if (!cancelled)
                    setError(formatApiError(err));
            }
            finally {
                if (!cancelled)
                    setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);
    if (loading)
        return _jsx("p", { className: "muted", children: "Loading personalization\u2026" });
    const hasProfile = !!(profile.company || profile.department || profile.job_title || profile.reporting_to);
    return (_jsxs("div", { className: "settings-section", children: [_jsx("h2", { children: "Personalization" }), _jsx("p", { className: "settings-section-desc", children: "Read-only directory fields from your account. They are added alongside chat history in non-private chats and never replace it. Private chats never receive this context." }), _jsxs("div", { className: "settings-list", children: [_jsx(SettingsRow, { title: "Company", hint: "From User Properties", children: _jsx("span", { className: "settings-row__readonly", children: profile.company || "—" }) }), _jsx(SettingsRow, { title: "Department", hint: "From User Properties", children: _jsx("span", { className: "settings-row__readonly", children: profile.department || "—" }) }), _jsx(SettingsRow, { title: "Job title", hint: "From User Properties", children: _jsx("span", { className: "settings-row__readonly", children: profile.job_title || "—" }) }), _jsx(SettingsRow, { title: "Report to", hint: "From User Properties", children: _jsx("span", { className: "settings-row__readonly", children: profile.reporting_to || "—" }) })] }), !hasProfile ? (_jsx("p", { className: "muted", style: { marginTop: "0.45rem" }, children: "No company, department, job title, or report-to is set on your account yet." })) : null, error ? _jsx("p", { className: "settings-error", children: error }) : null] }));
}
function MemoryPanel() {
    const { confirm } = useConfirm();
    const [memoryEnabled, setMemoryEnabled] = useState(true);
    const [autoCapture, setAutoCapture] = useState(true);
    const [memories, setMemories] = useState([]);
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
            }
            catch (err) {
                if (!cancelled)
                    setError(formatApiError(err));
            }
            finally {
                if (!cancelled)
                    setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);
    async function onToggleMemory(checked) {
        setBusy(true);
        setError("");
        setMessage("");
        try {
            await saveUserPrefs({ memory_enabled: checked });
            setMemoryEnabled(checked);
            window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.userPrefsSaved));
            setMessage(checked ? "Memories will be referenced in chat." : "Memory referencing is off.");
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function onToggleCapture(checked) {
        setBusy(true);
        setError("");
        setMessage("");
        try {
            await saveUserPrefs({ memory_auto_capture: checked });
            setAutoCapture(checked);
            window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.userPrefsSaved));
            setMessage(checked ? "New memories can be learned from chat." : "Automatic learning is off.");
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function onToggleItem(item, enabled) {
        setBusy(true);
        setError("");
        setMessage("");
        try {
            await updateUserMemory(item.id, { enabled });
            await refresh();
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    async function onDeleteItem(id) {
        const ok = await confirm({
            title: "Delete memory",
            message: "Delete this memory? It will not be learned again from old chats.",
            confirmLabel: "Delete",
            danger: true,
        });
        if (!ok)
            return;
        setBusy(true);
        setError("");
        setMessage("");
        try {
            await deleteUserMemory(id);
            await refresh();
            setMessage("Memory deleted.");
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
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
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
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
            message: `This permanently deletes every saved memory for your account (currently ${countLabel}). ` +
                "Your chat history is not removed. Continue?",
            confirmLabel: "Continue",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!step1)
            return;
        const step2 = await confirm({
            title: "Delete all memories — step 2 of 3",
            message: "Alpha Router will stop using these facts in future chats. Deleted memories are blocked from being " +
                "learned again from the same old conversations. This cannot be undone. Proceed?",
            confirmLabel: "I understand — continue",
            cancelLabel: "Stop",
            danger: true,
        });
        if (!step2)
            return;
        const step3 = await confirm({
            title: "Delete all memories — final confirmation",
            message: `Final step: permanently delete all ${countLabel} now. There is no undo inside Alpharouter. ` +
                "Confirm only if you are certain.",
            confirmLabel: "Delete all memories now",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!step3)
            return;
        setBusy(true);
        setError("");
        setMessage("");
        try {
            const deleted = await deleteAllUserMemories();
            await refresh();
            setMessage(deleted ? `Deleted ${deleted} memor${deleted === 1 ? "y" : "ies"}.` : "No memories to delete.");
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy(false);
        }
    }
    if (loading)
        return _jsx("p", { className: "muted", children: "Loading memory\u2026" });
    return (_jsxs("div", { className: "settings-section", children: [_jsx("h2", { children: "Memory" }), _jsx("p", { className: "settings-section-desc", children: "Durable facts learned from non-private chats. They are added alongside chat history and never replace it. Private chats never use memories, and learning is silent." }), !featureEnabled || !extractionConfigured ? (_jsxs("p", { className: "settings-memory-banner", children: ["Automatic memory is currently unavailable", !featureEnabled ? " (disabled by your administrator)" : " (not configured yet)", ". Existing memories can still be viewed, disabled, or deleted."] })) : null, _jsxs("div", { className: "settings-list", children: [_jsx(SettingsRow, { title: "Use my memories in chat", hint: "Reference saved facts in non-private chats", children: _jsx(SettingsToggle, { on: memoryEnabled, disabled: busy, label: "Use my memories in chat", onToggle: () => void onToggleMemory(!memoryEnabled) }) }), _jsx(SettingsRow, { title: "Automatically learn new things about me", hint: "Learn durable facts from non-private chats. Private chats are excluded.", children: _jsx(SettingsToggle, { on: autoCapture, disabled: busy, label: "Automatically learn new things about me", onToggle: () => void onToggleCapture(!autoCapture) }) })] }), _jsx("h3", { className: "settings-subsection-title", children: "What Alpha Router remembers" }), _jsx("div", { className: "settings-list", role: "list", children: memories.length === 0 ? (_jsx("div", { className: "settings-row", children: _jsx("span", { className: "settings-row__hint", children: "No memories yet. After a few non-private conversations, durable facts about you will appear here automatically." }) })) : (memories.map((item) => (_jsxs(SettingsRow, { dimmed: !item.enabled, stacked: true, title: item.content, hint: _jsxs(_Fragment, { children: [_jsx("span", { className: "settings-memory-chip", children: item.category || "other" }), relativeTime(item.created_at) ? _jsx("span", { children: relativeTime(item.created_at) }) : null, item.source_session_id ? (_jsx("a", { href: `/app/chat?session=${encodeURIComponent(item.source_session_id)}`, children: item.source_session_title || "Open source chat" })) : item.source_session_title ? (_jsxs("span", { children: ["From ", item.source_session_title] })) : null] }), children: [_jsx("button", { type: "button", className: "settings-row__action", disabled: busy, onClick: () => void onToggleItem(item, !item.enabled), children: item.enabled ? "Disable" : "Enable" }), _jsx("button", { type: "button", className: "settings-row__action settings-row__action--danger", disabled: busy, onClick: () => void onDeleteItem(item.id), children: "Delete" })] }, item.id)))) }), _jsx("h3", { className: "settings-subsection-title", children: "Danger zone" }), _jsxs("div", { className: "settings-list", children: [_jsx(SettingsRow, { title: "Export my memories", hint: "Download every saved fact as JSON", children: _jsx("button", { type: "button", className: "settings-row__action", disabled: busy, onClick: () => void onExport(), children: "Export" }) }), _jsx(SettingsRow, { title: "Delete all memories", hint: "Permanently delete every memory. Old chats will not be re-learned.", children: _jsx("button", { type: "button", className: "settings-row__action settings-row__action--danger", disabled: busy, onClick: () => void onDeleteAll(), children: "Delete all" }) })] }), error && _jsx("p", { className: "settings-error", children: error }), message && _jsx("p", { className: "settings-success", children: message })] }));
}
function DataControlPanel() {
    const fileRef = useRef(null);
    const [exporting, setExporting] = useState(false);
    const [importing, setImporting] = useState(false);
    const [selectedFile, setSelectedFile] = useState(null);
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
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setExporting(false);
        }
    }
    async function onImportFile(file) {
        if (!file)
            return;
        setImporting(true);
        setMessage("");
        setError("");
        try {
            const text = await file.text();
            let payload;
            try {
                payload = JSON.parse(text);
            }
            catch {
                throw new Error("Invalid JSON file");
            }
            const result = await api("/api/user/settings/chats/import", {
                method: "POST",
                body: JSON.stringify({ data: payload }),
            });
            const added = result.imported ?? 0;
            setMessage(result.message
                || `Added ${added} chat(s)`
                    + (result.skipped ? `, skipped ${result.skipped}` : "")
                    + ` (${result.format}). Existing chats were kept.`);
            // Import is additive on the server — refresh the sidebar without wiping locals.
            broadcastChatRefresh({ at: Date.now(), imported: added });
            window.dispatchEvent(new CustomEvent(BROWSER_EVENT_NAMES.chatsImported, {
                detail: { imported: added, skipped: result.skipped ?? 0, format: result.format },
            }));
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setImporting(false);
            setSelectedFile(null);
            if (fileRef.current)
                fileRef.current.value = "";
        }
    }
    return (_jsxs("div", { className: "settings-section", children: [_jsx("h2", { children: "Data Control" }), _jsx("p", { className: "settings-section-desc", children: "Export or import chats (Alpharouter, ChatGPT, or Open WebUI JSON). Import adds chats; it does not replace your existing history." }), _jsxs("div", { className: "settings-list", children: [_jsx(SettingsRow, { title: "Export chats", hint: "Server-stored chats as alpha-router-chats JSON", children: _jsx("button", { type: "button", className: "settings-row__action", disabled: exporting, onClick: () => void onExport(), children: exporting ? "Exporting…" : "Export" }) }), _jsxs(SettingsRow, { title: "Import chats", hint: selectedFile ? selectedFile.name : "Alpharouter, ChatGPT, or Open WebUI JSON", children: [_jsx("input", { ref: fileRef, type: "file", accept: "application/json,.json", className: "settings-file-input", disabled: importing, onChange: (e) => {
                                    const f = e.target.files?.[0] ?? null;
                                    setSelectedFile(f);
                                    void onImportFile(f);
                                } }), _jsx("button", { type: "button", className: "settings-row__action", disabled: importing, onClick: () => fileRef.current?.click(), children: importing ? "Importing…" : "Import" })] })] }), error && _jsx("p", { className: "settings-error", children: error }), message && _jsx("p", { className: "settings-success", children: message })] }));
}
function SecurityPanel() {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");
    const [pwdOpen, setPwdOpen] = useState(false);
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [pwdSaving, setPwdSaving] = useState(false);
    const [setup, setSetup] = useState(null);
    const [totpCode, setTotpCode] = useState("");
    const [backupCodes, setBackupCodes] = useState(null);
    const [disableOpen, setDisableOpen] = useState(false);
    const [disablePassword, setDisablePassword] = useState("");
    const [disableCode, setDisableCode] = useState("");
    const [busy2fa, setBusy2fa] = useState(false);
    async function refreshStatus() {
        const data = await api("/api/user/settings/security");
        setStatus(data);
    }
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                await refreshStatus();
            }
            catch (err) {
                if (!cancelled)
                    setError(formatApiError(err));
            }
            finally {
                if (!cancelled)
                    setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);
    async function onChangePassword(e) {
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
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
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
            const data = await api("/api/user/settings/2fa/setup", { method: "POST" });
            setSetup(data);
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy2fa(false);
        }
    }
    async function enable2fa(e) {
        e.preventDefault();
        setBusy2fa(true);
        setError("");
        setMessage("");
        try {
            const data = await api("/api/user/settings/2fa/enable", {
                method: "POST",
                body: JSON.stringify({ code: totpCode.trim() }),
            });
            setBackupCodes(data.backup_codes);
            setSetup(null);
            setTotpCode("");
            await refreshStatus();
            setMessage("Two-factor authentication enabled. Store your backup codes in a safe place.");
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy2fa(false);
        }
    }
    async function disable2fa(e) {
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
        }
        catch (err) {
            setError(formatApiError(err));
        }
        finally {
            setBusy2fa(false);
        }
    }
    if (loading)
        return _jsx("p", { className: "muted", children: "Loading security settings\u2026" });
    if (!status)
        return _jsx("p", { className: "settings-error", children: error || "Unable to load security settings." });
    const localOnlyHint = "Managed by your identity provider.";
    return (_jsxs("div", { className: "settings-section", children: [_jsx("h2", { children: "Security" }), _jsxs("p", { className: "settings-section-desc", children: ["Password and two-factor authentication for local accounts.", status.auth_provider !== "local" && (_jsxs(_Fragment, { children: [" Signed in via ", _jsx("strong", { children: status.auth_provider }), "."] }))] }), _jsxs("div", { className: "settings-list", children: [_jsx(SettingsRow, { title: "Two-factor authentication", hint: !status.two_factor_available
                            ? localOnlyHint
                            : status.totp_enabled
                                ? "Enabled · authenticator app"
                                : "Protect your account with TOTP", detail: (status.two_factor_available && status.totp_enabled && disableOpen && (_jsxs("form", { className: "settings-inline-form", onSubmit: disable2fa, children: [_jsx("input", { type: "password", className: "settings-row__control", placeholder: "Current password", autoComplete: "current-password", value: disablePassword, onChange: (e) => setDisablePassword(e.target.value), required: true }), _jsx("input", { type: "text", className: "settings-row__control", placeholder: "Authenticator or backup code", inputMode: "numeric", autoComplete: "one-time-code", value: disableCode, onChange: (e) => setDisableCode(e.target.value), required: true }), _jsx("button", { type: "submit", className: "btn btn-sm btn-ghost", disabled: busy2fa, children: busy2fa ? "Working…" : "Confirm disable" })] })))
                            || (status.two_factor_available && !status.totp_enabled && setup && (_jsxs("form", { className: "settings-inline-form", onSubmit: enable2fa, children: [setup.qr_png_base64 && (_jsx("img", { className: "settings-qr", src: `data:image/png;base64,${setup.qr_png_base64}`, alt: "QR code for authenticator setup" })), _jsxs("p", { className: "settings-row__hint", children: ["Scan the QR, or enter secret ", _jsx("code", { children: setup.secret })] }), _jsx("input", { type: "text", className: "settings-row__control", placeholder: "Verification code", inputMode: "numeric", autoComplete: "one-time-code", value: totpCode, onChange: (e) => setTotpCode(e.target.value), required: true }), _jsx("button", { type: "submit", className: "btn btn-sm btn-ghost", disabled: busy2fa, children: busy2fa ? "Verifying…" : "Confirm" })] })))
                            || (backupCodes && backupCodes.length > 0 && (_jsxs("div", { className: "settings-backup-codes", children: [_jsx("h4", { children: "Backup codes (save now \u2014 shown once)" }), _jsx("ul", { children: backupCodes.map((code) => (_jsx("li", { children: _jsx("code", { children: code }) }, code))) })] })))
                            || null, children: !status.two_factor_available ? (_jsx("span", { className: "settings-row__value", children: "Unavailable" })) : status.totp_enabled ? (_jsx("button", { type: "button", className: "settings-row__action settings-row__action--danger", disabled: busy2fa, onClick: () => {
                                setDisableOpen((v) => !v);
                                setSetup(null);
                            }, children: disableOpen ? "Cancel" : "Disable" })) : setup ? (_jsx("button", { type: "button", className: "settings-row__action", disabled: busy2fa, onClick: () => setSetup(null), children: "Cancel" })) : (_jsx("button", { type: "button", className: "settings-row__action", disabled: busy2fa, onClick: () => void start2faSetup(), children: busy2fa ? "Preparing…" : "Enable" })) }), _jsx(SettingsRow, { title: "Password", hint: !status.password_change_available ? localOnlyHint : "Change your local password", detail: status.password_change_available && pwdOpen ? (_jsxs("form", { className: "settings-inline-form", onSubmit: onChangePassword, children: [_jsx("input", { type: "password", className: "settings-row__control", placeholder: "Current password", autoComplete: "current-password", value: currentPassword, onChange: (e) => setCurrentPassword(e.target.value), required: true }), _jsx("input", { type: "password", className: "settings-row__control", placeholder: "New password", autoComplete: "new-password", value: newPassword, onChange: (e) => setNewPassword(e.target.value), required: true }), _jsx("input", { type: "password", className: "settings-row__control", placeholder: "Confirm new password", autoComplete: "new-password", value: confirmPassword, onChange: (e) => setConfirmPassword(e.target.value), required: true }), _jsx("button", { type: "submit", className: "btn btn-sm btn-ghost", disabled: pwdSaving, children: pwdSaving ? "Updating…" : "Update" })] })) : null, children: !status.password_change_available ? (_jsx("span", { className: "settings-row__value", children: "Unavailable" })) : (_jsx("button", { type: "button", className: "settings-row__action", onClick: () => setPwdOpen((v) => !v), children: pwdOpen ? "Cancel" : "Change" })) })] }), error && _jsx("p", { className: "settings-error", children: error }), message && _jsx("p", { className: "settings-success", children: message })] }));
}
