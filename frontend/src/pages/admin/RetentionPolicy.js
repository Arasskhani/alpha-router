import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";
function humanSize(bytes) {
    let v = bytes || 0;
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v.toFixed(1)} ${units[i]}`;
}
function formatServerScheduleClock(hour, minute) {
    return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}
function serverTimezoneHint(tz) {
    const zone = tz?.trim() || "unknown";
    return `Server timezone: ${zone}. Scheduled cleanup hours and minutes on this page use this zone (set TZ on the server, e.g. TZ=America/New_York).`;
}
export default function RetentionPolicy() {
    const { confirm } = useConfirm();
    const [stats, setStats] = useState(null);
    const [savingMedia, setSavingMedia] = useState(false);
    const [savingChat, setSavingChat] = useState(false);
    const [flash, setFlash] = useState("");
    const [error, setError] = useState("");
    const [retentionDays, setRetentionDays] = useState(30);
    const [scheduleEnabled, setScheduleEnabled] = useState(true);
    const [scheduleHour, setScheduleHour] = useState(3);
    const [scheduleMinute, setScheduleMinute] = useState(0);
    const [chatRetentionEnabled, setChatRetentionEnabled] = useState(false);
    const [chatRetentionDays, setChatRetentionDays] = useState(180);
    const [chatScheduleEnabled, setChatScheduleEnabled] = useState(false);
    const [chatScheduleHour, setChatScheduleHour] = useState(4);
    const [chatScheduleMinute, setChatScheduleMinute] = useState(0);
    async function load() {
        setError("");
        try {
            const data = await api("/api/admin/storage");
            setStats(data);
            setRetentionDays(data.settings.retention_days);
            setScheduleEnabled(data.settings.clear_schedule_enabled);
            setScheduleHour(data.settings.clear_schedule_hour);
            setScheduleMinute(data.settings.clear_schedule_minute);
            const chat = data.chat?.settings;
            if (chat) {
                setChatRetentionEnabled(chat.retention_enabled);
                setChatRetentionDays(chat.retention_days);
                setChatScheduleEnabled(chat.clear_schedule_enabled);
                setChatScheduleHour(chat.clear_schedule_hour);
                setChatScheduleMinute(chat.clear_schedule_minute);
            }
        }
        catch (e) {
            setError(String(e));
        }
    }
    useEffect(() => {
        void load();
    }, []);
    async function saveMediaSettings(e) {
        e.preventDefault();
        setSavingMedia(true);
        setError("");
        setFlash("");
        try {
            await api("/api/admin/storage/settings", {
                method: "PATCH",
                body: JSON.stringify({
                    retention_days: retentionDays,
                    clear_schedule_enabled: scheduleEnabled,
                    clear_schedule_hour: scheduleHour,
                    clear_schedule_minute: scheduleMinute,
                }),
            });
            setFlash("Media retention settings updated.");
            await load();
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setSavingMedia(false);
        }
    }
    async function saveChatSettings(e) {
        e.preventDefault();
        setSavingChat(true);
        setError("");
        setFlash("");
        try {
            await api("/api/admin/storage/chat-settings", {
                method: "PATCH",
                body: JSON.stringify({
                    retention_enabled: chatRetentionEnabled,
                    retention_days: chatRetentionDays,
                    clear_schedule_enabled: chatScheduleEnabled,
                    clear_schedule_hour: chatScheduleHour,
                    clear_schedule_minute: chatScheduleMinute,
                }),
            });
            setFlash("Chat retention policy saved.");
            await load();
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setSavingChat(false);
        }
    }
    async function requestPurgeExpiredMedia() {
        const pending = stats?.expired_files ?? 0;
        const ok = await confirm({
            title: "Purge expired media",
            message: `This permanently deletes media files older than ${retentionDays} day${retentionDays === 1 ? "" : "s"} ` +
                "from object storage (attachments, generated images, voice notes, and other blobs). " +
                `${pending.toLocaleString()} file${pending === 1 ? "" : "s"} ${pending === 1 ? "is" : "are"} currently eligible. ` +
                "Users may see broken links in old chats until they upload again. This cannot be undone.",
            confirmLabel: "Purge expired media",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        await purgeExpiredMedia();
    }
    async function purgeExpiredMedia() {
        setError("");
        setFlash("");
        try {
            const res = await api("/api/admin/storage/purge-expired", { method: "POST" });
            setFlash(`Removed ${res.removed_files} expired media files.`);
            await load();
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function requestPurgeExpiredChat() {
        const pending = chatStats?.expired_messages ?? 0;
        const ok = await confirm({
            title: "Purge expired chat messages",
            message: `This permanently deletes chat messages older than ${chatRetentionDays} day${chatRetentionDays === 1 ? "" : "s"} ` +
                "for all users. " +
                `${pending.toLocaleString()} message${pending === 1 ? "" : "s"} ${pending === 1 ? "is" : "are"} currently eligible. ` +
                "Chats that lose all messages are removed from the sidebar. This cannot be undone.",
            confirmLabel: "Purge expired messages",
            cancelLabel: "Cancel",
            danger: true,
        });
        if (!ok)
            return;
        await purgeExpiredChat();
    }
    async function purgeExpiredChat() {
        setError("");
        setFlash("");
        try {
            const res = await api("/api/admin/storage/purge-expired-chat", {
                method: "POST",
            });
            setFlash(`Removed ${res.removed_messages} expired chat messages.`);
            await load();
        }
        catch (e) {
            setError(String(e));
        }
    }
    const chatStats = stats?.chat?.stats;
    const chatSettings = stats?.chat?.settings;
    const scheduleTz = chatSettings?.schedule_timezone;
    return (_jsxs(AdminPage, { title: "Retention Policy", children: [_jsxs("p", { className: "muted-text", style: { marginTop: "-0.25rem", marginBottom: "0.5rem" }, children: ["Media files and chat history retention for the platform. For usage and quotas see", " ", _jsx(Link, { to: "/admin/storage-management", children: "Storage Management" }), "."] }), _jsx("p", { className: "muted-text", style: { marginBottom: "1rem" }, children: serverTimezoneHint(scheduleTz) }), flash && _jsx("p", { className: "alert alert-success", children: flash }), error && _jsx("p", { className: "alert alert-error", children: error }), _jsxs("div", { className: "card", children: [_jsx("h3", { children: "Media & files \u2014 overview" }), _jsx("p", { className: "muted-text", children: stats
                            ? `${(stats.total_files ?? 0).toLocaleString()} files · ${humanSize(stats.total_size_bytes ?? 0)} in object storage`
                            : "Loading media statistics…" }), stats ? (_jsxs("p", { className: "muted-text", children: ["Files older than ", retentionDays, " day", retentionDays === 1 ? "" : "s", " pending cleanup:", " ", (stats.expired_files ?? 0).toLocaleString()] })) : null] }), _jsxs("form", { className: "card", onSubmit: saveMediaSettings, children: [_jsx("h3", { children: "Media & files \u2014 retention" }), _jsx("label", { children: "Keep files for (days)" }), _jsx("input", { type: "number", min: 1, className: "input-block", value: retentionDays, onChange: (e) => setRetentionDays(Number(e.target.value || 1)) }), _jsx("h3", { style: { marginTop: "1rem" }, children: "Scheduled cleanup" }), _jsxs("label", { className: "alpha-router-tool-row", style: { marginBottom: "0.65rem" }, children: [_jsx("span", { children: "Enable daily cleanup job" }), _jsx("button", { type: "button", className: `alpha-router-toggle${scheduleEnabled ? " on" : ""}`, onClick: () => setScheduleEnabled((v) => !v), "aria-pressed": scheduleEnabled, children: _jsx("span", { className: "alpha-router-toggle-knob" }) })] }), _jsxs("div", { style: { display: "flex", gap: "0.6rem", flexWrap: "wrap" }, children: [_jsxs("div", { style: { minWidth: 120 }, children: [_jsx("label", { children: "Hour" }), _jsx("input", { type: "number", min: 0, max: 23, className: "input-block", value: scheduleHour, onChange: (e) => setScheduleHour(Math.min(23, Math.max(0, Number(e.target.value || 0)))), disabled: !scheduleEnabled })] }), _jsxs("div", { style: { minWidth: 120 }, children: [_jsx("label", { children: "Minute" }), _jsx("input", { type: "number", min: 0, max: 59, className: "input-block", value: scheduleMinute, onChange: (e) => setScheduleMinute(Math.min(59, Math.max(0, Number(e.target.value || 0)))), disabled: !scheduleEnabled })] })] }), _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: savingMedia, children: savingMedia ? "Saving…" : "Save media settings" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void requestPurgeExpiredMedia(), children: "Purge expired media now" })] })] }), _jsxs("div", { className: "card", children: [_jsx("h3", { children: "Chat history \u2014 overview" }), _jsx("p", { className: "muted-text", children: chatStats
                            ? `${chatStats.total_sessions.toLocaleString()} sessions · ${chatStats.total_messages.toLocaleString()} messages in PostgreSQL`
                            : "Loading chat statistics…" }), chatStats && chatRetentionEnabled ? (_jsxs("p", { className: "muted-text", children: ["Messages older than ", chatRetentionDays, " days pending cleanup:", " ", chatStats.expired_messages.toLocaleString()] })) : null] }), _jsxs("form", { className: "card", onSubmit: saveChatSettings, children: [_jsx("h3", { children: "Chat history \u2014 retention" }), _jsxs("label", { className: "alpha-router-tool-row", style: { marginBottom: "0.65rem" }, children: [_jsx("span", { children: "Enable chat retention policy" }), _jsx("button", { type: "button", className: `alpha-router-toggle${chatRetentionEnabled ? " on" : ""}`, onClick: () => setChatRetentionEnabled((v) => !v), "aria-pressed": chatRetentionEnabled, children: _jsx("span", { className: "alpha-router-toggle-knob" }) })] }), _jsx("label", { children: "Keep chat messages for (days)" }), _jsx("input", { type: "number", min: 1, className: "input-block", value: chatRetentionDays, onChange: (e) => setChatRetentionDays(Number(e.target.value || 1)), disabled: !chatRetentionEnabled }), _jsx("h3", { style: { marginTop: "1rem" }, children: "Scheduled cleanup" }), _jsxs("label", { className: "alpha-router-tool-row", style: { marginBottom: "0.65rem" }, children: [_jsx("span", { children: "Enable daily message cleanup job" }), _jsx("button", { type: "button", className: `alpha-router-toggle${chatScheduleEnabled ? " on" : ""}`, onClick: () => setChatScheduleEnabled((v) => !v), "aria-pressed": chatScheduleEnabled, disabled: !chatRetentionEnabled, children: _jsx("span", { className: "alpha-router-toggle-knob" }) })] }), _jsxs("div", { style: { display: "flex", gap: "0.6rem", flexWrap: "wrap" }, children: [_jsxs("div", { style: { minWidth: 120 }, children: [_jsx("label", { children: "Hour" }), _jsx("input", { type: "number", min: 0, max: 23, className: "input-block", value: chatScheduleHour, onChange: (e) => setChatScheduleHour(Math.min(23, Math.max(0, Number(e.target.value || 0)))), disabled: !chatRetentionEnabled || !chatScheduleEnabled })] }), _jsxs("div", { style: { minWidth: 120 }, children: [_jsx("label", { children: "Minute" }), _jsx("input", { type: "number", min: 0, max: 59, className: "input-block", value: chatScheduleMinute, onChange: (e) => setChatScheduleMinute(Math.min(59, Math.max(0, Number(e.target.value || 0)))), disabled: !chatRetentionEnabled || !chatScheduleEnabled })] })] }), chatSettings?.cleanup_active ? (_jsxs("p", { className: "muted-text", style: { marginTop: "0.75rem" }, children: ["Automated cleanup is active. Messages older than ", chatRetentionDays, " days are removed daily at", " ", formatServerScheduleClock(chatScheduleHour, chatScheduleMinute), " (", scheduleTz || "server timezone", ")."] })) : chatRetentionEnabled ? (_jsx("p", { className: "muted-text", style: { marginTop: "0.75rem" }, children: "Retention policy is saved. Enable the scheduled cleanup job to delete expired messages automatically." })) : null, _jsxs("div", { className: "dialog-actions", children: [_jsx("button", { type: "submit", className: "btn", disabled: savingChat, children: savingChat ? "Saving…" : "Save chat policy" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void requestPurgeExpiredChat(), disabled: !chatRetentionEnabled, children: "Purge expired messages now" })] })] })] }));
}
