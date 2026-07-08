import { FormEvent, useEffect, useMemo, useState } from "react";
import AdminPage from "../../components/AdminPage";
import { api } from "../../api";
import { useConfirm } from "../../context/ConfirmContext";

type StorageSettings = {
  user_media_quota_gb?: number;
  user_media_quota_bytes?: number;
};

type StorageOverview = {
  total_files: number;
  total_size_bytes: number;
  expired_files: number;
  settings: StorageSettings;
  users_over_quota?: number;
  by_kind?: Array<{ kind: string; count: number; size_bytes: number }>;
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

export default function StorageManagement() {
  const { confirm } = useConfirm();
  const [stats, setStats] = useState<StorageOverview | null>(null);
  const [quotaGb, setQuotaGb] = useState(1);
  const [savingQuota, setSavingQuota] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const data = await api<StorageOverview>("/api/admin/storage");
      setStats(data);
      const gb = data.settings?.user_media_quota_gb;
      if (typeof gb === "number" && gb >= 1) setQuotaGb(gb);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const usagePercent = useMemo(() => {
    const bytes = stats?.total_size_bytes || 0;
    const perUser = stats?.settings?.user_media_quota_bytes || 1024 * 1024 * 1024;
    const vizCap = Math.max(perUser * 20, bytes, 5 * 1024 * 1024 * 1024);
    return Math.min(100, Math.round((bytes / vizCap) * 100));
  }, [stats]);

  async function saveQuotaSettings(e: FormEvent) {
    e.preventDefault();
    const nextGb = Math.max(1, Math.min(100, Math.round(Number(quotaGb) || 1)));
    const currentGb = stats?.settings?.user_media_quota_gb ?? 1;
    if (nextGb < currentGb && (stats?.users_over_quota ?? 0) > 0) {
      const ok = await confirm({
        title: "Lower storage quota?",
        message:
          `${stats?.users_over_quota ?? 0} user(s) already use more than ${nextGb} GB. ` +
          "They will not be able to upload new files until they free space. Existing files are not deleted. Continue?",
        confirmLabel: "Apply lower quota",
        cancelLabel: "Cancel",
        danger: true,
      });
      if (!ok) return;
    }
    setSavingQuota(true);
    setError("");
    setFlash("");
    try {
      await api("/api/admin/storage/settings", {
        method: "PATCH",
        body: JSON.stringify({ user_media_quota_gb: nextGb }),
      });
      setFlash(`Per-user media quota set to ${nextGb} GB for all users.`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingQuota(false);
    }
  }

  async function requestClearCache() {
    const fileCount = stats?.total_files ?? 0;
    const sizeLabel = humanSize(stats?.total_size_bytes ?? 0);

    const step1 = await confirm({
      title: "Clear all media — step 1 of 3",
      message:
        "This action permanently deletes every media file in object storage for all users " +
        `(currently ${fileCount.toLocaleString()} files, ${sizeLabel}). Chat message text is not removed. Continue?`,
      confirmLabel: "Continue",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!step1) return;

    const step2 = await confirm({
      title: "Clear all media — step 2 of 3",
      message:
        "Attachments, generated images, voice notes, and other blobs will be removed from storage. " +
        "Users may see broken links in old chats until they upload again. This cannot be undone. Proceed?",
      confirmLabel: "I understand — continue",
      cancelLabel: "Stop",
      danger: true,
    });
    if (!step2) return;

    const step3 = await confirm({
      title: "Clear all media — final confirmation",
      message:
        `Final step: delete all ${fileCount.toLocaleString()} files (${sizeLabel}) from storage now. ` +
        "There is no backup step inside Alpha Router. Confirm only if you are certain.",
      confirmLabel: "Delete all media now",
      cancelLabel: "Cancel",
      danger: true,
    });
    if (!step3) return;

    setClearing(true);
    setError("");
    setFlash("");
    try {
      const res = await api<{ removed_files: number }>("/api/admin/storage/clear-cache", { method: "POST" });
      setFlash(`All media deleted. Removed ${res.removed_files} files.`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setClearing(false);
    }
  }

  return (
    <AdminPage title="Storage Management">
      <p className="muted-text" style={{ marginTop: "-0.25rem", marginBottom: "1rem" }}>
        Platform media usage and per-user storage limits.
      </p>
      {flash && <p className="alert alert-success">{flash}</p>}
      {error && <p className="alert alert-error">{error}</p>}

      <div className="card">
        <h3>Media &amp; files — usage</h3>
        <p className="muted-text">Total media stored in object storage across all users.</p>
        <div className="storage-usage-bar">
          <div className="storage-usage-fill" style={{ width: `${usagePercent}%` }} />
        </div>
        <p style={{ marginTop: "0.4rem" }}>
          <strong>{humanSize(stats?.total_size_bytes || 0)}</strong> used by {stats?.total_files || 0} files
        </p>
        <p className="muted-text">Expired files pending cleanup: {stats?.expired_files || 0}</p>
        {!!stats?.by_kind?.length && (
          <div className="table-wrap" style={{ marginTop: "0.8rem" }}>
            <table className="card data-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Count</th>
                  <th>Size</th>
                </tr>
              </thead>
              <tbody>
                {stats.by_kind.map((row) => (
                  <tr key={row.kind}>
                    <td>{row.kind}</td>
                    <td>{row.count}</td>
                    <td>{humanSize(row.size_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="dialog-actions" style={{ marginTop: "0.8rem" }}>
          <button type="button" className="btn btn-ghost btn-readonly-ok" onClick={() => void load()}>
            Refresh
          </button>
          <button
            type="button"
            className="btn btn-danger dialog-actions-end"
            onClick={() => void requestClearCache()}
            disabled={clearing}
          >
            {clearing ? "Deleting…" : "DELETE ALL MEDIA"}
          </button>
        </div>
      </div>

      <form className="card" onSubmit={saveQuotaSettings}>
        <h3>Per-user storage quota</h3>
        <p className="muted-text">
          Maximum media library size for every user. Applies globally — changing this updates the limit for all accounts.
        </p>
        <label htmlFor="user-media-quota-gb">Storage per user (GB)</label>
        <input
          id="user-media-quota-gb"
          type="number"
          min={1}
          max={100}
          step={1}
          className="input-block"
          value={quotaGb}
          onChange={(e) => setQuotaGb(Number(e.target.value || 1))}
        />
        <p className="muted-text" style={{ marginTop: "0.5rem" }}>
          Current: {stats?.settings?.user_media_quota_gb ?? 1} GB per user
          {(stats?.users_over_quota ?? 0) > 0
            ? ` · ${stats?.users_over_quota} user(s) over the current limit`
            : ""}
        </p>
        <div className="dialog-actions">
          <button type="submit" className="btn" disabled={savingQuota}>
            {savingQuota ? "Saving…" : "Save quota"}
          </button>
        </div>
      </form>
    </AdminPage>
  );
}
