import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, authFetch } from "../api";
import AdminPage from "../components/AdminPage";
import AuthenticatedImage from "../components/AuthenticatedImage";
import AuthenticatedVideo from "../components/AuthenticatedVideo";
import RowActionsMenu from "../components/RowActionsMenu";
import { useConfirm } from "../context/ConfirmContext";
import { useReadOnly } from "../context/ReadOnlyContext";
import { fetchAuthenticatedMediaBlob, fetchAuthenticatedMediaObjectUrl, isAlphaRouterMediaFileUrl, } from "../lib/mediaUrl";
import { openSafeUrlInNewTab, safeBrowserUrl } from "../lib/browserUrlPolicy";
import MediaViewerModal from "../components/MediaViewerModal";
import { dedupeMediaItemsForDisplay, formatMediaBytes, formatMediaDate, formatMediaQuotaLabel, loadMediaViewMode, MEDIA_VIEW_OPTIONS, saveMediaViewMode, } from "../lib/mediaLibrary";
import { isSlideshowMediaKind, slideshowItemsFromMedia } from "../lib/mediaViewer";
function buildQuery(search, fromDate, toDate) {
    const q = new URLSearchParams();
    q.set("limit", "1000");
    if (search.trim())
        q.set("q", search.trim());
    if (fromDate)
        q.set("from_date", fromDate);
    if (toDate)
        q.set("to_date", toDate);
    return q.toString();
}
export default function MediaLibrary({ adminUserId, backLink } = {}) {
    const readOnly = useReadOnly();
    const isAdminScope = adminUserId != null && Number.isFinite(adminUserId);
    const apiBase = isAdminScope ? `/api/admin/users/${adminUserId}/media` : "/api/user/media";
    const { confirm } = useConfirm();
    const [subjectName, setSubjectName] = useState("");
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [quota, setQuota] = useState(null);
    const [schedule, setSchedule] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [flash, setFlash] = useState("");
    const [search, setSearch] = useState("");
    const [fromDate, setFromDate] = useState("");
    const [toDate, setToDate] = useState("");
    const [viewMode, setViewMode] = useState(() => loadMediaViewMode());
    const [selected, setSelected] = useState(() => new Set());
    const [scheduleOpen, setScheduleOpen] = useState(false);
    const [savingSchedule, setSavingSchedule] = useState(false);
    const [retentionDays, setRetentionDays] = useState(30);
    const [cleanupEnabled, setCleanupEnabled] = useState(false);
    const [cleanupHour, setCleanupHour] = useState(3);
    const [cleanupMinute, setCleanupMinute] = useState(0);
    const [downloadingZip, setDownloadingZip] = useState(false);
    const [viewerId, setViewerId] = useState(null);
    const load = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const qs = buildQuery(search, fromDate, toDate);
            const [listRes, quotaRes, scheduleRes] = await Promise.all([
                api(`${apiBase}?${qs}`),
                api(`${apiBase}/quota`),
                api(`${apiBase}/schedule`),
            ]);
            setItems(listRes.items);
            setTotal(listRes.total);
            if (isAdminScope) {
                const label = listRes.display_name?.trim() ||
                    quotaRes.display_name?.trim() ||
                    listRes.username ||
                    quotaRes.username ||
                    "";
                if (label)
                    setSubjectName(label);
            }
            setQuota(quotaRes);
            setSchedule(scheduleRes);
            setRetentionDays(scheduleRes.cleanup_retention_days);
            setCleanupEnabled(scheduleRes.cleanup_enabled);
            setCleanupHour(scheduleRes.cleanup_hour);
            setCleanupMinute(scheduleRes.cleanup_minute);
            setSelected(new Set());
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setLoading(false);
        }
    }, [search, fromDate, toDate, apiBase, isAdminScope]);
    useEffect(() => {
        void load();
    }, [load]);
    const displayItems = useMemo(() => dedupeMediaItemsForDisplay(items), [items]);
    const slideshowItems = useMemo(() => slideshowItemsFromMedia(displayItems), [displayItems]);
    const viewerIndex = useMemo(() => {
        if (!viewerId)
            return null;
        const next = slideshowItems.findIndex((entry) => entry.id === viewerId);
        return next >= 0 ? next : null;
    }, [viewerId, slideshowItems]);
    useEffect(() => {
        if (viewerId && viewerIndex == null)
            setViewerId(null);
    }, [viewerId, viewerIndex]);
    const allSelected = displayItems.length > 0 && displayItems.every((m) => selected.has(m.id));
    const someSelected = selected.size > 0;
    function toggleSelect(id) {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(id))
                next.delete(id);
            else
                next.add(id);
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
    function changeView(mode) {
        setViewMode(mode);
        saveMediaViewMode(mode);
    }
    async function deleteIds(ids) {
        if (!ids.length || readOnly)
            return;
        const ok = await confirm({
            title: "Delete media",
            message: `Delete ${ids.length} file${ids.length === 1 ? "" : "s"}? This cannot be undone.`,
            confirmLabel: "Delete",
            danger: true,
        });
        if (!ok)
            return;
        setError("");
        try {
            await api(`${apiBase}/bulk-delete`, {
                method: "POST",
                body: JSON.stringify({ ids }),
            });
            setFlash(`Removed ${ids.length} file(s).`);
            await load();
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function deleteAll() {
        if (readOnly || !items.length)
            return;
        const ok = await confirm({
            title: "Delete all media",
            message: isAdminScope
                ? `Remove every media file for ${subjectName || "this user"}?`
                : "Remove every media file in your library? This only affects your account.",
            confirmLabel: "Delete all",
            danger: true,
        });
        if (!ok)
            return;
        try {
            const res = await api(`${apiBase}/all`, { method: "DELETE" });
            setFlash(`Removed ${res.removed} file(s).`);
            await load();
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function saveSchedule(e) {
        e.preventDefault();
        if (readOnly)
            return;
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
        }
        catch (err) {
            setError(String(err));
        }
        finally {
            setSavingSchedule(false);
        }
    }
    async function downloadOne(item) {
        const trigger = (href, name) => {
            const safeHref = safeBrowserUrl(href, "download");
            if (!safeHref)
                throw new Error("Blocked unsafe media URL.");
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
        }
        catch (e) {
            setError(String(e));
        }
    }
    async function downloadAsZip(targets) {
        if (!targets.length)
            return;
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
                    const j = JSON.parse(text);
                    if (j.detail)
                        detail = j.detail;
                }
                catch {
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
        }
        catch (e) {
            setError(String(e));
        }
        finally {
            setDownloadingZip(false);
        }
    }
    async function downloadSelected(allFiltered = false) {
        const targets = allFiltered ? displayItems : displayItems.filter((m) => selected.has(m.id));
        if (!targets.length)
            return;
        if (allFiltered || targets.length > 1) {
            await downloadAsZip(targets);
            return;
        }
        await downloadOne(targets[0]);
        setFlash("Downloaded 1 file.");
    }
    function openItem(item) {
        if (isSlideshowMediaKind(item.kind)) {
            const nextId = `media-${item.id}`;
            if (slideshowItems.some((entry) => entry.id === nextId)) {
                setViewerId(nextId);
                return;
            }
        }
        void openFull(item);
    }
    async function openFull(item) {
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
        }
        catch (e) {
            setError(String(e));
        }
    }
    const usagePercent = useMemo(() => {
        if (!quota)
            return 0;
        return Math.min(100, quota.used_percent);
    }, [quota]);
    const viewActions = MEDIA_VIEW_OPTIONS.map((opt) => ({
        label: opt.label,
        onClick: () => changeView(opt.id),
    }));
    const pageTitle = isAdminScope
        ? subjectName
            ? `User Storage — ${subjectName}`
            : "User Storage"
        : "Media";
    return (_jsxs(AdminPage, { title: pageTitle, actions: _jsx(RowActionsMenu, { label: "View", actions: viewActions }), children: [backLink ? (_jsx("p", { style: { margin: "0 0 0.75rem" }, children: _jsx(Link, { to: backLink.to, className: "btn btn-ghost activity-back", children: backLink.label }) })) : null, isAdminScope ? (_jsx("p", { className: "muted-text", style: { marginTop: 0 }, children: "Admin view of this user's media library (same files, filters, and actions they see)." })) : null, flash ? _jsx("p", { className: "alert alert-success", children: flash }) : null, error ? _jsx("p", { className: "alert alert-error", children: error }) : null, _jsxs("section", { className: "media-page-quota card", children: [_jsxs("div", { className: "media-page-quota__head", children: [_jsxs("div", { children: [_jsx("h2", { className: "media-page-quota__title", children: "Storage" }), _jsx("p", { className: "muted-text media-page-quota__sub", children: quota
                                            ? `${formatMediaBytes(quota.used_bytes)} of ${formatMediaBytes(quota.quota_bytes)} used · ${quota.file_count} file${quota.file_count === 1 ? "" : "s"}`
                                            : "Loading…" })] }), _jsx("span", { className: "media-page-quota__badge", children: quota ? formatMediaQuotaLabel(quota.quota_bytes) : "…" })] }), _jsx("div", { className: "media-page-quota__bar", "aria-hidden": true, children: _jsx("div", { className: "media-page-quota__fill", style: { width: `${usagePercent}%` } }) })] }), _jsxs("section", { className: "media-page-toolbar card", children: [_jsxs("div", { className: "media-page-filters", children: [_jsx("input", { type: "search", className: "media-page-search", placeholder: "Search prompt, filename, model, type\u2026", value: search, onChange: (e) => setSearch(e.target.value), dir: "auto" }), _jsxs("label", { className: "media-page-date", children: [_jsx("span", { children: "From" }), _jsx("input", { type: "date", value: fromDate, onChange: (e) => setFromDate(e.target.value) })] }), _jsxs("label", { className: "media-page-date", children: [_jsx("span", { children: "To" }), _jsx("input", { type: "date", value: toDate, onChange: (e) => setToDate(e.target.value) })] }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => void load(), disabled: loading, children: "Refresh" })] }), _jsxs("div", { className: "media-page-actions", children: [_jsxs("label", { className: "media-page-select-all", children: [_jsx("input", { type: "checkbox", checked: allSelected, onChange: toggleSelectAll, disabled: !displayItems.length }), _jsxs("span", { children: [someSelected ? `${selected.size} selected` : "Select all", total > displayItems.length ? ` (${displayItems.length} shown)` : ""] })] }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: !someSelected || downloadingZip, onClick: () => void downloadSelected(false), children: downloadingZip ? "Preparing ZIP…" : "Download selected" }), _jsx("button", { type: "button", className: "btn btn-ghost", disabled: !displayItems.length || downloadingZip, onClick: () => void downloadSelected(true), children: downloadingZip ? "Preparing ZIP…" : "Download all (filtered)" }), !readOnly ? (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: "btn btn-ghost", disabled: !someSelected, onClick: () => void deleteIds([...selected]), children: "Delete selected" }), _jsx("button", { type: "button", className: "btn btn-ghost", onClick: () => setScheduleOpen((o) => !o), children: "Schedule cleanup" }), _jsx("button", { type: "button", className: "btn btn-danger", disabled: !items.length, onClick: () => void deleteAll(), children: "Delete all" })] })) : null] })] }), scheduleOpen && !readOnly ? (_jsxs("form", { className: "media-page-schedule card", onSubmit: (e) => void saveSchedule(e), children: [_jsx("h3", { children: isAdminScope ? "User cleanup schedule" : "Your cleanup schedule" }), _jsx("p", { className: "muted-text", children: isAdminScope
                            ? `Automatically delete ${subjectName ? `${subjectName}'s` : "this user's"} media older than the retention period. Applies only to this user.`
                            : "Automatically delete your own media older than the retention period. This applies only to your account." }), _jsxs("label", { className: "media-page-schedule__row", children: [_jsx("input", { type: "checkbox", checked: cleanupEnabled, onChange: (e) => setCleanupEnabled(e.target.checked) }), _jsx("span", { children: "Enable scheduled cleanup" })] }), _jsxs("div", { className: "media-page-schedule__grid", children: [_jsxs("label", { children: ["Retention (days)", _jsx("input", { type: "number", min: 1, max: 3650, value: retentionDays, onChange: (e) => setRetentionDays(Number(e.target.value)) })] }), _jsxs("label", { children: ["Hour (UTC)", _jsx("input", { type: "number", min: 0, max: 23, value: cleanupHour, onChange: (e) => setCleanupHour(Number(e.target.value)) })] }), _jsxs("label", { children: ["Minute", _jsx("input", { type: "number", min: 0, max: 59, value: cleanupMinute, onChange: (e) => setCleanupMinute(Number(e.target.value)) })] })] }), schedule?.last_cleanup_at ? (_jsxs("p", { className: "muted-text", children: ["Last run: ", formatMediaDate(schedule.last_cleanup_at)] })) : null, _jsx("div", { className: "media-page-schedule__foot", children: _jsx("button", { type: "submit", className: "btn", disabled: savingSchedule, children: savingSchedule ? "Saving…" : "Save schedule" }) })] })) : null, loading && !items.length ? _jsx("p", { className: "muted-text", children: "Loading media\u2026" }) : null, !loading && !displayItems.length && !error ? (_jsx("p", { className: "muted-text media-page-empty", children: search || fromDate || toDate ? "No media matches your filters." : "No media files yet." })) : null, _jsx("div", { className: `media-page-grid media-page-grid--${viewMode}`, children: displayItems.map((m) => (_jsxs("article", { className: `media-page-item${selected.has(m.id) ? " is-selected" : ""}`, children: [_jsx("label", { className: "media-page-item__check", children: _jsx("input", { type: "checkbox", checked: selected.has(m.id), onChange: () => toggleSelect(m.id) }) }), _jsx("button", { type: "button", className: "media-page-item__preview", onClick: () => openItem(m), title: m.source_prompt || m.file_name, children: m.kind === "image" ? (_jsx(AuthenticatedImage, { url: m.url, alt: m.file_name, className: "media-page-item__img" })) : m.kind === "video" ? (_jsx(AuthenticatedVideo, { url: m.url, className: "media-page-item__img", title: m.source_prompt || m.file_name, controls: false })) : (_jsx("div", { className: "media-page-item__file", children: m.file_name })) }), _jsxs("div", { className: "media-page-item__meta", children: [viewMode === "title" ? (_jsx("strong", { className: "media-page-item__prompt", title: m.source_prompt || "", children: m.source_prompt?.trim() || m.file_name })) : (_jsxs(_Fragment, { children: [_jsx("strong", { title: m.file_name, children: m.file_name }), m.source_prompt ? (_jsx("span", { className: "media-page-item__prompt", title: m.source_prompt, children: m.source_prompt })) : null] })), _jsx("span", { className: "media-page-item__date", children: formatMediaDate(m.created_at) }), _jsx("span", { className: "media-page-item__size", children: formatMediaBytes(m.size_bytes) })] }), _jsxs("div", { className: "media-page-item__actions", children: [_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => openItem(m), children: "Open" }), _jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => void downloadOne(m), children: "Download" }), !readOnly ? (_jsx("button", { type: "button", className: "btn btn-ghost btn-sm", onClick: () => void deleteIds([m.id]), children: "Delete" })) : null] })] }, m.id))) }), _jsx(MediaViewerModal, { items: slideshowItems, index: viewerIndex, onClose: () => setViewerId(null), onIndexChange: (next) => setViewerId(slideshowItems[next]?.id ?? null), onOpenExternal: (entry) => {
                    const item = displayItems.find((row) => `media-${row.id}` === entry.id);
                    if (item)
                        void openFull(item);
                } })] }));
}
