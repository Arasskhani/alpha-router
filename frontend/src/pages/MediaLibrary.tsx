import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, authFetch } from "../api";
import AdminPage from "../components/AdminPage";
import AuthenticatedImage from "../components/AuthenticatedImage";
import AuthenticatedVideo from "../components/AuthenticatedVideo";
import FilterPanel, { countActiveFilters } from "../components/FilterPanel";
import RowActionsMenu, { type RowAction } from "../components/RowActionsMenu";
import { useConfirm } from "../context/ConfirmContext";
import { useReadOnly } from "../context/ReadOnlyContext";
import { usePhoneLayout } from "../hooks/useMediaQuery";
import {
  fetchAuthenticatedMediaBlob,
  fetchAuthenticatedMediaObjectUrl,
  isAlphaRouterMediaFileUrl,
} from "../lib/mediaUrl";
import { openSafeUrlInNewTab, safeBrowserUrl } from "../lib/browserUrlPolicy";
import MediaViewerModal from "../components/MediaViewerModal";
import {
  dedupeMediaItemsForDisplay,
  formatMediaBytes,
  formatMediaDate,
  formatMediaQuotaLabel,
  loadMediaViewMode,
  MEDIA_VIEW_OPTIONS,
  type MediaItem,
  type MediaQuota,
  type MediaSchedule,
  type MediaViewMode,
  saveMediaViewMode,
} from "../lib/mediaLibrary";
import { isSlideshowMediaKind, slideshowItemsFromMedia } from "../lib/mediaViewer";

type MediaLibraryProps = {
  /** When set, admin views/manages this user's media library. */
  adminUserId?: number;
  backLink?: { to: string; label: string };
};

function buildQuery(search: string, fromDate: string, toDate: string) {
  const q = new URLSearchParams();
  q.set("limit", "1000");
  if (search.trim()) q.set("q", search.trim());
  if (fromDate) q.set("from_date", fromDate);
  if (toDate) q.set("to_date", toDate);
  return q.toString();
}

export default function MediaLibrary({ adminUserId, backLink }: MediaLibraryProps = {}) {
  const readOnly = useReadOnly();
  const phone = usePhoneLayout();
  const isAdminScope = adminUserId != null && Number.isFinite(adminUserId);
  const apiBase = isAdminScope ? `/api/admin/users/${adminUserId}/media` : "/api/user/media";
  const { confirm } = useConfirm();
  const [subjectName, setSubjectName] = useState("");
  const [items, setItems] = useState<MediaItem[]>([]);
  const [total, setTotal] = useState(0);
  const [quota, setQuota] = useState<MediaQuota | null>(null);
  const [schedule, setSchedule] = useState<MediaSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [search, setSearch] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [viewMode, setViewMode] = useState<MediaViewMode>(() => loadMediaViewMode());
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [retentionDays, setRetentionDays] = useState(30);
  const [cleanupEnabled, setCleanupEnabled] = useState(false);
  const [cleanupHour, setCleanupHour] = useState(3);
  const [cleanupMinute, setCleanupMinute] = useState(0);
  const [downloadingZip, setDownloadingZip] = useState(false);
  const [viewerId, setViewerId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const qs = buildQuery(search, fromDate, toDate);
      const [listRes, quotaRes, scheduleRes] = await Promise.all([
        api<{ items: MediaItem[]; total: number; username?: string; display_name?: string }>(
          `${apiBase}?${qs}`,
        ),
        api<MediaQuota & { username?: string; display_name?: string }>(`${apiBase}/quota`),
        api<MediaSchedule>(`${apiBase}/schedule`),
      ]);
      setItems(listRes.items);
      setTotal(listRes.total);
      if (isAdminScope) {
        const label =
          listRes.display_name?.trim() ||
          quotaRes.display_name?.trim() ||
          listRes.username ||
          quotaRes.username ||
          "";
        if (label) setSubjectName(label);
      }
      setQuota(quotaRes);
      setSchedule(scheduleRes);
      setRetentionDays(scheduleRes.cleanup_retention_days);
      setCleanupEnabled(scheduleRes.cleanup_enabled);
      setCleanupHour(scheduleRes.cleanup_hour);
      setCleanupMinute(scheduleRes.cleanup_minute);
      setSelected(new Set());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [search, fromDate, toDate, apiBase, isAdminScope]);

  useEffect(() => {
    void load();
  }, [load]);

  const displayItems = useMemo(() => dedupeMediaItemsForDisplay(items), [items]);
  const slideshowItems = useMemo(() => slideshowItemsFromMedia(displayItems), [displayItems]);
  const viewerIndex = useMemo(() => {
    if (!viewerId) return null;
    const next = slideshowItems.findIndex((entry) => entry.id === viewerId);
    return next >= 0 ? next : null;
  }, [viewerId, slideshowItems]);

  useEffect(() => {
    if (viewerId && viewerIndex == null) setViewerId(null);
  }, [viewerId, viewerIndex]);

  const allSelected = displayItems.length > 0 && displayItems.every((m) => selected.has(m.id));
  const someSelected = selected.size > 0;

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(displayItems.map((m) => m.id)));
  }

  function changeView(mode: MediaViewMode) {
    setViewMode(mode);
    saveMediaViewMode(mode);
  }

  async function deleteIds(ids: number[]) {
    if (!ids.length || readOnly) return;
    const ok = await confirm({
      title: "Delete media",
      message: `Delete ${ids.length} file${ids.length === 1 ? "" : "s"}? This cannot be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setError("");
    try {
      await api(`${apiBase}/bulk-delete`, {
        method: "POST",
        body: JSON.stringify({ ids }),
      });
      setFlash(`Removed ${ids.length} file(s).`);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function deleteAll() {
    if (readOnly || !items.length) return;
    const ok = await confirm({
      title: "Delete all media",
      message: isAdminScope
        ? `Remove every media file for ${subjectName || "this user"}?`
        : "Remove every media file in your library? This only affects your account.",
      confirmLabel: "Delete all",
      danger: true,
    });
    if (!ok) return;
    try {
      const res = await api<{ removed: number }>(`${apiBase}/all`, { method: "DELETE" });
      setFlash(`Removed ${res.removed} file(s).`);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function saveSchedule(e: FormEvent) {
    e.preventDefault();
    if (readOnly) return;
    setSavingSchedule(true);
    setError("");
    try {
      await api(`${apiBase}/schedule`, {
        method: "PATCH",
        body: JSON.stringify({
          cleanup_enabled: cleanupEnabled,
          cleanup_retention_days: retentionDays,
          cleanup_hour: cleanupHour,
          cleanup_minute: cleanupMinute,
        }),
      });
      setFlash("Cleanup schedule saved.");
      setScheduleOpen(false);
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingSchedule(false);
    }
  }

  async function downloadOne(item: MediaItem) {
    const trigger = (href: string, name: string) => {
      const safeHref = safeBrowserUrl(href, "download");
      if (!safeHref) throw new Error("Blocked unsafe media URL.");
      const a = document.createElement("a");
      a.href = safeHref;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    };
    try {
      if (isAlphaRouterMediaFileUrl(item.url)) {
        const blob = await fetchAuthenticatedMediaBlob(item.url);
        const blobUrl = URL.createObjectURL(blob);
        trigger(blobUrl, item.file_name);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }
      trigger(item.url, item.file_name);
    } catch (e) {
      setError(String(e));
    }
  }

  async function downloadAsZip(targets: MediaItem[]) {
    if (!targets.length) return;
    setDownloadingZip(true);
    setError("");
    try {
      const res = await authFetch(`${apiBase}/download-zip`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ids: targets.map((m) => m.id) }),
      });
      if (!res.ok) {
        const text = await res.text();
        let detail = text || `Download failed (${res.status})`;
        try {
          const j = JSON.parse(text) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* plain-text body (e.g. uvicorn 500) */
        }
        throw new Error(detail);
      }
      const blob = await res.blob();
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `alpha-router-media-${stamp}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
      setFlash(`Downloaded ${targets.length} file(s) as ZIP.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setDownloadingZip(false);
    }
  }

  async function downloadSelected(allFiltered = false) {
    const targets = allFiltered ? displayItems : displayItems.filter((m) => selected.has(m.id));
    if (!targets.length) return;
    if (allFiltered || targets.length > 1) {
      await downloadAsZip(targets);
      return;
    }
    await downloadOne(targets[0]);
    setFlash("Downloaded 1 file.");
  }

  function openItem(item: MediaItem) {
    if (isSlideshowMediaKind(item.kind)) {
      const nextId = `media-${item.id}`;
      if (slideshowItems.some((entry) => entry.id === nextId)) {
        setViewerId(nextId);
        return;
      }
    }
    void openFull(item);
  }

  async function openFull(item: MediaItem) {
    try {
      if (isAlphaRouterMediaFileUrl(item.url)) {
        const blobUrl = await fetchAuthenticatedMediaObjectUrl(item.url);
        if (!openSafeUrlInNewTab(blobUrl, item.kind === "image" ? "image" : "media")) {
          throw new Error("Blocked unsafe media URL.");
        }
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }
      if (!openSafeUrlInNewTab(item.url, item.kind === "image" ? "image" : "media")) {
        throw new Error("Blocked unsafe media URL.");
      }
    } catch (e) {
      setError(String(e));
    }
  }

  const usagePercent = useMemo(() => {
    if (!quota) return 0;
    return Math.min(100, quota.used_percent);
  }, [quota]);

  // On a phone the five bulk actions are one action sheet instead of three
  // rows of buttons. Read-only has only the two downloads: they stay buttons
  // (the menu is locked in read-only, and downloads must not be).
  const bulkActions: RowAction[] = [
    {
      label: "Download selected",
      onClick: () => downloadSelected(false),
      disabled: !someSelected || downloadingZip,
    },
    {
      label: "Download all (filtered)",
      onClick: () => downloadSelected(true),
      disabled: !displayItems.length || downloadingZip,
    },
    { label: "Delete selected", onClick: () => deleteIds([...selected]), disabled: !someSelected, danger: true },
    { label: "Schedule cleanup", onClick: () => setScheduleOpen((o) => !o) },
    { label: "Delete all", onClick: () => deleteAll(), disabled: !items.length, danger: true },
  ];

  const viewActions = MEDIA_VIEW_OPTIONS.map((opt) => ({
    label: opt.label,
    onClick: () => changeView(opt.id),
  }));

  const pageTitle = isAdminScope
    ? subjectName
      ? `User Storage — ${subjectName}`
      : "User Storage"
    : "Media";

  return (
    <AdminPage
      title={pageTitle}
      actions={
        <RowActionsMenu
          label="View"
          actions={viewActions}
        />
      }
    >
      {backLink ? (
        <p style={{ margin: "0 0 0.75rem" }}>
          <Link to={backLink.to} className="btn btn-ghost activity-back">
            {backLink.label}
          </Link>
        </p>
      ) : null}
      {isAdminScope ? (
        <p className="muted-text" style={{ marginTop: 0 }}>
          Admin view of this user&apos;s media library (same files, filters, and actions they see).
        </p>
      ) : null}
      {flash ? <p className="alert alert-success">{flash}</p> : null}
      {error ? <p className="alert alert-error" role="alert">{error}</p> : null}

      <section className="media-page-quota card">
        <div className="media-page-quota__head">
          <div>
            <h2 className="media-page-quota__title">Storage</h2>
            <p className="muted-text media-page-quota__sub">
              {quota
                ? `${formatMediaBytes(quota.used_bytes)} of ${formatMediaBytes(quota.quota_bytes)} used · ${quota.file_count} file${quota.file_count === 1 ? "" : "s"}`
                : "Loading…"}
            </p>
          </div>
          <span className="media-page-quota__badge">
            {quota ? formatMediaQuotaLabel(quota.quota_bytes) : "…"}
          </span>
        </div>
        <div className="media-page-quota__bar" aria-hidden>
          <div className="media-page-quota__fill" style={{ width: `${usagePercent}%` }} />
        </div>
      </section>

      <section className="media-page-toolbar card">
        <div className="media-page-filters">
          {/* On a phone the search and dates fold behind one button; Refresh stays in sight. */}
          <FilterPanel activeCount={countActiveFilters([search, fromDate, toDate])}>
            <input
              type="search"
              className="media-page-search"
              placeholder="Search prompt, filename, model, type…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              dir="auto"
            />
            <label className="media-page-date">
              <span>From</span>
              <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
            </label>
            <label className="media-page-date">
              <span>To</span>
              <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
            </label>
          </FilterPanel>
          <button type="button" className="btn btn-ghost" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
        </div>

        <div className="media-page-actions">
          <label className="media-page-select-all">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleSelectAll}
              disabled={!displayItems.length}
            />
            <span>
              {someSelected ? `${selected.size} selected` : "Select all"}
              {total > displayItems.length ? ` (${displayItems.length} shown)` : ""}
            </span>
          </label>
          {phone && !readOnly ? (
            <RowActionsMenu
              label={downloadingZip ? "Preparing ZIP…" : "Actions"}
              actions={bulkActions}
              onError={setError}
            />
          ) : (
            <>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={!someSelected || downloadingZip}
                onClick={() => void downloadSelected(false)}
              >
                {downloadingZip ? "Preparing ZIP…" : "Download selected"}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={!displayItems.length || downloadingZip}
                onClick={() => void downloadSelected(true)}
              >
                {downloadingZip ? "Preparing ZIP…" : "Download all (filtered)"}
              </button>
              {!readOnly ? (
                <>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={!someSelected}
                    onClick={() => void deleteIds([...selected])}
                  >
                    Delete selected
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => setScheduleOpen((o) => !o)}>
                    Schedule cleanup
                  </button>
                  <button type="button" className="btn btn-danger" disabled={!items.length} onClick={() => void deleteAll()}>
                    Delete all
                  </button>
                </>
              ) : null}
            </>
          )}
        </div>
      </section>

      {scheduleOpen && !readOnly ? (
        <form className="media-page-schedule card" onSubmit={(e) => void saveSchedule(e)}>
          <h3>{isAdminScope ? "User cleanup schedule" : "Your cleanup schedule"}</h3>
          <p className="muted-text">
            {isAdminScope
              ? `Automatically delete ${subjectName ? `${subjectName}'s` : "this user's"} media older than the retention period. Applies only to this user.`
              : "Automatically delete your own media older than the retention period. This applies only to your account."}
          </p>
          <label className="media-page-schedule__row">
            <input
              type="checkbox"
              checked={cleanupEnabled}
              onChange={(e) => setCleanupEnabled(e.target.checked)}
            />
            <span>Enable scheduled cleanup</span>
          </label>
          <div className="media-page-schedule__grid">
            <label>
              Retention (days)
              <input
                type="number"
                min={1}
                max={3650}
                value={retentionDays}
                onChange={(e) => setRetentionDays(Number(e.target.value))}
              />
            </label>
            <label>
              Hour (UTC)
              <input
                type="number"
                min={0}
                max={23}
                value={cleanupHour}
                onChange={(e) => setCleanupHour(Number(e.target.value))}
              />
            </label>
            <label>
              Minute
              <input
                type="number"
                min={0}
                max={59}
                value={cleanupMinute}
                onChange={(e) => setCleanupMinute(Number(e.target.value))}
              />
            </label>
          </div>
          {schedule?.last_cleanup_at ? (
            <p className="muted-text">Last run: {formatMediaDate(schedule.last_cleanup_at)}</p>
          ) : null}
          <div className="media-page-schedule__foot">
            <button type="submit" className="btn" disabled={savingSchedule}>
              {savingSchedule ? "Saving…" : "Save schedule"}
            </button>
          </div>
        </form>
      ) : null}

      {loading && !items.length ? <p className="muted-text">Loading media…</p> : null}
      {!loading && !displayItems.length && !error ? (
        <p className="muted-text media-page-empty">
          {search || fromDate || toDate ? "No media matches your filters." : "No media files yet."}
        </p>
      ) : null}

      <div className={`media-page-grid media-page-grid--${viewMode}`}>
        {displayItems.map((m) => (
          <article
            key={m.id}
            className={`media-page-item${selected.has(m.id) ? " is-selected" : ""}`}
          >
            <label className="media-page-item__check">
              <input
                type="checkbox"
                checked={selected.has(m.id)}
                onChange={() => toggleSelect(m.id)}
              />
              <span className="sr-only">Select this item</span>
            </label>
            <button
              type="button"
              className="media-page-item__preview"
              onClick={() => openItem(m)}
              title={m.source_prompt || m.file_name}
            >
              {m.kind === "image" ? (
                <AuthenticatedImage url={m.url} alt={m.file_name} className="media-page-item__img" />
              ) : m.kind === "video" ? (
                <AuthenticatedVideo
                  url={m.url}
                  className="media-page-item__img"
                  title={m.source_prompt || m.file_name}
                  controls={false}
                />
              ) : (
                <div className="media-page-item__file">{m.file_name}</div>
              )}
            </button>
            <div className="media-page-item__meta">
              {viewMode === "title" ? (
                <strong className="media-page-item__prompt" title={m.source_prompt || ""}>
                  {m.source_prompt?.trim() || m.file_name}
                </strong>
              ) : (
                <>
                  <strong title={m.file_name}>{m.file_name}</strong>
                  {m.source_prompt ? (
                    <span className="media-page-item__prompt" title={m.source_prompt}>
                      {m.source_prompt}
                    </span>
                  ) : null}
                </>
              )}
              <span className="media-page-item__date">{formatMediaDate(m.created_at)}</span>
              <span className="media-page-item__size">{formatMediaBytes(m.size_bytes)}</span>
            </div>
            <div className="media-page-item__actions">
              <button type="button" className="btn btn-ghost btn-sm media-page-item__open" onClick={() => openItem(m)}>
                Open
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => void downloadOne(m)}>
                Download
              </button>
              {!readOnly ? (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => void deleteIds([m.id])}>
                  Delete
                </button>
              ) : null}
            </div>
          </article>
        ))}
      </div>
      <MediaViewerModal
        items={slideshowItems}
        index={viewerIndex}
        onClose={() => setViewerId(null)}
        onIndexChange={(next) => setViewerId(slideshowItems[next]?.id ?? null)}
        onOpenExternal={(entry) => {
          const item = displayItems.find((row) => `media-${row.id}` === entry.id);
          if (item) void openFull(item);
        }}
      />
    </AdminPage>
  );
}
