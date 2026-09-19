import { Link } from "react-router-dom";
import { FormEvent, useEffect, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";

type MediaSettings = {
  retention_days: number;
  clear_schedule_enabled: boolean;
  clear_schedule_hour: number;
  clear_schedule_minute: number;
};

type ChatSettings = {
  retention_enabled: boolean;
  retention_days: number;
  clear_schedule_enabled: boolean;
  clear_schedule_hour: number;
  clear_schedule_minute: number;
  cleanup_active: boolean;
  schedule_timezone?: string;
};

type RetentionOverview = {
  total_files?: number;
  total_size_bytes?: number;
  expired_files?: number;
  settings: MediaSettings;
  chat?: {
    stats: { total_sessions: number; total_messages: number; expired_messages: number };
    settings: ChatSettings;
  };
  api_logs?: ApiLogRetention;
  admin_logs?: AdminLogRetention;
};

type AdminLogRetention = {
  detail_retention_days: number;
  event_retention_days: number;
  min_days: number;
  max_days: number;
  default_detail_days: number;
  default_event_days: number;
  stored_events: number;
  expiring_details: number;
  expiring_events: number;
};

type ApiLogRetention = {
  retention_days: number;
  min_days: number;
  max_days: number;
  default_days: number;
  stored_events: number;
  expired_events: number;
  stored_video_jobs: number;
  expired_video_jobs: number;
};

function humanSize(bytes: number) {
  let v = bytes || 0;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

function formatServerScheduleClock(hour: number, minute: number): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function serverTimezoneHint(tz?: string): string {
  const zone = tz?.trim() || "unknown";
  return `Server timezone: ${zone}. Scheduled cleanup hours and minutes on this page use this zone (set TZ on the server, e.g. TZ=America/New_York).`;
}

export default function RetentionPolicy() {
  const { confirm } = useConfirm();
  const [stats, setStats] = useState<RetentionOverview | null>(null);
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
  const [savingApiLogs, setSavingApiLogs] = useState(false);
  const [adminLogDetailDays, setAdminLogDetailDays] = useState(90);
  const [adminLogEventDays, setAdminLogEventDays] = useState(365);
  const [savingAdminLogs, setSavingAdminLogs] = useState(false);
  const [apiLogRetentionDays, setApiLogRetentionDays] = useState(30);

  async function load() {
    setError("");
    try {
      const data = await api<RetentionOverview>("/api/admin/storage");
      setStats(data);
      setRetentionDays(data.settings.retention_days);
      setScheduleEnabled(data.settings.clear_schedule_enabled);
      setScheduleHour(data.settings.clear_schedule_hour);
      setScheduleMinute(data.settings.clear_schedule_minute);
      if (data.api_logs) setApiLogRetentionDays(data.api_logs.retention_days);
      if (data.admin_logs) {
        setAdminLogDetailDays(data.admin_logs.detail_retention_days);
        setAdminLogEventDays(data.admin_logs.event_retention_days);
      }
      const chat = data.chat?.settings;
      if (chat) {
        setChatRetentionEnabled(chat.retention_enabled);
        setChatRetentionDays(chat.retention_days);
        setChatScheduleEnabled(chat.clear_schedule_enabled);
        setChatScheduleHour(chat.clear_schedule_hour);
        setChatScheduleMinute(chat.clear_schedule_minute);
      }
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function saveMediaSettings(e: FormEvent) {
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
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingMedia(false);
    }
  }

  async function saveApiLogSettings(e: FormEvent) {
    e.preventDefault();
    setSavingApiLogs(true);
    setError("");
    setFlash("");
    try {
      const result = await api<{ purged?: { usage_events_cleared: number; video_jobs_cleared: number } }>(
        "/api/admin/storage/api-log-settings",
        {
          method: "PATCH",
          body: JSON.stringify({ retention_days: apiLogRetentionDays }),
        },
      );
      const cleared = (result.purged?.usage_events_cleared ?? 0) + (result.purged?.video_jobs_cleared ?? 0);
      setFlash(
        cleared > 0
          ? `Provider response retention updated. ${cleared.toLocaleString()} stored response(s) outside the new window were cleared.`
          : "Provider response retention updated.",
      );
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingApiLogs(false);
    }
  }

  async function saveAdminLogSettings(e: FormEvent) {
    e.preventDefault();
    setSavingAdminLogs(true);
    setError("");
    setFlash("");
    try {
      await api("/api/admin/storage/admin-log-settings", {
        method: "PATCH",
        body: JSON.stringify({
          detail_retention_days: adminLogDetailDays,
          event_retention_days: adminLogEventDays,
        }),
      });
      setFlash("Admin log retention updated. The nightly job applies it.");
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingAdminLogs(false);
    }
  }

  async function saveChatSettings(e: FormEvent) {
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
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingChat(false);
    }
  }

  async function requestPurgeExpiredMedia() {
    const pending = stats?.expired_files ?? 0;
    const ok = await confirm({
      title: "Purge expired media",
      message:
        `This permanently deletes media files older than ${retentionDays} day${retentionDays === 1 ? "" : "s"} ` +
        "from object storage (attachments, generated images, voice notes, and other blobs). " +
        `${pending.toLocaleString()} file${pending === 1 ? "" : "s"} ${pending === 1 ? "is" : "are"} currently eligible. ` +
        "Users may see broken links in old chats until they upload again. This cannot be undone.",
      confirmLabel: "Purge expired media",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    await purgeExpiredMedia();
  }

  async function purgeExpiredMedia() {
    setError("");
    setFlash("");
    try {
      const res = await api<{ removed_files: number }>("/api/admin/storage/purge-expired", { method: "POST" });
      setFlash(`Removed ${res.removed_files} expired media files.`);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function requestPurgeExpiredChat() {
    const pending = chatStats?.expired_messages ?? 0;
    const ok = await confirm({
      title: "Purge expired chat messages",
      message:
        `This permanently deletes chat messages older than ${chatRetentionDays} day${chatRetentionDays === 1 ? "" : "s"} ` +
        "for all users. " +
        `${pending.toLocaleString()} message${pending === 1 ? "" : "s"} ${pending === 1 ? "is" : "are"} currently eligible. ` +
        "Chats that lose all messages are removed from the sidebar. This cannot be undone.",
      confirmLabel: "Purge expired messages",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!ok) return;
    await purgeExpiredChat();
  }

  async function purgeExpiredChat() {
    setError("");
    setFlash("");
    try {
      const res = await api<{ removed_messages: number }>("/api/admin/storage/purge-expired-chat", {
        method: "POST",
      });
      setFlash(`Removed ${res.removed_messages} expired chat messages.`);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  const chatStats = stats?.chat?.stats;
  const chatSettings = stats?.chat?.settings;
  const scheduleTz = chatSettings?.schedule_timezone;

  return (
    <AdminPage title="Retention Policy">
      <p className="muted-text" style={{ marginTop: "-0.25rem", marginBottom: "0.5rem" }}>
        Media files and chat history retention for the platform. For usage and quotas see{" "}
        <Link to="/admin/storage-management">Storage Management</Link>.
      </p>
      <p className="muted-text" style={{ marginBottom: "1rem" }}>
        {serverTimezoneHint(scheduleTz)}
      </p>
      {flash && <p className="alert alert-success">{flash}</p>}
      {error && <p className="alert alert-error">{error}</p>}

      <div className="card">
        <h3>Media &amp; files — overview</h3>
        <p className="muted-text">
          {stats
            ? `${(stats.total_files ?? 0).toLocaleString()} files · ${humanSize(stats.total_size_bytes ?? 0)} in object storage`
            : "Loading media statistics…"}
        </p>
        {stats ? (
          <p className="muted-text">
            Files older than {retentionDays} day{retentionDays === 1 ? "" : "s"} pending cleanup:{" "}
            {(stats.expired_files ?? 0).toLocaleString()}
          </p>
        ) : null}
      </div>

      <form className="card" onSubmit={saveMediaSettings}>
        <h3>Media &amp; files — retention</h3>
        <label htmlFor="retention-policy-keep-files-for-days">Keep files for (days)</label>
        <input id="retention-policy-keep-files-for-days"
          type="number"
          min={1}
          className="input-block"
          value={retentionDays}
          onChange={(e) => setRetentionDays(Number(e.target.value || 1))}
        />
        <h3 style={{ marginTop: "1rem" }}>Scheduled cleanup</h3>
        <div className="alpha-router-tool-row" style={{ marginBottom: "0.65rem" }}>
          <span>Enable daily cleanup job</span>
          <button
            aria-label="Enable daily cleanup job"
            type="button"
            className={`alpha-router-toggle${scheduleEnabled ? " on" : ""}`}
            onClick={() => setScheduleEnabled((v) => !v)}
            aria-pressed={scheduleEnabled}
          >
            <span className="alpha-router-toggle-knob" />
          </button>
        </div>
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <div style={{ minWidth: 120 }}>
            <label htmlFor="retention-policy-hour">Hour</label>
            <input id="retention-policy-hour"
              type="number"
              min={0}
              max={23}
              className="input-block"
              value={scheduleHour}
              onChange={(e) => setScheduleHour(Math.min(23, Math.max(0, Number(e.target.value || 0))))}
              disabled={!scheduleEnabled}
            />
          </div>
          <div style={{ minWidth: 120 }}>
            <label htmlFor="retention-policy-minute">Minute</label>
            <input id="retention-policy-minute"
              type="number"
              min={0}
              max={59}
              className="input-block"
              value={scheduleMinute}
              onChange={(e) => setScheduleMinute(Math.min(59, Math.max(0, Number(e.target.value || 0))))}
              disabled={!scheduleEnabled}
            />
          </div>
        </div>
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={savingMedia}>
            {savingMedia ? "Saving…" : "Save media settings"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void requestPurgeExpiredMedia()}>
            Purge expired media now
          </button>
        </div>
      </form>

      <div className="card">
        <h3>Chat history — overview</h3>
        <p className="muted-text">
          {chatStats
            ? `${chatStats.total_sessions.toLocaleString()} sessions · ${chatStats.total_messages.toLocaleString()} messages in PostgreSQL`
            : "Loading chat statistics…"}
        </p>
        {chatStats && chatRetentionEnabled ? (
          <p className="muted-text">
            Messages older than {chatRetentionDays} days pending cleanup:{" "}
            {chatStats.expired_messages.toLocaleString()}
          </p>
        ) : null}
      </div>

      <form className="card" onSubmit={saveChatSettings}>
        <h3>Chat history — retention</h3>
        <div className="alpha-router-tool-row" style={{ marginBottom: "0.65rem" }}>
          <span>Enable chat retention policy</span>
          <button
            aria-label="Enable chat retention policy"
            type="button"
            className={`alpha-router-toggle${chatRetentionEnabled ? " on" : ""}`}
            onClick={() => setChatRetentionEnabled((v) => !v)}
            aria-pressed={chatRetentionEnabled}
          >
            <span className="alpha-router-toggle-knob" />
          </button>
        </div>
        <label htmlFor="retention-policy-keep-chat-messages-for-days">Keep chat messages for (days)</label>
        <input id="retention-policy-keep-chat-messages-for-days"
          type="number"
          min={1}
          className="input-block"
          value={chatRetentionDays}
          onChange={(e) => setChatRetentionDays(Number(e.target.value || 1))}
          disabled={!chatRetentionEnabled}
        />
        <h3 style={{ marginTop: "1rem" }}>Scheduled cleanup</h3>
        <div className="alpha-router-tool-row" style={{ marginBottom: "0.65rem" }}>
          <span>Enable daily message cleanup job</span>
          <button
            aria-label="Enable daily message cleanup job"
            type="button"
            className={`alpha-router-toggle${chatScheduleEnabled ? " on" : ""}`}
            onClick={() => setChatScheduleEnabled((v) => !v)}
            aria-pressed={chatScheduleEnabled}
            disabled={!chatRetentionEnabled}
          >
            <span className="alpha-router-toggle-knob" />
          </button>
        </div>
        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <div style={{ minWidth: 120 }}>
            <label htmlFor="retention-policy-hour-2">Hour</label>
            <input id="retention-policy-hour-2"
              type="number"
              min={0}
              max={23}
              className="input-block"
              value={chatScheduleHour}
              onChange={(e) => setChatScheduleHour(Math.min(23, Math.max(0, Number(e.target.value || 0))))}
              disabled={!chatRetentionEnabled || !chatScheduleEnabled}
            />
          </div>
          <div style={{ minWidth: 120 }}>
            <label htmlFor="retention-policy-minute-2">Minute</label>
            <input id="retention-policy-minute-2"
              type="number"
              min={0}
              max={59}
              className="input-block"
              value={chatScheduleMinute}
              onChange={(e) => setChatScheduleMinute(Math.min(59, Math.max(0, Number(e.target.value || 0))))}
              disabled={!chatRetentionEnabled || !chatScheduleEnabled}
            />
          </div>
        </div>
        {chatSettings?.cleanup_active ? (
          <p className="muted-text" style={{ marginTop: "0.75rem" }}>
            Automated cleanup is active. Messages older than {chatRetentionDays} days are removed daily at{" "}
            {formatServerScheduleClock(chatScheduleHour, chatScheduleMinute)} ({scheduleTz || "server timezone"}).
          </p>
        ) : chatRetentionEnabled ? (
          <p className="muted-text" style={{ marginTop: "0.75rem" }}>
            Retention policy is saved. Enable the scheduled cleanup job to delete expired messages automatically.
          </p>
        ) : null}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={savingChat}>
            {savingChat ? "Saving…" : "Save chat policy"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => void requestPurgeExpiredChat()}
            disabled={!chatRetentionEnabled}
          >
            Purge expired messages now
          </button>
        </div>
      </form>

      <div className="card">
        <h3>API logs — overview</h3>
        <p className="muted-text">
          {stats?.api_logs
            ? `${stats.api_logs.stored_events.toLocaleString()} upstream attempts and ${stats.api_logs.stored_video_jobs.toLocaleString()} media jobs hold a stored provider response`
            : "Loading API log statistics…"}
        </p>
        {stats?.api_logs && stats.api_logs.expired_events + stats.api_logs.expired_video_jobs > 0 ? (
          <p className="muted-text">
            Responses older than {stats.api_logs.retention_days} days pending cleanup:{" "}
            {(stats.api_logs.expired_events + stats.api_logs.expired_video_jobs).toLocaleString()}
          </p>
        ) : null}
      </div>

      <form className="card" onSubmit={saveApiLogSettings}>
        <h3>API logs — raw provider responses</h3>
        <p className="muted-text" style={{ marginTop: 0 }}>
          Every upstream attempt behind{" "}
          <Link to="/admin/logs">API Logs</Link> stores the provider&apos;s own response, which is what explains a
          failed request. It is also the bulkiest part of the log and can contain prompt text the provider echoed back,
          so it is kept only for the window you set here. The requests themselves — cost, tokens, status and the failure
          reason — are unaffected.
        </p>
        <label htmlFor="api-log-retention-days">Keep raw provider responses for (days)</label>
        <input
          id="api-log-retention-days"
          type="number"
          min={stats?.api_logs?.min_days ?? 1}
          max={stats?.api_logs?.max_days ?? 365}
          className="input-block"
          value={apiLogRetentionDays}
          onChange={(e) => setApiLogRetentionDays(Number(e.target.value || 1))}
        />
        {stats?.api_logs && apiLogRetentionDays < stats.api_logs.retention_days ? (
          <p className="muted-text" style={{ marginTop: "0.75rem" }}>
            Saving a shorter window clears what falls outside it straight away.
          </p>
        ) : (
          <p className="muted-text" style={{ marginTop: "0.75rem" }}>
            A daily job clears responses past this window; saving also applies it immediately.
          </p>
        )}
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={savingApiLogs}>
            {savingApiLogs ? "Saving…" : "Save API log policy"}
          </button>
        </div>
      </form>

      <form className="card" onSubmit={saveAdminLogSettings}>
        <h3>Admin logs — administrative audit trail</h3>
        <p className="muted-text" style={{ marginTop: 0 }}>
          The events behind <Link to="/admin/admin-logs">Admin Logs</Link>: who changed what, from where. An
          event has two halves. Who did what and when is a few short columns and is the part an audit asks
          for; the recorded detail is unbounded and is what makes an old event useful rather than merely
          countable. So the detail is cleared first, and the event itself is kept for longer.
        </p>
        <label htmlFor="admin-log-detail-days">Keep event detail for (days)</label>
        <input
          id="admin-log-detail-days"
          type="number"
          min={stats?.admin_logs?.min_days ?? 7}
          max={stats?.admin_logs?.max_days ?? 3650}
          className="input-block"
          value={adminLogDetailDays}
          onChange={(e) => setAdminLogDetailDays(Number(e.target.value || 7))}
        />
        <label htmlFor="admin-log-event-days">Keep events for (days)</label>
        <input
          id="admin-log-event-days"
          type="number"
          min={stats?.admin_logs?.min_days ?? 7}
          max={stats?.admin_logs?.max_days ?? 3650}
          className="input-block"
          value={adminLogEventDays}
          onChange={(e) => setAdminLogEventDays(Number(e.target.value || 7))}
        />
        {adminLogDetailDays > adminLogEventDays ? (
          <p className="alert alert-warning">
            Detail cannot outlive the event it belongs to; it will be saved as {adminLogEventDays} days.
          </p>
        ) : null}
        {stats?.admin_logs ? (
          <p className="muted-text" style={{ marginTop: "0.75rem" }}>
            {stats.admin_logs.stored_events.toLocaleString()} event(s) stored. The next nightly run will clear
            detail on {stats.admin_logs.expiring_details.toLocaleString()} and delete{" "}
            {stats.admin_logs.expiring_events.toLocaleString()}.
          </p>
        ) : null}
        <p className="muted-text">
          Saving does not purge immediately. Shortening a window here destroys audit evidence, so it is left to
          the nightly job rather than happening as a side effect of saving. Changing these windows is itself
          recorded in the trail.
        </p>
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={savingAdminLogs}>
            {savingAdminLogs ? "Saving…" : "Save admin log policy"}
          </button>
        </div>
      </form>
    </AdminPage>
  );
}
