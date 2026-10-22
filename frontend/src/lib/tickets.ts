/**
 * Tickets (Support): the shapes the user API (`/api/support`) and the staff API
 * (`/api/admin/tickets`) return, their labels, and one request helper that keeps
 * the server's error code (`count_changed`, `image_rejected`, …) so a page can
 * answer each one rather than print a message.
 */

import { authFetch } from "../api";

export const SUPPORT_BASE = "/api/support";
export const TICKETS_BASE = "/api/admin/tickets";

/** Sent on `window` after anything that can change a menu count; the badges read it. */
export const TICKETS_CHANGED_EVENT = "alpha-router:tickets-changed";

export type Priority = "low" | "normal" | "high" | "urgent";
export type TicketStatus = "open" | "in_progress" | "waiting" | "resolved" | "closed";
export type MessageKind = "user" | "staff" | "note" | "auto" | "event";
export type ClosedReason = "manual" | "auto" | "resolved";
export type StaffView = "needs_staff" | "mine" | "unassigned" | "active" | "closed" | "all";
export type UserState = "open" | "resolved" | "all";

export const PRIORITIES: Priority[] = ["low", "normal", "high", "urgent"];
export const STATUSES: TicketStatus[] = ["open", "in_progress", "waiting", "resolved", "closed"];
export const ACTIVE_STATUSES: TicketStatus[] = ["open", "in_progress", "waiting"];

export const PRIORITY_LABELS: Record<Priority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

const STATUS_LABELS: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  waiting: "Waiting for user",
  resolved: "Resolved",
  closed: "Closed",
};

/** The person sees "Waiting for you"; staff see "Waiting for user". */
export function statusLabel(status: TicketStatus, audience: "user" | "staff"): string {
  if (status === "waiting" && audience === "user") return "Waiting for you";
  return STATUS_LABELS[status] ?? status;
}

export const STAFF_VIEW_LABELS: Record<StaffView, string> = {
  needs_staff: "Needs staff",
  mine: "Mine",
  unassigned: "Unassigned",
  active: "All active",
  closed: "Closed",
  all: "All",
};

export type Reporter = { name: string; username: string; email: string | null; department: string | null };
export type PersonRef = { id: number | null; name: string };

export type Attachment = {
  id: number;
  url: string;
  mime: string;
  bytes: number;
  width: number;
  height: number;
  display_name: string;
};

export type TicketMessage = {
  id: number;
  kind: MessageKind;
  author: PersonRef | null;
  author_label: string;
  body: string;
  created_at: string;
  internal: boolean;
  attachments: Attachment[];
};

export type UserTicketSummary = {
  id: number;
  number: number;
  title: string;
  category: string;
  priority: Priority;
  status: TicketStatus;
  user_unread: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
  image_count: number;
  reopen_until: string | null;
};

export type UserTicketDetail = UserTicketSummary & {
  reporter: Reporter;
  assignee: { id: number; name: string } | null;
  messages: TicketMessage[];
  auto_close_at: string | null;
  can_reply: boolean;
  can_resolve: boolean;
};

export type SupportLimits = {
  image_types: string[];
  max_image_mb: number;
  max_images: number;
  max_side_px: number;
};

export type SupportStatus = {
  enabled: boolean;
  unread: number;
  categories: string[];
  priorities: Priority[];
  limits: SupportLimits;
  reopen_days: number;
  auto_close_days: number;
  reporter: Reporter;
};

export type UserTicketList = {
  items: UserTicketSummary[];
  counts: { open: number; resolved: number; all: number };
};

export type Assignee = {
  id: number;
  name: string;
  username: string;
  role_label: string;
  open_count: number;
  is_me: boolean;
};

export type StaffTicketSummary = {
  id: number;
  number: number;
  title: string;
  category: string;
  priority: Priority;
  status: TicketStatus;
  needs_staff: boolean;
  reporter: { name: string; username: string; department: string | null };
  assignee: { id: number; name: string } | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  image_count: number;
};

export type TicketContext = { app_version?: string; browser?: string; page?: string };

export type StaffTicketDetail = Omit<UserTicketDetail, "user_unread"> & {
  user_unread: boolean;
  needs_staff: boolean;
  context: TicketContext | null;
  first_staff_reply_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  closed_reason: ClosedReason | null;
  resolved_by: "staff" | "user" | null;
  reopened_count: number;
  can_write: boolean;
  can_delete: boolean;
};

export type StaffTicketList = { items: StaffTicketSummary[]; total: number; page: number; page_size: number };

export type StaffCounts = {
  needs_staff: number;
  needs_staff_urgent: number;
  mine: number;
  unassigned: number;
  active: number;
  closed: number;
};

export type StaffMeta = {
  categories: string[];
  priorities: Priority[];
  statuses: TicketStatus[];
  departments: string[];
  assignees: Assignee[];
  me: { id: number; can_write: boolean; is_super_admin: boolean };
  settings: { auto_close_days: number; reopen_days: number; enabled: boolean };
};

export type TicketSettings = {
  enabled: boolean;
  per_hour: number;
  max_open: number;
  reopen_days: number;
  auto_close_days: number;
  retention_days: number;
  notify_emails: string[];
  notify_on_user_reply: boolean;
  notify_min_priority: Priority;
  email_assignee: boolean;
  email_user: boolean;
  auto_reply_enabled: boolean;
  auto_reply_text: string;
  categories: string[];
  image_types: string[];
  max_image_mb: number;
  max_images: number;
  max_side_px: number;
};

/** The image types an administrator may allow; never more. */
export const IMAGE_TYPE_CEILING = ["png", "jpg", "webp", "gif"] as const;
export const AUTO_REPLY_PLACEHOLDERS = ["{name}", "{number}", "{title}", "{priority}", "{category}"] as const;

export type DeleteFilter = {
  statuses?: TicketStatus[];
  priority?: Priority | "";
  category?: string;
  department?: string;
  assignee?: string;
  before?: string;
};

export type DeletePreview = {
  count: number;
  messages: number;
  images: number;
  image_bytes: number;
  includes_active: boolean;
  token: string;
  phrase: string;
};

export const DELETE_ALL_PHRASE = "DELETE ALL TICKETS";

export type OverviewKpi = { value: number | null; change_pct: number | null; sparkline: number[] };
export type OverviewSegment = { key: string; label: string; color: string; value?: number };
export type OverviewChart = { segments: OverviewSegment[]; chart: Record<string, string | number>[] };

export type TicketsOverview = {
  period: string;
  period_label: string;
  timezone: "local" | "utc";
  kpis: {
    opened: OverviewKpi;
    resolved: OverviewKpi;
    open_now: OverviewKpi & { unanswered: number };
    first_reply_minutes: OverviewKpi;
    resolution_hours: OverviewKpi;
    auto_closed: OverviewKpi & { share_pct: number | null };
  };
  top_departments: { department: string; opened: number; still_open: number; urgent_open: number }[];
  workload: {
    user_id: number | null;
    name: string;
    role_label: string;
    open: number;
    resolved: number;
    oldest_wait_minutes?: number | null;
  }[];
  first_reply_by_priority: { priority: Priority; tickets: number; median_minutes: number | null }[];
  opened_by_priority: OverviewChart;
  ended: OverviewChart & { total: number; reopened: number; reopened_pct: number | null };
  backlog: OverviewChart & { total: number; oldest_unanswered_minutes: number | null };
  by_category: OverviewChart & { total: number; most_common: { label: string; pct: number } | null };
  options: { departments: string[]; assignees: { id: number; name: string }[]; categories: string[] };
};

/** An API refusal with the server's code kept (`detail.code`), and whatever else it sent (`count`, `file`). */
export class TicketsApiError extends Error {
  status: number;
  code: string | null;
  data: Record<string, unknown>;

  constructor(status: number, message: string, code: string | null, data: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

async function readError(res: Response): Promise<TicketsApiError> {
  const text = await res.text();
  let message = res.statusText || `Request failed (${res.status})`;
  let code: string | null = null;
  let data: Record<string, unknown> = {};
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object") {
      data = detail as Record<string, unknown>;
      if (typeof data.message === "string") message = data.message;
      if (typeof data.code === "string") code = data.code;
    }
  } catch {
    if (text) message = text;
  }
  return new TicketsApiError(res.status, message, code, data);
}

/** JSON in, JSON out; a FormData body goes as multipart. Throws TicketsApiError. */
export async function ticketsRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body != null && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await authFetch(path, { ...init, headers });
  if (!res.ok) throw await readError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function announceTicketsChanged(): void {
  window.dispatchEvent(new Event(TICKETS_CHANGED_EVENT));
}

/** `#1042` */
export function ticketNumber(n: number): string {
  return `#${n}`;
}

/** 412 KB, 3.4 MB */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
