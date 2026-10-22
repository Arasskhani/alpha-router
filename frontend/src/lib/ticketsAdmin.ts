/**
 * Helpers for the staff Tickets pages (Overview, the queue, Settings): the
 * numbers as people read them, the queries the pages send, the Settings bounds
 * the server checks again, and the client-side image checks.
 */

import { authFetch } from "../api";
import {
  IMAGE_TYPE_CEILING,
  PRIORITIES,
  PRIORITY_LABELS,
  STATUSES,
  statusLabel,
  type DeleteFilter,
  type Priority,
  type TicketSettings,
  type TicketStatus,
} from "./tickets";

/** 18 min · 1 h 35 min · 21 h · 2 d 4 h; "—" when there is no number. */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(minutes)) return "—";
  const total = Math.max(0, Math.round(minutes));
  if (total < 60) return `${total} min`;
  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  const mins = total % 60;
  if (days > 0) return hours ? `${days} d ${hours} h` : `${days} d`;
  return mins ? `${hours} h ${mins} min` : `${hours} h`;
}

/** The KPI cards' shorter form: 18 min · 1h 20m · 21 h · 2d 4h. */
export function formatDurationShort(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(minutes)) return "—";
  const total = Math.max(0, Math.round(minutes));
  if (total < 60) return `${total} min`;
  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  const mins = total % 60;
  if (days > 0) return hours ? `${days}d ${hours}h` : `${days} d`;
  return mins ? `${hours}h ${mins}m` : `${hours} h`;
}

/** "Sara Karimi" → "SK"; "IT" → "IT"; "Finance" → "FI". */
export function initials(label: string): string {
  const parts = label.trim().split(/[\s@._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

/** The first word of a name, for "Reply to Sara…". */
export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

/** "8 min", "3 h", "yesterday", "4 days", "12 Oct": how long ago a row last moved. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days`;
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** "09:12" today, "21 Oct 09:12" before. */
export function messageTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return time;
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} ${time}`;
}

/* ------------------------------------------------------------------ Overview */

export type OverviewFilterKey = "assignee" | "department" | "priority" | "category" | "status";
export type OverviewFilters = Record<OverviewFilterKey, string>;
export const OVERVIEW_FILTER_KEYS: OverviewFilterKey[] = ["assignee", "department", "priority", "category", "status"];

export const OVERVIEW_PERIODS = ["15m", "30m", "1h", "3h", "day", "2d", "week", "month", "year"] as const;
export type OverviewPeriod = (typeof OVERVIEW_PERIODS)[number];

/** The period in the address, or a week (the Overview's default). */
export function parseOverviewPeriod(raw: string | null): OverviewPeriod {
  return OVERVIEW_PERIODS.includes(raw as OverviewPeriod) ? (raw as OverviewPeriod) : "week";
}

export function readOverviewFilters(params: URLSearchParams): OverviewFilters {
  return {
    assignee: params.get("assignee") ?? "",
    department: params.get("department") ?? "",
    priority: params.get("priority") ?? "",
    category: params.get("category") ?? "",
    status: params.get("status") ?? "",
  };
}

/** The query `/overview` and `/overview.csv` take. */
export function overviewQuery(period: string, timezone: "local" | "utc", filters: OverviewFilters): string {
  const q = new URLSearchParams({ period, timezone });
  for (const key of OVERVIEW_FILTER_KEYS) if (filters[key]) q.set(key, filters[key]);
  return q.toString();
}

/** "Department: Finance · Priority: High" for the subtitle. */
export function overviewFilterSummary(
  filters: OverviewFilters,
  assignees: { id: number; name: string }[],
): string {
  const parts: string[] = [];
  if (filters.assignee) {
    const name =
      filters.assignee === "none"
        ? "Unassigned"
        : (assignees.find((a) => String(a.id) === filters.assignee)?.name ?? `#${filters.assignee}`);
    parts.push(`Assignee: ${name}`);
  }
  if (filters.department) parts.push(`Department: ${filters.department}`);
  if (filters.priority) parts.push(`Priority: ${PRIORITY_LABELS[filters.priority as Priority] ?? filters.priority}`);
  if (filters.category) parts.push(`Category: ${filters.category}`);
  if (filters.status) parts.push(`Status: ${statusLabel(filters.status as TicketStatus, "staff")}`);
  return parts.join(" · ");
}

/**
 * Whether a change is good news. Volume is neither (grey); fewer open tickets,
 * a shorter reply and a shorter resolution are; more resolved tickets are.
 */
export type KpiDirection = "up" | "down" | null;

export function kpiTone(changePct: number | null, better: KpiDirection): "good" | "bad" | "flat" {
  if (changePct == null || changePct === 0 || better == null) return "flat";
  const up = changePct > 0;
  return up === (better === "up") ? "good" : "bad";
}

/* --------------------------------------------------------------------- Queue */

export type QueueFilters = {
  view: string;
  q: string;
  priority: string;
  category: string;
  department: string;
  assignee: string;
  status: string;
};

export const QUEUE_VIEWS = ["needs_staff", "mine", "unassigned", "active", "closed", "all"] as const;

export function readQueueFilters(params: URLSearchParams): QueueFilters {
  const view = params.get("view") ?? "active";
  return {
    view: QUEUE_VIEWS.includes(view as (typeof QUEUE_VIEWS)[number]) ? view : "active",
    q: params.get("q") ?? "",
    priority: params.get("priority") ?? "",
    category: params.get("category") ?? "",
    department: params.get("department") ?? "",
    assignee: params.get("assignee") ?? "",
    status: params.get("status") ?? "",
  };
}

/** The list (and `/export.csv`) query: empty filters are left out. */
export function queueQuery(filters: QueueFilters, extra: Record<string, string | number> = {}): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) q.set(key, value);
  for (const [key, value] of Object.entries(extra)) q.set(key, String(value));
  return q.toString();
}

/** The queue filters as a delete filter: the statuses default to Resolved and Closed. */
export function deleteFilterFromQueue(filters: QueueFilters): DeleteFilter {
  const out: DeleteFilter = { statuses: ["resolved", "closed"] };
  if (filters.status && STATUSES.includes(filters.status as TicketStatus)) out.statuses = [filters.status as TicketStatus];
  if (filters.priority) out.priority = filters.priority as Priority;
  if (filters.category) out.category = filters.category;
  if (filters.department) out.department = filters.department;
  if (filters.assignee) out.assignee = filters.assignee;
  return out;
}

/** Only the keys the server reads, with empty values dropped. */
export function cleanDeleteFilter(filter: DeleteFilter): DeleteFilter {
  const out: DeleteFilter = { statuses: filter.statuses?.length ? filter.statuses : ["resolved", "closed"] };
  if (filter.priority) out.priority = filter.priority;
  if (filter.category) out.category = filter.category;
  if (filter.department) out.department = filter.department;
  if (filter.assignee) out.assignee = filter.assignee;
  if (filter.before) out.before = filter.before;
  return out;
}

/** The export of what a delete filter matches, offered before deleting it. */
export function deleteFilterExportQuery(filter: DeleteFilter): string {
  const q = new URLSearchParams({ view: "all" });
  const statuses = filter.statuses ?? [];
  if (statuses.length === 1) q.set("status", statuses[0]);
  else if (statuses.length > 1) q.set("statuses", statuses.join(","));
  if (filter.priority) q.set("priority", filter.priority);
  if (filter.category) q.set("category", filter.category);
  if (filter.department) q.set("department", filter.department);
  if (filter.assignee) q.set("assignee", filter.assignee);
  if (filter.before) q.set("before", filter.before);
  return q.toString();
}

/* ------------------------------------------------------------------ Settings */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

type NumberField =
  | "per_hour"
  | "max_open"
  | "reopen_days"
  | "auto_close_days"
  | "retention_days"
  | "max_image_mb"
  | "max_images"
  | "max_side_px";

/** The bounds the server checks (contract § Settings). */
export const SETTINGS_BOUNDS: Record<NumberField, [number, number]> = {
  per_hour: [1, 100],
  max_open: [1, 200],
  reopen_days: [1, 90],
  auto_close_days: [1, 60],
  retention_days: [0, 3650],
  max_image_mb: [1, 10],
  max_images: [1, 10],
  max_side_px: [512, 8192],
};

export type SettingsErrors = Partial<Record<keyof TicketSettings, string>>;

/** What is wrong with the form, by field; empty when it can be saved. */
export function validateSettings(s: TicketSettings): SettingsErrors {
  const errors: SettingsErrors = {};
  for (const [field, [min, max]] of Object.entries(SETTINGS_BOUNDS) as [NumberField, [number, number]][]) {
    const value = s[field];
    if (!Number.isInteger(value) || value < min || value > max) {
      errors[field] = `Enter a whole number from ${min} to ${max}.`;
    }
  }
  if (s.notify_emails.length > 20) errors.notify_emails = "At most 20 addresses.";
  else {
    const bad = s.notify_emails.find((e) => !isValidEmail(e));
    if (bad) errors.notify_emails = `Not a valid address: ${bad}`;
  }
  if (!PRIORITIES.includes(s.notify_min_priority)) errors.notify_min_priority = "Choose a priority.";
  const names = s.categories.map((c) => c.trim());
  if (names.length === 0) errors.categories = "Keep at least one category.";
  else if (names.length > 20) errors.categories = "At most 20 categories.";
  else if (names.some((n) => !n)) errors.categories = "A category needs a name.";
  else if (names.some((n) => n.length > 40)) errors.categories = "A category name is at most 40 characters.";
  else if (new Set(names.map((n) => n.toLowerCase())).size !== names.length) {
    errors.categories = "Each category needs a different name.";
  }
  const ceiling = IMAGE_TYPE_CEILING as readonly string[];
  if (s.image_types.length === 0) errors.image_types = "Allow at least one image type.";
  else if (s.image_types.some((t) => !ceiling.includes(t))) errors.image_types = "Only PNG, JPG, WEBP and GIF can be allowed.";
  if (s.auto_reply_text.length > 2000) errors.auto_reply_text = "At most 2,000 characters.";
  else if (s.auto_reply_enabled && !s.auto_reply_text.trim()) errors.auto_reply_text = "Write the reply, or turn it off.";
  return errors;
}

/* -------------------------------------------------------------------- Images */

const MIME_TO_TYPE: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
};

/** png / jpg / webp / gif from the file's type or, failing that, its name. */
export function imageTypeOf(file: File): string | null {
  const byMime = MIME_TO_TYPE[file.type.toLowerCase()];
  if (byMime) return byMime;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "jpeg") return "jpg";
  return (IMAGE_TYPE_CEILING as readonly string[]).includes(ext) ? ext : null;
}

export type ImageLimits = { image_types: string[]; max_image_mb: number; max_images: number; max_side_px: number };

/** Why this file cannot be sent, or "" when it can (the server checks again). */
export function imageProblem(file: File, limits: ImageLimits): string {
  const type = imageTypeOf(file);
  if (!type || !limits.image_types.includes(type)) return "not an allowed image type";
  if (file.size > limits.max_image_mb * 1024 * 1024) return `over ${limits.max_image_mb} MB`;
  return "";
}

/** The largest side in pixels, where the browser can tell; null when it cannot. */
export async function imageLargestSide(file: File): Promise<number | null> {
  if (typeof createImageBitmap !== "function") return null;
  try {
    const bitmap = await createImageBitmap(file);
    const side = Math.max(bitmap.width, bitmap.height);
    bitmap.close();
    return side;
  } catch {
    return null;
  }
}

/** "PNG, JPG, WEBP, GIF". */
export function imageTypesLabel(types: string[]): string {
  return types.map((t) => t.toUpperCase()).join(", ");
}

/* ------------------------------------------------------------------ Download */

/** Fetch a CSV with the session and save it; throws with the server's message. */
export async function downloadCsv(path: string, fallbackName: string): Promise<void> {
  const res = await authFetch(path);
  if (!res.ok) {
    let message = `Export failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
        message = String((body.detail as { message: unknown }).message);
      }
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  const match = res.headers.get("Content-Disposition")?.match(/filename="?([^";]+)"?/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = match?.[1] ?? fallbackName;
  a.click();
  URL.revokeObjectURL(a.href);
}
