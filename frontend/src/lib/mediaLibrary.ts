import { formatLocalDateTime } from "./dateTime";

export type MediaItem = {
  id: number;
  kind: string;
  mime_type: string;
  file_name: string;
  size_bytes: number;
  source_model?: string;
  source_prompt?: string;
  chat_session_id?: string;
  created_at?: string;
  expires_at?: string;
  url: string;
  content_hash?: string | null;
};

export type MediaQuota = {
  quota_bytes: number;
  used_bytes: number;
  remaining_bytes: number;
  file_count: number;
  used_percent: number;
};

export type MediaSchedule = {
  cleanup_enabled: boolean;
  cleanup_retention_days: number;
  cleanup_hour: number;
  cleanup_minute: number;
  last_cleanup_at?: string | null;
};

export type MediaViewMode =
  | "extra-large"
  | "large"
  | "medium"
  | "small"
  | "list"
  | "detail"
  | "title";

export const MEDIA_VIEW_OPTIONS: { id: MediaViewMode; label: string }[] = [
  { id: "extra-large", label: "Extra Large" },
  { id: "large", label: "Large" },
  { id: "medium", label: "Medium" },
  { id: "small", label: "Small" },
  { id: "list", label: "List" },
  { id: "detail", label: "Detail" },
  { id: "title", label: "Title" },
];

const VIEW_KEY = "nitro_media_view";

export function loadMediaViewMode(): MediaViewMode {
  try {
    const raw = localStorage.getItem(VIEW_KEY) as MediaViewMode | null;
    if (raw && MEDIA_VIEW_OPTIONS.some((o) => o.id === raw)) return raw;
  } catch {
    /* ignore */
  }
  return "medium";
}

export function saveMediaViewMode(mode: MediaViewMode) {
  localStorage.setItem(VIEW_KEY, mode);
}

export function formatMediaBytes(bytes: number): string {
  let v = bytes || 0;
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatMediaQuotaLabel(quotaBytes: number): string {
  const gb = quotaBytes / (1024 * 1024 * 1024);
  if (gb >= 1 && Math.abs(gb - Math.round(gb)) < 0.05) {
    const n = Math.round(gb);
    return n === 1 ? "1 GB per user" : `${n} GB per user`;
  }
  return `${formatMediaBytes(quotaBytes)} per user`;
}

export function formatMediaDate(iso?: string): string {
  return formatLocalDateTime(iso);
}

/** Collapse duplicate media rows (same image persisted twice) for Media UI display. */
export function mediaDedupeKey(m: MediaItem): string {
  const hash = (m.content_hash || "").trim().toLowerCase();
  if (hash) return `hash:${hash}`;
  const prompt = (m.source_prompt || "").trim().toLowerCase();
  const minute = (m.created_at || "").slice(0, 16);
  const sizeBucket = Math.round((m.size_bytes || 0) / 16384);
  return `fuzzy:${m.kind}:${minute}:${sizeBucket}:${prompt}`;
}

export function dedupeMediaItemsForDisplay(items: MediaItem[]): MediaItem[] {
  const keep = new Map<string, MediaItem>();
  for (const item of items) {
    const key = mediaDedupeKey(item);
    const prev = keep.get(key);
    if (!prev || item.id > prev.id) keep.set(key, item);
  }
  return [...keep.values()].sort((a, b) => {
    const ta = Date.parse(a.created_at || "") || 0;
    const tb = Date.parse(b.created_at || "") || 0;
    return tb - ta || b.id - a.id;
  });
}
