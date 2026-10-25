/**
 * Fixtures and a fake admin API for the Exchange EWS page tests: one place
 * that answers `/api/admin/exchange-ews/*` (and the model catalog) the way the
 * contract says, and records every call so a test can read what was sent.
 */
import type {
  AdminConnection,
  CatalogModel,
  ExchangeOverview,
  ExchangeSettingsResponse,
  TestResult,
  ToolAccess,
} from "../../lib/exchangeMail";

const NOW = Date.now();
const minutesAgo = (n: number) => new Date(NOW - n * 60_000).toISOString().replace(/\.\d+Z$/, "Z");

export function makeSettings(over: Partial<ExchangeSettingsResponse["settings"]> = {}): ExchangeSettingsResponse {
  return {
    settings: {
      enabled: true,
      ews_url: "https://mail.corp.example/EWS/Exchange.asmx",
      autodiscover_url: "",
      login_format: "netbios",
      netbios_domain: "",
      upn_suffix: "",
      verify_tls: true,
      ca_bundle_pem: "",
      require_mailbox_match: true,
      allow_full_access: true,
      allow_manual_mailboxes: true,
      allow_drafts: true,
      allow_send: true,
      allow_free_time: true,
      notify_enabled: true,
      poll_minutes: 5,
      detection: "rules",
      detection_model: "",
      search_limit: 25,
      body_chars: 8000,
      timeout_s: 30,
      max_mailboxes: 10,
      action_retention_days: 30,
      ...over,
    },
    directory: { netbios_domain: "CORP", dns_domain: "corp.example", available: true },
    example_login: "CORP\\m.arasskhani",
    ews_endpoint: "https://mail.corp.example/EWS/Exchange.asmx",
    autodiscover_endpoint: "https://mail.corp.example/autodiscover/autodiscover.xml",
  };
}

export const OVERVIEW: ExchangeOverview = {
  counts: { connected: 42, needs_password: 3, error: 1 },
  eligible_accounts: 180,
  action_items_7d: 57,
  drafts_7d: 23,
  sent_7d: 11,
  last_check_at: minutesAgo(3),
  enabled: true,
  configured: true,
};

const ACCESS: ToolAccess = {
  tool_key: "exchange_mail",
  access_type: "public",
  acl_version: 2,
  grants: [],
  updated_at: null,
  updated_by_user_id: null,
};

const MODELS: CatalogModel[] = [
  { id: 7, external_id: "gpt-4o-mini", display_name: "GPT-4o mini", enabled: true, provider: "openai", kinds: ["text"] },
  { id: 8, external_id: "old-model", display_name: "Old model", enabled: false, provider: "openai", kinds: ["text"] },
  { id: 9, external_id: "text-embedding-3-small", display_name: null, enabled: true, provider: "openai", kinds: ["embeddings"] },
];

const TEST_OK: TestResult = {
  ok: true,
  steps: [
    { key: "endpoint", label: "EWS address", ok: true, detail: "https://mail.corp.example/EWS/Exchange.asmx" },
    { key: "login", label: "Sign in", ok: true, detail: "Exchange accepted CORP\\s.karimi" },
    { key: "mailbox", label: "Mailbox", ok: true, detail: "s.karimi@corp.example" },
    { key: "match", label: "Own mailbox", ok: true, detail: "The password opens s.karimi@corp.example" },
    { key: "autodiscover", label: "Full Access mailboxes", ok: true, detail: "2 mailboxes" },
  ],
  mailbox: { smtp: "s.karimi@corp.example", display_name: "Sara Karimi" },
  full_access: [
    { smtp: "finance@corp.example", display_name: "Finance" },
    { smtp: "hr@corp.example", display_name: "Human Resources" },
  ],
};

export const TEST_FAILED: TestResult = {
  ok: false,
  steps: [
    { key: "endpoint", label: "EWS address", ok: true, detail: "https://mail.corp.example/EWS/Exchange.asmx" },
    { key: "login", label: "Sign in", ok: false, detail: "Exchange did not accept the user name or password" },
  ],
  mailbox: null,
  full_access: [],
};

const STATUSES = ["connected", "connected", "connected", "needs_password", "error"] as const;

/** 120 people: Sara Karimi first, then "Person 2" … "Person 120". */
const CONNECTIONS: AdminConnection[] = Array.from({ length: 120 }, (_, i) => {
  const n = i + 1;
  const first = n === 1;
  const status = first ? "connected" : STATUSES[n % STATUSES.length];
  return {
    id: 100 + n,
    user_id: n,
    username: first ? "s.karimi" : `person${n}`,
    display_name: first ? "Sara Karimi" : `Person ${n}`,
    email: first ? "s.karimi@corp.example" : `person${n}@corp.example`,
    login: first ? "CORP\\s.karimi" : `CORP\\person${n}`,
    status,
    primary_smtp: first ? "s.karimi@corp.example" : `person${n}@corp.example`,
    mailbox_count: first ? 3 : 1,
    full_access_count: first ? 2 : 0,
    notify_enabled: true,
    last_ok_at: minutesAgo(5),
    last_checked_at: minutesAgo(5),
    last_error: status === "error" ? "Exchange could not be reached" : null,
    connected_at: minutesAgo(10_000),
  };
});

export type Call = { url: string; method: string; body: unknown };

type Handler = (url: string, method: string, body: unknown) => unknown;

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function connectionsPage(url: string) {
  const query = new URL(url, "http://local").searchParams;
  const q = (query.get("q") ?? "").toLowerCase();
  const status = query.get("status") ?? "";
  const limit = Number(query.get("limit") ?? 50);
  const offset = Number(query.get("offset") ?? 0);
  const rows = CONNECTIONS.filter(
    (row) =>
      (!status || row.status === status) &&
      (!q || [row.username, row.display_name, row.email, row.primary_smtp].some((v) => v?.toLowerCase().includes(q))),
  );
  return { items: rows.slice(offset, offset + limit), total: rows.length };
}

/**
 * A fake `authFetch`: answers the admin API from the fixtures; `override` runs
 * first and may return a Response (an error) or a body.
 */
export function fakeExchangeApi(calls: Call[], override?: Handler, settings: ExchangeSettingsResponse = makeSettings()) {
  let current = settings;
  return async (input: string, init: RequestInit = {}): Promise<Response> => {
    const method = (init.method ?? "GET").toUpperCase();
    let body: unknown = init.body;
    if (typeof init.body === "string") body = JSON.parse(init.body);
    calls.push({ url: input, method, body });
    const path = input.split("?")[0];
    const own = override?.(input, method, body);
    if (own instanceof Response) return own;
    if (own !== undefined) return json(200, own);
    if (path === "/api/admin/models") return json(200, MODELS);
    if (path.endsWith("/exchange-ews/settings")) {
      if (method === "PUT") current = { ...current, settings: body as ExchangeSettingsResponse["settings"] };
      return json(200, current);
    }
    if (path.endsWith("/exchange-ews/overview")) return json(200, OVERVIEW);
    if (path.endsWith("/exchange-ews/test")) return json(200, TEST_OK);
    if (path.endsWith("/exchange-ews/access")) {
      return json(200, method === "PUT" ? { ...ACCESS, ...(body as object), acl_version: 3 } : ACCESS);
    }
    if (/\/exchange-ews\/connections\/\d+$/.test(path) && method === "DELETE") return json(200, { ok: true });
    if (path.endsWith("/exchange-ews/connections")) return json(200, connectionsPage(input));
    return json(404, { detail: "Not found" });
  };
}
