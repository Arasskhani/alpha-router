import { formatLocalDateTime } from "./dateTime";
import { STORAGE_KEYS } from "./brand";
export const MEDIA_VIEW_OPTIONS = [
    { id: "extra-large", label: "Extra Large" },
    { id: "large", label: "Large" },
    { id: "medium", label: "Medium" },
    { id: "small", label: "Small" },
    { id: "list", label: "List" },
    { id: "detail", label: "Detail" },
    { id: "title", label: "Title" },
];
export function loadMediaViewMode() {
    try {
        const raw = localStorage.getItem(STORAGE_KEYS.mediaView);
        if (raw && MEDIA_VIEW_OPTIONS.some((o) => o.id === raw))
            return raw;
    }
    catch {
        /* ignore */
    }
    return "medium";
}
export function saveMediaViewMode(mode) {
    localStorage.setItem(STORAGE_KEYS.mediaView, mode);
}
export function formatMediaBytes(bytes) {
    let v = bytes || 0;
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i += 1;
    }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
export function formatMediaQuotaLabel(quotaBytes) {
    const gb = quotaBytes / (1024 * 1024 * 1024);
    if (gb >= 1 && Math.abs(gb - Math.round(gb)) < 0.05) {
        const n = Math.round(gb);
        return n === 1 ? "1 GB per user" : `${n} GB per user`;
    }
    return `${formatMediaBytes(quotaBytes)} per user`;
}
export function formatMediaDate(iso) {
    return formatLocalDateTime(iso);
}
/** Collapse duplicate media rows (same image persisted twice) for Media UI display. */
export function mediaDedupeKey(m) {
    const hash = (m.content_hash || "").trim().toLowerCase();
    if (hash)
        return `hash:${hash}`;
    const prompt = (m.source_prompt || "").trim().toLowerCase();
    const minute = (m.created_at || "").slice(0, 16);
    const sizeBucket = Math.round((m.size_bytes || 0) / 16384);
    return `fuzzy:${m.kind}:${minute}:${sizeBucket}:${prompt}`;
}
export function dedupeMediaItemsForDisplay(items) {
    const keep = new Map();
    for (const item of items) {
        const key = mediaDedupeKey(item);
        const prev = keep.get(key);
        if (!prev || item.id > prev.id)
            keep.set(key, item);
    }
    return [...keep.values()].sort((a, b) => {
        const ta = Date.parse(a.created_at || "") || 0;
        const tb = Date.parse(b.created_at || "") || 0;
        return tb - ta || b.id - a.id;
    });
}
