/**
 * Exchange EWS mailboxes: the shapes the user API (`/api/mail`) and the admin
 * API (`/api/admin/exchange-ews`) return, and one call per endpoint.
 *
 * Errors keep the server's code (`exchange_auth`, `needs_password`,
 * `exchange_conflict`, …) so a page can answer each one rather than print a
 * message: they are thrown as `MailApiError`.
 */

import { authFetch } from "../api";

const MAIL_BASE = "/api/mail";
const EXCHANGE_ADMIN_BASE = "/api/admin/exchange-ews";

/** Sent on `window` after the connection or its action items change; the indicator and the toasts read it. */
export const MAIL_CHANGED_EVENT = "alpha-router:mail-changed";

export type ConnectionStatus = "connected" | "needs_password" | "error";
type MailboxKind = "own" | "full_access";
export type MailboxSource = "own" | "autodiscover" | "manual";
export type DraftKind = "new" | "reply" | "reply_all" | "forward";
/** `sending`: another request is sending it right now (the server holds that claim for up to 10 minutes). */
export type DraftStatus = "draft" | "sending" | "sent" | "discarded" | "failed";
type ActionKind = "reply" | "schedule" | "review" | "approve" | "other";
type ActionStatus = "new" | "notified" | "dismissed" | "done";
type EligibilityReason =
  | ""
  | "feature_off"
  | "not_configured"
  | "not_ad"
  | "no_email"
  | "not_permitted"
  | "chat_off";

export type MailAddress = { name: string; email: string };

export type Mailbox = {
  id: number;
  smtp: string;
  display_name: string;
  kind: MailboxKind;
  source: MailboxSource;
  enabled: boolean;
  notify: boolean;
  verified_at: string | null;
  last_error: string | null;
};

export type MailConnection = {
  status: ConnectionStatus;
  login: string;
  primary_smtp: string;
  display_name: string;
  last_error: string | null;
  last_ok_at: string | null;
  last_checked_at: string | null;
  connected_at: string;
  notify_enabled: boolean;
  mailboxes: Mailbox[];
};

export type MailCapabilities = {
  full_access: boolean;
  manual_mailboxes: boolean;
  drafts: boolean;
  send: boolean;
  free_time: boolean;
  notifications: boolean;
  max_mailboxes: number;
};

export type MailStatus = {
  eligible: boolean;
  reason: EligibilityReason;
  message: string;
  login: string;
  email: string;
  connection: MailConnection | null;
  capabilities: MailCapabilities;
  pending_actions: number;
};

export type ActionItem = {
  id: number;
  mailbox: string;
  subject: string;
  sender_name: string | null;
  sender_email: string | null;
  received_at: string | null;
  reason: string;
  action: ActionKind;
  importance: string | null;
  status: ActionStatus;
  owa_url: string | null;
  created_at: string;
};

export type ActionItemList = { items: ActionItem[]; open_count: number };

export type MailDraft = {
  id: number;
  mailbox: string;
  kind: DraftKind;
  status: DraftStatus;
  subject: string;
  to: MailAddress[];
  cc: MailAddress[];
  body_preview: string;
  created_at: string;
  sent_at: string | null;
  error: string | null;
  chat_session_id: string | null;
};

/** A draft as it is now in Exchange (status `draft` only). */
export type MailDraftLive = MailDraft & {
  body_text: string;
  change_key: string;
  owa_url: string | null;
  can_send: boolean;
};

/** What the chat shows under an answer for a draft the model saved (`alpha_router.mail_drafts`, `mailDrafts`). */
export type MailDraftCard = {
  id: number;
  mailbox: string;
  kind: DraftKind;
  subject: string;
  to: MailAddress[];
  cc: MailAddress[];
  preview: string;
};

// --- admin ---

export type LoginFormat = "netbios" | "upn" | "email";
type DetectionMode = "rules" | "model";

export type ExchangeSettings = {
  enabled: boolean;
  ews_url: string;
  autodiscover_url: string;
  login_format: LoginFormat;
  netbios_domain: string;
  upn_suffix: string;
  verify_tls: boolean;
  ca_bundle_pem: string;
  require_mailbox_match: boolean;
  allow_full_access: boolean;
  allow_manual_mailboxes: boolean;
  allow_drafts: boolean;
  allow_send: boolean;
  allow_free_time: boolean;
  notify_enabled: boolean;
  poll_minutes: number;
  detection: DetectionMode;
  detection_model: string;
  search_limit: number;
  body_chars: number;
  timeout_s: number;
  max_mailboxes: number;
  action_retention_days: number;
};

/** Mirrors `SETTING_BOUNDS` in `app/services/exchange_mail.py`. */
export const SETTING_BOUNDS: Record<
  "poll_minutes" | "search_limit" | "body_chars" | "timeout_s" | "max_mailboxes" | "action_retention_days",
  [number, number]
> = {
  poll_minutes: [2, 60],
  search_limit: [5, 100],
  body_chars: [1000, 30000],
  timeout_s: [5, 120],
  max_mailboxes: [1, 50],
  action_retention_days: [1, 365],
};

export type ExchangeSettingsResponse = {
  settings: ExchangeSettings;
  directory: { netbios_domain: string; dns_domain: string; available: boolean };
  example_login: string;
  ews_endpoint: string;
  autodiscover_endpoint: string;
};

export type TestStep = { key: string; label: string; ok: boolean; detail: string };

export type TestResult = {
  ok: boolean;
  steps: TestStep[];
  mailbox: { smtp: string; display_name: string } | null;
  full_access: { smtp: string; display_name: string }[];
};

export type AdminConnection = {
  id: number;
  user_id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  login: string;
  status: ConnectionStatus;
  primary_smtp: string;
  mailbox_count: number;
  full_access_count: number;
  notify_enabled: boolean;
  last_ok_at: string | null;
  last_checked_at: string | null;
  last_error: string | null;
  connected_at: string;
};

export type AdminConnectionList = { items: AdminConnection[]; total: number };

export type ExchangeOverview = {
  counts: { connected: number; needs_password: number; error: number };
  eligible_accounts: number;
  action_items_7d: number;
  drafts_7d: number;
  sent_7d: number;
  last_check_at: string | null;
  enabled: boolean;
  configured: boolean;
};

export type AccessGrant = {
  target_type: "user" | "group" | "department" | "role";
  target: number | string;
  effect: "allow" | "deny";
};

export type ToolAccess = {
  tool_key: string;
  access_type: "public" | "private";
  acl_version: number;
  grants: AccessGrant[];
  updated_at: string | null;
  updated_by_user_id: number | null;
};

/** A row of the model catalog (`/api/admin/models`), for the detection model picker. */
export type CatalogModel = {
  id: number;
  external_id: string;
  display_name?: string | null;
  enabled: boolean;
  provider: string;
  kinds?: string[];
};

// --- labels ---

export const CONNECTION_STATUS_LABELS: Record<ConnectionStatus, string> = {
  connected: "Connected",
  needs_password: "Password needed",
  error: "Error",
};

export const DRAFT_KIND_LABELS: Record<DraftKind, string> = {
  new: "Draft",
  reply: "Draft reply",
  reply_all: "Draft reply all",
  forward: "Draft forward",
};


// --- requests ---

/** An API refusal with the server's code kept (`detail.code`). */
export class MailApiError extends Error {
  status: number;
  code: string | null;
  /** The message is the server's own sentence, not the HTTP status text. */
  serverMessage: boolean;

  constructor(status: number, message: string, code: string | null, serverMessage = false) {
    super(message);
    this.status = status;
    this.code = code;
    this.serverMessage = serverMessage;
  }
}

async function readError(res: Response): Promise<MailApiError> {
  const text = await res.text();
  let message = res.statusText || `Request failed (${res.status})`;
  let code: string | null = null;
  let serverMessage = false;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string" && detail) {
      message = detail;
      serverMessage = true;
    } else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const data = detail as Record<string, unknown>;
      if (typeof data.message === "string" && data.message) {
        message = data.message;
        serverMessage = true;
      }
      if (typeof data.code === "string") code = data.code;
    }
  } catch {
    if (text) message = text;
  }
  return new MailApiError(res.status, message, code, serverMessage);
}

/** JSON in, JSON out. Throws MailApiError. */
async function mailRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body != null && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await authFetch(path, { ...init, headers });
  if (!res.ok) throw await readError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function json(method: string, body?: unknown): RequestInit {
  return body === undefined ? { method } : { method, body: JSON.stringify(body) };
}

export function announceMailChanged(): void {
  window.dispatchEvent(new Event(MAIL_CHANGED_EVENT));
}

// user API

export const mailApi = {
  status: () => mailRequest<MailStatus>(`${MAIL_BASE}/status`),
  connect: (password: string) => mailRequest<MailConnection>(`${MAIL_BASE}/connect`, json("POST", { password })),
  setNotify: (notify_enabled: boolean) =>
    mailRequest<MailConnection>(`${MAIL_BASE}/connection`, json("PATCH", { notify_enabled })),
  disconnect: () => mailRequest<{ ok: true }>(`${MAIL_BASE}/connection`, json("DELETE")),
  addMailbox: (smtp: string) => mailRequest<MailConnection>(`${MAIL_BASE}/mailboxes`, json("POST", { smtp })),
  updateMailbox: (id: number, patch: { enabled?: boolean; notify?: boolean }) =>
    mailRequest<MailConnection>(`${MAIL_BASE}/mailboxes/${id}`, json("PATCH", patch)),
  removeMailbox: (id: number) => mailRequest<MailConnection>(`${MAIL_BASE}/mailboxes/${id}`, json("DELETE")),
  rediscover: () => mailRequest<MailConnection>(`${MAIL_BASE}/mailboxes/rediscover`, json("POST")),
  actionItems: (state: "open" | "all" = "open", limit = 50) =>
    mailRequest<ActionItemList>(`${MAIL_BASE}/action-items?state=${state}&limit=${limit}`),
  markNotified: (ids: number[]) => mailRequest<{ ok: true }>(`${MAIL_BASE}/action-items/notified`, json("POST", { ids })),
  dismissAction: (id: number) => mailRequest<ActionItem>(`${MAIL_BASE}/action-items/${id}/dismiss`, json("POST")),
  doneAction: (id: number) => mailRequest<ActionItem>(`${MAIL_BASE}/action-items/${id}/done`, json("POST")),
  askAction: (id: number) => mailRequest<{ prompt: string }>(`${MAIL_BASE}/action-items/${id}/ask`, json("POST")),
  draft: (id: number) => mailRequest<MailDraftLive | MailDraft>(`${MAIL_BASE}/drafts/${id}`),
  sendDraft: (id: number, change_key: string) =>
    mailRequest<MailDraft>(`${MAIL_BASE}/drafts/${id}/send`, json("POST", { change_key })),
  discardDraft: (id: number) => mailRequest<MailDraft>(`${MAIL_BASE}/drafts/${id}/discard`, json("POST")),
};

export function isLiveDraft(draft: MailDraft | MailDraftLive): draft is MailDraftLive {
  return draft.status === "draft" && typeof (draft as MailDraftLive).change_key === "string";
}

// admin API

export const exchangeAdminApi = {
  settings: () => mailRequest<ExchangeSettingsResponse>(`${EXCHANGE_ADMIN_BASE}/settings`),
  saveSettings: (settings: ExchangeSettings) =>
    mailRequest<ExchangeSettingsResponse>(`${EXCHANGE_ADMIN_BASE}/settings`, json("PUT", settings)),
  test: (body: { login: string; password: string; email?: string }) =>
    mailRequest<TestResult>(`${EXCHANGE_ADMIN_BASE}/test`, json("POST", body)),
  access: () => mailRequest<ToolAccess>(`${EXCHANGE_ADMIN_BASE}/access`),
  saveAccess: (body: { access_type: "public" | "private"; grants: AccessGrant[] }) =>
    mailRequest<ToolAccess>(`${EXCHANGE_ADMIN_BASE}/access`, json("PUT", body)),
  connections: (params: { q?: string; status?: ConnectionStatus | ""; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.status) query.set("status", params.status);
    query.set("limit", String(params.limit ?? 50));
    query.set("offset", String(params.offset ?? 0));
    return mailRequest<AdminConnectionList>(`${EXCHANGE_ADMIN_BASE}/connections?${query.toString()}`);
  },
  disconnect: (id: number) => mailRequest<{ ok: true }>(`${EXCHANGE_ADMIN_BASE}/connections/${id}`, json("DELETE")),
  overview: () => mailRequest<ExchangeOverview>(`${EXCHANGE_ADMIN_BASE}/overview`),
  /** The model catalog the Memory settings pick from too; `detection_model` holds a row's id as text. */
  models: () => mailRequest<CatalogModel[]>("/api/admin/models"),
};

/** Only http(s) links from the server become links (an Outlook on the web address). */
export function safeOwaUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** Draft cards from the stream or stored metadata; anything malformed is dropped. */
export function readMailDraftCards(value: unknown): MailDraftCard[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const cards: MailDraftCard[] = [];
  const kinds: DraftKind[] = ["new", "reply", "reply_all", "forward"];
  const addresses = (raw: unknown): MailAddress[] =>
    Array.isArray(raw)
      ? raw
          .filter((a): a is Record<string, unknown> => !!a && typeof a === "object")
          .map((a) => ({ name: typeof a.name === "string" ? a.name : "", email: typeof a.email === "string" ? a.email : "" }))
          .filter((a) => a.email)
      : [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const raw = item as Record<string, unknown>;
    if (typeof raw.id !== "number" || !Number.isInteger(raw.id) || raw.id <= 0) continue;
    if (cards.some((c) => c.id === raw.id)) continue;
    const kind = kinds.includes(raw.kind as DraftKind) ? (raw.kind as DraftKind) : "new";
    cards.push({
      id: raw.id,
      mailbox: typeof raw.mailbox === "string" ? raw.mailbox : "",
      kind,
      subject: typeof raw.subject === "string" ? raw.subject : "",
      to: addresses(raw.to),
      cc: addresses(raw.cc),
      preview: typeof raw.preview === "string" ? raw.preview : "",
    });
    if (cards.length >= 10) break;
  }
  return cards.length ? cards : undefined;
}
