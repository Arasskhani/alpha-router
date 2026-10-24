/**
 * Fixtures and a fake staff API for the Tickets page tests: one place that
 * answers `/api/admin/tickets/*` the way the contract says, and records every
 * call so a test can read what was sent.
 */
import type {
  Assignee,
  StaffCounts,
  StaffMeta,
  StaffTicketDetail,
  StaffTicketList,
  TicketSettings,
  TicketsOverview,
} from "../../lib/tickets";

const ASSIGNEES: Assignee[] = [
  { id: 1, name: "Majid Arasskhani", username: "m.arasskhani", role_label: "Super Admin", open_count: 9, is_me: true },
  { id: 2, name: "Ali Mohammadi", username: "a.mohammadi", role_label: "Support", open_count: 7, is_me: false },
  { id: 3, name: "Leila Farahani", username: "l.farahani", role_label: "Support", open_count: 3, is_me: false },
];

export function makeMeta(over: Partial<StaffMeta["me"]> = {}): StaffMeta {
  return {
    categories: ["Bug", "Problem", "Question", "Feature request"],
    priorities: ["low", "normal", "high", "urgent"],
    statuses: ["open", "in_progress", "waiting", "resolved", "closed"],
    departments: ["Finance", "IT", "Legal"],
    assignees: ASSIGNEES,
    me: { id: 1, can_write: true, is_super_admin: true, ...over },
    settings: { auto_close_days: 7, reopen_days: 14, enabled: true },
  };
}

export const SETTINGS: TicketSettings = {
  enabled: true,
  per_hour: 5,
  max_open: 20,
  reopen_days: 14,
  auto_close_days: 7,
  retention_days: 365,
  notify_emails: ["support@company.ir"],
  notify_on_user_reply: true,
  notify_min_priority: "normal",
  email_assignee: true,
  email_user: false,
  auto_reply_enabled: true,
  auto_reply_text: "Hello {name}, we have your ticket {number}.",
  categories: ["Bug", "Problem", "Question", "Feature request"],
  image_types: ["png", "jpg", "webp", "gif"],
  max_image_mb: 5,
  max_images: 5,
  max_side_px: 4096,
};

const COUNTS: StaffCounts = { needs_staff: 5, needs_staff_urgent: 1, mine: 9, unassigned: 5, active: 24, closed: 80 };

const days = ["Oct 16", "Oct 17", "Oct 18"];

export const OVERVIEW: TicketsOverview = {
  period: "week",
  period_label: "Past 1 Week",
  timezone: "local",
  kpis: {
    opened: { value: 48, change_pct: 12.5, sparkline: [3, 5, 10] },
    resolved: { value: 41, change_pct: 8, sparkline: [2, 3, 6] },
    open_now: { value: 24, change_pct: -11.1, sparkline: [27, 25, 24], unanswered: 5 },
    first_reply_minutes: { value: 80, change_pct: -15.2, sparkline: [110, 95, 80] },
    resolution_hours: { value: 21, change_pct: 6.1, sparkline: [18, 19, 21] },
    auto_closed: { value: 6, change_pct: 20, sparkline: [0, 1, 1], share_pct: 15 },
  },
  top_departments: [
    { department: "Finance", opened: 14, still_open: 4, urgent_open: 0 },
    { department: "IT", opened: 11, still_open: 6, urgent_open: 1 },
  ],
  workload: [
    { user_id: null, name: "Unassigned", role_label: "", open: 5, resolved: 0, oldest_wait_minutes: 190 },
    { user_id: 1, name: "Majid Arasskhani", role_label: "Super Admin", open: 9, resolved: 17 },
    { user_id: 2, name: "Ali Mohammadi", role_label: "Support", open: 7, resolved: 14 },
  ],
  first_reply_by_priority: [
    { priority: "urgent", tickets: 3, median_minutes: 18 },
    { priority: "normal", tickets: 27, median_minutes: 95 },
  ],
  opened_by_priority: {
    segments: [
      { key: "low", label: "Low", color: "#94a3b8" },
      { key: "normal", label: "Normal", color: "#38bdf8" },
      { key: "high", label: "High", color: "#f59e0b" },
      { key: "urgent", label: "Urgent", color: "#f87171" },
    ],
    chart: days.map((label, i) => ({ label, low: i, normal: 2 + i, high: 1, urgent: 0 })),
  },
  ended: {
    total: 41,
    segments: [
      { key: "staff", label: "Resolved by support", color: "#34d399", value: 29 },
      { key: "user", label: "Resolved by the user", color: "#5eead4", value: 6 },
      { key: "auto", label: "Auto-closed (no reply in 7 days)", color: "#94a3b8", value: 6 },
    ],
    chart: days.map((label) => ({ label, staff: 4, user: 1, auto: 1 })),
    reopened: 3,
    reopened_pct: 7,
  },
  backlog: {
    total: 24,
    segments: [
      { key: "open", label: "Open", color: "#60a5fa", value: 12 },
      { key: "in_progress", label: "In progress", color: "#a78bfa", value: 8 },
      { key: "waiting", label: "Waiting for user", color: "#fbbf24", value: 4 },
    ],
    chart: days.map((label) => ({ label, open: 12, in_progress: 8, waiting: 4 })),
    oldest_unanswered_minutes: 190,
  },
  by_category: {
    total: 48,
    segments: [
      { key: "bug", label: "Bug", color: "#fb7185", value: 18 },
      { key: "problem", label: "Problem", color: "#f59e0b", value: 14 },
    ],
    chart: days.map((label) => ({ label, bug: 3, problem: 2 })),
    most_common: { label: "Bug", pct: 38 },
  },
  options: {
    departments: ["Finance", "IT", "Legal"],
    assignees: [
      { id: 1, name: "Majid Arasskhani" },
      { id: 2, name: "Ali Mohammadi" },
    ],
    categories: ["Bug", "Problem"],
  },
};

export const LIST: StaffTicketList = {
  items: [
    {
      id: 47,
      number: 1047,
      title: "Can't sign in with LDAP since update",
      category: "Bug",
      priority: "urgent",
      status: "open",
      needs_staff: true,
      reporter: { name: "Reza Ahmadi", username: "r.ahmadi", department: "IT" },
      assignee: null,
      created_at: "2026-10-22T09:58:00Z",
      updated_at: "2026-10-22T09:58:00Z",
      message_count: 2,
      image_count: 0,
    },
    {
      id: 42,
      number: 1042,
      title: "Image generation fails with Gemini",
      category: "Bug",
      priority: "high",
      status: "waiting",
      needs_staff: false,
      reporter: { name: "Sara Karimi", username: "s.karimi", department: "Finance" },
      assignee: { id: 1, name: "Majid Arasskhani" },
      created_at: "2026-10-22T09:12:00Z",
      updated_at: "2026-10-22T10:05:00Z",
      message_count: 4,
      image_count: 1,
    },
  ],
  total: 2,
  page: 1,
  page_size: 50,
};

const DETAIL: StaffTicketDetail = {
  id: 47,
  number: 1047,
  title: "Can't sign in with LDAP since update",
  category: "Bug",
  priority: "urgent",
  status: "open",
  user_unread: false,
  needs_staff: true,
  created_at: "2026-10-22T09:58:00Z",
  updated_at: "2026-10-22T09:58:00Z",
  message_count: 2,
  image_count: 0,
  reopen_until: null,
  reporter: { name: "Reza Ahmadi", username: "r.ahmadi", email: "r.ahmadi@company.ir", department: "IT" },
  assignee: null,
  context: { app_version: "2.9.0", browser: "Edge 141", page: "/app/chat" },
  messages: [
    {
      id: 1,
      kind: "user",
      author: { id: 9, name: "Reza Ahmadi" },
      author_label: "Reporter",
      body: "Nobody in IT can sign in with LDAP.",
      created_at: "2026-10-22T09:58:00Z",
      internal: false,
      attachments: [],
    },
    {
      id: 2,
      kind: "auto",
      author: null,
      author_label: "Automatic reply",
      body: "Hello Reza, we have your ticket #1047.",
      created_at: "2026-10-22T09:58:00Z",
      internal: false,
      attachments: [],
    },
    {
      id: 3,
      kind: "event",
      author: null,
      author_label: "",
      body: "Ali Mohammadi assigned this to Majid Arasskhani · email sent",
      created_at: "2026-10-22T10:00:00Z",
      internal: true,
      attachments: [],
    },
  ],
  auto_close_at: null,
  can_reply: true,
  can_resolve: false,
  first_staff_reply_at: null,
  resolved_at: null,
  closed_at: null,
  closed_reason: null,
  resolved_by: null,
  reopened_count: 0,
  can_write: true,
  can_delete: true,
};

export type Call = { url: string; method: string; body: unknown };

type Handler = (url: string, method: string, body: unknown) => unknown;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/**
 * A fake `authFetch`: answers the staff API from the fixtures; `override` runs
 * first and may return a Response (an error) or a body.
 */
export function fakeTicketsApi(calls: Call[], override?: Handler) {
  return async (input: string, init: RequestInit = {}): Promise<Response> => {
    const method = (init.method ?? "GET").toUpperCase();
    let body: unknown = init.body;
    if (typeof init.body === "string") body = JSON.parse(init.body);
    calls.push({ url: input, method, body });
    const path = input.split("?")[0];
    const own = override?.(input, method, body);
    if (own instanceof Response) return own;
    if (own !== undefined) return json(200, own);
    if (path.endsWith("/meta")) return json(200, makeMeta());
    if (path.endsWith("/settings")) return json(200, method === "PUT" ? body : SETTINGS);
    if (path.endsWith("/counts")) return json(200, COUNTS);
    if (path.endsWith("/assignees")) return json(200, ASSIGNEES);
    if (path.endsWith("/overview")) return json(200, OVERVIEW);
    if (path.endsWith("/delete-preview")) {
      return json(200, { count: 128, messages: 611, images: 342, image_bytes: 64_000_000, includes_active: false, token: "t1", phrase: "DELETE 128 TICKETS" });
    }
    if (path.endsWith("/delete")) return json(200, { deleted: 128, messages: 611, images: 342 });
    if (path.endsWith("/delete-all")) return json(200, { deleted: 300 });
    if (path.endsWith("/bulk")) return json(200, { updated: 2 });
    if (/\/api\/admin\/tickets\/\d+/.test(path)) {
      if (method === "DELETE") return json(200, { deleted: 1 });
      return json(200, DETAIL);
    }
    if (path === "/api/admin/tickets" || path === "/api/admin/tickets/") return json(200, LIST);
    return json(404, { detail: "Not found" });
  };
}
