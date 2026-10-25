/**
 * @vitest-environment happy-dom
 *
 * Connections (the person's Exchange mailbox): every state of the page (not
 * eligible, not connected, connected with mailboxes, password needed, error,
 * the status not readable), connecting and each refusal, Update password,
 * Disconnect behind a confirmation, adding / removing / switching mailboxes,
 * Find again, the notification switch, what the administrator's switches hide,
 * and the "Waiting for your action" list with its four buttons.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../api", () => ({ authFetch: vi.fn(), bootstrapSession: vi.fn(() => Promise.resolve({})) }));
const readOnly = vi.hoisted(() => ({ value: false }));
vi.mock("../../context/ReadOnlyContext", () => ({ useReadOnly: () => readOnly.value }));
const dialogs = vi.hoisted(() => ({
  confirm: vi.fn(async () => true as boolean | "secondary"),
  prompt: vi.fn(async () => null as string | null),
}));
vi.mock("../../context/ConfirmContext", () => ({ useConfirm: () => dialogs }));

import { authFetch, bootstrapSession } from "../../api";
import { takeChatPrefill } from "../../lib/chatPrefill";
import {
  MAIL_CHANGED_EVENT,
  type ActionItem,
  type MailCapabilities,
  type MailConnection,
  type MailStatus,
  type Mailbox,
} from "../../lib/exchangeMail";
import Connections from "./Connections";

const MIN = 60_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString().replace(/\.\d+Z$/, "Z");

const CAPS: MailCapabilities = {
  full_access: true,
  manual_mailboxes: true,
  drafts: true,
  send: true,
  free_time: true,
  notifications: true,
  max_mailboxes: 10,
};

const OWN: Mailbox = {
  id: 1,
  smtp: "s.karimi@corp.example",
  display_name: "Sara Karimi",
  kind: "own",
  source: "own",
  enabled: true,
  notify: true,
  verified_at: iso(-60 * MIN),
  last_error: null,
};
const FINANCE: Mailbox = {
  id: 2,
  smtp: "finance@corp.example",
  display_name: "Finance",
  kind: "full_access",
  source: "autodiscover",
  enabled: true,
  notify: false,
  verified_at: iso(-60 * MIN),
  last_error: null,
};
const OPS: Mailbox = {
  id: 3,
  smtp: "ops@corp.example",
  display_name: "",
  kind: "full_access",
  source: "manual",
  enabled: false,
  notify: false,
  verified_at: iso(-60 * MIN),
  last_error: "You no longer have access to this mailbox.",
};

const CONNECTION: MailConnection = {
  status: "connected",
  login: "CORP\\s.karimi",
  primary_smtp: "s.karimi@corp.example",
  display_name: "Sara Karimi",
  last_error: null,
  last_ok_at: iso(-5 * MIN),
  last_checked_at: iso(-5 * MIN),
  connected_at: iso(-24 * 60 * MIN),
  notify_enabled: true,
  mailboxes: [OWN, FINANCE, OPS],
};

const BASE: MailStatus = {
  eligible: true,
  reason: "",
  message: "",
  login: "CORP\\s.karimi",
  email: "s.karimi@corp.example",
  connection: null,
  capabilities: CAPS,
  pending_actions: 0,
};

const CONNECTED: MailStatus = { ...BASE, connection: CONNECTION, pending_actions: 2 };

const ITEM: ActionItem = {
  id: 7,
  mailbox: "s.karimi@corp.example",
  subject: "Budget approval for Q4",
  sender_name: "Ali Rezaei",
  sender_email: "a.rezaei@corp.example",
  received_at: iso(-25 * MIN),
  reason: "Asks you to approve",
  action: "approve",
  importance: "High",
  status: "new",
  owa_url: "https://mail.corp.example/owa/?ItemID=AAMk",
  created_at: iso(-20 * MIN),
};
const ITEM_2: ActionItem = {
  ...ITEM,
  id: 8,
  mailbox: "finance@corp.example",
  subject: "",
  sender_name: null,
  sender_email: "billing@vendor.example",
  reason: "Asks you a question",
  action: "reply",
  importance: "Normal",
  status: "notified",
  owa_url: "javascript:alert(1)",
};

type Call = { url: string; method: string; body: unknown };
type Handler = (url: string, method: string, body: unknown) => Response | undefined;

let host: HTMLDivElement;
let root: Root;
let calls: Call[];
let handler: Handler;
let status: MailStatus;
/** The open items as the server holds them: Done and Dismiss take theirs off. */
let openItems: ActionItem[];
let announced: number;

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
const refusal = (code: number, errorCode: string, message = "Refused.") =>
  json({ detail: { code: errorCode, message } }, code);

function defaults(url: string, method: string): Response {
  if (url === "/api/mail/status") return json(status);
  if (url.startsWith("/api/mail/action-items?")) return json({ items: openItems, open_count: openItems.length });
  const closed = /^\/api\/mail\/action-items\/(\d+)\/(done|dismiss)$/.exec(url);
  if (closed && method === "POST") {
    const item = openItems.find((i) => i.id === Number(closed[1]));
    openItems = openItems.filter((i) => i.id !== Number(closed[1]));
    return json({ ...item, status: closed[2] === "done" ? "done" : "dismissed" });
  }
  return json({});
}

const onAnnounce = () => {
  announced += 1;
};

beforeEach(() => {
  readOnly.value = false;
  status = CONNECTED;
  openItems = [ITEM, ITEM_2];
  dialogs.confirm.mockReset();
  dialogs.confirm.mockResolvedValue(true);
  calls = [];
  announced = 0;
  handler = () => undefined;
  takeChatPrefill();
  vi.mocked(bootstrapSession).mockClear();
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockImplementation(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    return handler(url, method, body) ?? defaults(url, method);
  });
  window.addEventListener(MAIL_CHANGED_EVENT, onAnnounce);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.removeEventListener(MAIL_CHANGED_EVENT, onAnnounce);
});

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.hash}</output>;
}

async function render(path = "/app/connections") {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/app/connections" element={<Connections />} />
          <Route path="/admin/my-connections" element={<Connections />} />
          <Route path="/app/chat" element={<p>chat page</p>} />
          <Route path="/admin/chat" element={<p>admin chat page</p>} />
        </Routes>
        <Where />
      </MemoryRouter>,
    );
  });
  await settle();
}

async function settle() {
  for (let i = 0; i < 5; i += 1) await act(async () => undefined);
}

const text = () => document.body.textContent ?? "";
const where = () => document.querySelector('[data-testid="where"]')?.textContent;
const button = (name: string | RegExp, scope: ParentNode = document) =>
  [...scope.querySelectorAll<HTMLButtonElement>("button")].find((b) =>
    typeof name === "string" ? b.textContent?.trim() === name || b.getAttribute("aria-label") === name : name.test(b.textContent ?? ""),
  );
const byLabel = <T extends HTMLElement>(label: string) => {
  const el = [...document.querySelectorAll("label")].find((l) => l.textContent?.trim() === label);
  return document.getElementById(el?.htmlFor ?? "") as T;
};
const switchFor = (label: string) => document.querySelector<HTMLButtonElement>(`[role="switch"][aria-label="${label}"]`);
const posts = (url: string) => calls.filter((c) => c.url === url && c.method !== "GET");
const alerts = () => [...document.querySelectorAll('[role="alert"]')].map((a) => a.textContent ?? "");

async function click(el: Element | null | undefined) {
  expect(el, "element to click").toBeTruthy();
  await act(async () => {
    (el as HTMLElement).click();
  });
  await settle();
}

async function type(el: HTMLInputElement, value: string) {
  expect(el, "field to type in").toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit(form: HTMLFormElement | null) {
  expect(form).toBeTruthy();
  await act(async () => {
    form!.requestSubmit();
  });
  await settle();
}

describe("not eligible", () => {
  it("shows the server's reason and nothing else", async () => {
    status = {
      ...BASE,
      eligible: false,
      reason: "not_ad",
      message: "Only accounts that sign in with Active Directory can connect an Exchange mailbox.",
    };
    await render();
    expect(document.querySelector("h1")?.textContent).toBe("Connections");
    expect(text()).toContain("Exchange mailbox");
    expect(text()).toContain("Only accounts that sign in with Active Directory can connect an Exchange mailbox.");
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(button("Connect")).toBeUndefined();
    expect(calls.map((c) => c.url)).toEqual(["/api/mail/status"]);
    expect(button("Disconnect")).toBeUndefined();
  });

  it("lets a person no longer allowed remove the password still stored", async () => {
    status = {
      ...BASE,
      eligible: false,
      reason: "not_permitted",
      message: "Your administrator has not given you the Exchange mailbox.",
      connection: CONNECTION,
    };
    await render();
    expect(text()).toContain("Your administrator has not given you the Exchange mailbox.");
    expect(text()).toContain("s.karimi@corp.example");
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(document.querySelector(".mail-mailbox-table")).toBeNull();
    expect(document.querySelector(".mail-actions")).toBeNull();

    dialogs.confirm.mockResolvedValueOnce(false);
    await click(button("Disconnect"));
    expect(dialogs.confirm).toHaveBeenCalledWith(expect.objectContaining({ title: "Disconnect mailbox", danger: true }));
    expect(posts("/api/mail/connection")).toHaveLength(0);

    handler = (url, method) => (url === "/api/mail/connection" && method === "DELETE" ? json({ ok: true }) : undefined);
    await click(button("Disconnect"));
    expect(posts("/api/mail/connection")).toEqual([{ url: "/api/mail/connection", method: "DELETE", body: undefined }]);
    expect(text()).toContain("Your mailbox is disconnected.");
    expect(text()).not.toContain("still stored");
    expect(button("Disconnect")).toBeUndefined();
    expect(button("Connect")).toBeUndefined();
  });

  it("says why the stored password could not be removed", async () => {
    status = { ...BASE, eligible: false, reason: "feature_off", message: "Exchange EWS is off.", connection: CONNECTION };
    handler = (url, method) =>
      url === "/api/mail/connection" && method === "DELETE" ? json({ detail: "Database busy" }, 503) : undefined;
    await render();
    await click(button("Disconnect"));
    expect(alerts().join(" ")).toContain("Database busy");
    expect(button("Disconnect")).toBeTruthy();
  });

  it("keeps Disconnect off for an inactive account", async () => {
    readOnly.value = true;
    status = { ...BASE, eligible: false, reason: "not_ad", message: "Not AD.", connection: CONNECTION };
    await render();
    expect(button("Disconnect")?.disabled).toBe(true);
  });
});

describe("not connected", () => {
  beforeEach(() => {
    status = BASE;
  });

  it("says what connecting allows and asks for the password of the login it shows", async () => {
    await render();
    for (const line of [
      "Read and search your email",
      "Summarise emails and threads",
      "Draft new emails, replies and forwards",
      "Find a free time to meet",
      "Nothing is sent without you.",
      "Your password is stored encrypted and used only to reach your mailbox. If you change your AD password, enter the new one here.",
    ]) {
      expect(text()).toContain(line);
    }
    const login = byLabel<HTMLInputElement>("User name");
    expect(login.value).toBe("CORP\\s.karimi");
    expect(login.readOnly).toBe(true);
    const password = byLabel<HTMLInputElement>("Password");
    expect(password.type).toBe("password");
    expect(button("Connect")?.disabled).toBe(true);
    // Only what the administrator allows is promised.
    expect(calls.some((c) => c.url.startsWith("/api/mail/action-items"))).toBe(false);
  });

  it("leaves out drafting and meeting times when they are off", async () => {
    status = { ...BASE, capabilities: { ...CAPS, drafts: false, free_time: false } };
    await render();
    expect(text()).not.toContain("Draft new emails");
    expect(text()).not.toContain("Find a free time");
  });

  it("connects, shows the mailbox and re-reads the session", async () => {
    handler = (url, method) => {
      if (url === "/api/mail/connect" && method === "POST") return json(CONNECTION);
      return undefined;
    };
    await render();
    const password = byLabel<HTMLInputElement>("Password");
    await type(password, "s3cret!");
    expect(button("Connect")?.disabled).toBe(false);
    await click(button("Connect"));
    expect(posts("/api/mail/connect")).toEqual([{ url: "/api/mail/connect", method: "POST", body: { password: "s3cret!" } }]);
    expect(text()).toContain("Your mailbox is connected.");
    expect(text()).toContain("finance@corp.example");
    expect(document.querySelector(".mail-status")?.textContent).toBe("Connected");
    expect(bootstrapSession).toHaveBeenCalledWith(true);
    expect(announced).toBeGreaterThan(0);
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(calls.some((c) => c.url === "/api/mail/action-items?state=open&limit=50")).toBe(true);
  });

  const refusals: [string, number, string][] = [
    ["exchange_auth", 400, "Exchange did not accept this password. Check it and try again."],
    ["mailbox_mismatch", 400, "This password opens a different mailbox than yours."],
    ["too_many_attempts", 429, "Too many tries. Wait 15 minutes, then try again."],
    ["exchange_unreachable", 502, "Alpharouter cannot reach the Exchange server."],
    ["exchange_tls", 502, "The Exchange server's certificate is not trusted. Tell your administrator."],
    ["not_eligible", 403, "Your administrator has not allowed you to connect a mailbox."],
  ];

  it.each(refusals)("shows %s inline and clears the password", async (code, httpStatus, expected) => {
    handler = (url, method) =>
      url === "/api/mail/connect" && method === "POST"
        ? refusal(httpStatus, code, "Your administrator has not allowed you to connect a mailbox.")
        : undefined;
    await render();
    const password = byLabel<HTMLInputElement>("Password");
    await type(password, "wrong");
    await submit(password.form);
    expect(alerts().join(" ")).toContain(expected);
    expect(byLabel<HTMLInputElement>("Password").value).toBe("");
    // Only a refusal that may have changed the connection re-reads the session.
    expect(vi.mocked(bootstrapSession).mock.calls.length > 0).toBe(code === "exchange_auth" || code === "not_eligible");
    expect(text()).not.toContain("Your mailbox is connected.");
  });

  it("reads the status again after a refused password or a lost eligibility", async () => {
    handler = (url, method) => (url === "/api/mail/connect" && method === "POST" ? refusal(400, "exchange_auth") : undefined);
    await render();
    const before = calls.filter((c) => c.url === "/api/mail/status").length;
    const password = byLabel<HTMLInputElement>("Password");
    await type(password, "wrong");
    await submit(password.form);
    expect(calls.filter((c) => c.url === "/api/mail/status").length).toBe(before + 1);
  });

  it("cannot connect from an inactive account", async () => {
    readOnly.value = true;
    await render();
    expect(byLabel<HTMLInputElement>("Password").disabled).toBe(true);
    expect(button("Connect")?.disabled).toBe(true);
  });
});

describe("connected", () => {
  it("shows the status, the mailbox, the login and the last check", async () => {
    await render();
    expect(document.querySelector(".mail-status")?.textContent).toBe("Connected");
    const identity = document.querySelector(".mail-identity")!.textContent ?? "";
    expect(identity).toContain("s.karimi@corp.example");
    expect(identity).toContain("Sara Karimi");
    expect(identity).toContain("Signed in as CORP\\s.karimi");
    expect(identity).toContain("Last checked 5 min ago");
    expect(button("Update password")).toBeTruthy();
    expect(button("Disconnect")).toBeTruthy();
    expect(switchFor("Tell me about emails that need my action")?.getAttribute("aria-checked")).toBe("true");
  });

  it("lists the mailboxes with their type, source, switches and errors", async () => {
    await render();
    const rows = [...document.querySelectorAll<HTMLTableRowElement>(".mail-mailbox-table tbody tr")];
    expect(rows).toHaveLength(3);
    const cells = (row: HTMLTableRowElement) => [...row.cells].map((c) => c.textContent?.trim());
    expect(cells(rows[0]).slice(0, 4)).toEqual(["s.karimi@corp.example" + "Sara Karimi", "Own", "Your account", "Always"]);
    expect(cells(rows[1]).slice(1, 3)).toEqual(["Full access", "Autodiscover"]);
    expect(cells(rows[2]).slice(1, 3)).toEqual(["Full access", "Added by you"]);
    expect(rows[2].textContent).toContain("You no longer have access to this mailbox.");
    // Own: always on in the chat, never removed.
    expect(switchFor("Use s.karimi@corp.example in chat")).toBeNull();
    expect(button("Remove s.karimi@corp.example")).toBeUndefined();
    expect(switchFor("Use finance@corp.example in chat")?.getAttribute("aria-checked")).toBe("true");
    expect(switchFor("Use ops@corp.example in chat")?.getAttribute("aria-checked")).toBe("false");
    expect(switchFor("Notify about emails in s.karimi@corp.example")?.getAttribute("aria-checked")).toBe("true");
    expect(switchFor("Notify about emails in finance@corp.example")?.getAttribute("aria-checked")).toBe("false");
    expect(button("Remove finance@corp.example")).toBeTruthy();
    expect(button("Remove ops@corp.example")).toBeTruthy();
    expect(text()).toContain("3 of 10");
  });

  it("asks for the password again when Exchange refused the saved one", async () => {
    status = { ...CONNECTED, connection: { ...CONNECTION, status: "needs_password" } };
    await render();
    expect(document.querySelector(".mail-status")?.textContent).toBe("Password needed");
    expect(text()).toContain("Exchange did not accept your saved password.");
    expect(byLabel<HTMLInputElement>("Password")).toBeTruthy();
    expect(button("Cancel")).toBeUndefined();
    expect(button("Update password")).toBeUndefined();
  });

  it("shows the last error", async () => {
    status = {
      ...CONNECTED,
      connection: { ...CONNECTION, status: "error", last_error: "Alpharouter cannot reach the Exchange server." },
    };
    await render();
    expect(document.querySelector(".mail-status")?.textContent).toBe("Error");
    expect(text()).toContain("Alpharouter cannot reach the Exchange server.");
  });

  it("updates the password inline", async () => {
    handler = (url, method) => (url === "/api/mail/connect" && method === "POST" ? json(CONNECTION) : undefined);
    await render();
    await click(button("Update password"));
    expect(button("Cancel")).toBeTruthy();
    await type(byLabel<HTMLInputElement>("Password"), "n3w");
    await click(button("Save password"));
    expect(posts("/api/mail/connect")[0].body).toEqual({ password: "n3w" });
    expect(text()).toContain("Password saved. Your mailbox is connected.");
    expect(byLabel<HTMLInputElement>("Password")).toBeNull();
    expect(bootstrapSession).toHaveBeenCalledWith(true);
  });

  it("closes the password form on Cancel", async () => {
    await render();
    await click(button("Update password"));
    await click(button("Cancel"));
    expect(byLabel<HTMLInputElement>("Password")).toBeNull();
    expect(posts("/api/mail/connect")).toHaveLength(0);
  });

  it("disconnects only after the confirmation", async () => {
    dialogs.confirm.mockResolvedValueOnce(false);
    await render();
    await click(button("Disconnect"));
    expect(dialogs.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Disconnect mailbox", danger: true, confirmLabel: "Disconnect" }),
    );
    expect(posts("/api/mail/connection")).toHaveLength(0);

    handler = (url, method) => (url === "/api/mail/connection" && method === "DELETE" ? json({ ok: true }) : undefined);
    await click(button("Disconnect"));
    expect(posts("/api/mail/connection")).toEqual([{ url: "/api/mail/connection", method: "DELETE", body: undefined }]);
    expect(text()).toContain("Your mailbox is disconnected.");
    expect(button("Connect")).toBeTruthy();
    expect(document.querySelector(".mail-actions")).toBeNull();
    expect(bootstrapSession).toHaveBeenCalledWith(true);
    expect(announced).toBeGreaterThan(0);
  });

  it("turns the notifications off", async () => {
    handler = (url, method) =>
      url === "/api/mail/connection" && method === "PATCH" ? json({ ...CONNECTION, notify_enabled: false }) : undefined;
    await render();
    await click(switchFor("Tell me about emails that need my action"));
    expect(posts("/api/mail/connection")[0]).toEqual({
      url: "/api/mail/connection",
      method: "PATCH",
      body: { notify_enabled: false },
    });
    expect(switchFor("Tell me about emails that need my action")?.getAttribute("aria-checked")).toBe("false");
    expect(announced).toBeGreaterThan(0);
  });

  it("reads the status again when the refusal says it is out of date", async () => {
    handler = (url, method) =>
      url === "/api/mail/connection" && method === "PATCH" ? refusal(409, "needs_password") : undefined;
    await render();
    await click(switchFor("Tell me about emails that need my action"));
    expect(alerts().join(" ")).toContain("Your password is needed again.");
    expect(calls.filter((c) => c.url === "/api/mail/status")).toHaveLength(2);
    expect(bootstrapSession).toHaveBeenCalledWith(true);
  });

  it("offers a retry when the status cannot be read", async () => {
    let fail = true;
    handler = (url) => (url === "/api/mail/status" && fail ? json({ detail: "Service unavailable" }, 503) : undefined);
    await render();
    expect(alerts().join(" ")).toContain("Service unavailable");
    fail = false;
    await click(button("Try again"));
    expect(document.querySelector(".mail-status")?.textContent).toBe("Connected");
  });

  it("disables every change for an inactive account", async () => {
    readOnly.value = true;
    await render();
    expect(button("Update password")?.disabled).toBe(true);
    expect(button("Disconnect")?.disabled).toBe(true);
    expect(switchFor("Use finance@corp.example in chat")?.disabled).toBe(true);
    expect(button("Remove finance@corp.example")?.disabled).toBe(true);
    expect(button("Ask Alpharouter")?.disabled).toBe(true);
  });
});

describe("mailboxes", () => {
  it("adds a mailbox by address", async () => {
    const SHARED: Mailbox = { ...OPS, id: 4, smtp: "shared@corp.example", enabled: true, last_error: null };
    handler = (url, method) =>
      url === "/api/mail/mailboxes" && method === "POST"
        ? json({ ...CONNECTION, mailboxes: [...CONNECTION.mailboxes, SHARED] })
        : undefined;
    await render();
    const field = byLabel<HTMLInputElement>("Add a mailbox");
    await type(field, "  shared@corp.example ");
    await click(button("Add"));
    expect(posts("/api/mail/mailboxes")[0].body).toEqual({ smtp: "shared@corp.example" });
    expect(document.querySelectorAll(".mail-mailbox-table tbody tr")).toHaveLength(4);
    expect(text()).toContain("shared@corp.example was added.");
    expect(byLabel<HTMLInputElement>("Add a mailbox").value).toBe("");
    expect(announced).toBeGreaterThan(0);
  });

  const refusals: [string, number, string][] = [
    ["invalid_address", 422, "That is not a valid email address."],
    ["already_added", 409, "This mailbox is already in your list."],
    ["too_many_mailboxes", 422, "You can have at most 10 mailboxes. Remove one first."],
    ["exchange_access_denied", 403, "You do not have access to this mailbox. Ask your Exchange administrator for Full Access."],
    ["exchange_not_found", 404, "No mailbox was found at this address."],
    ["manual_mailboxes_off", 403, "Adding mailboxes yourself is turned off by your administrator."],
    ["exchange_auth", 400, "Exchange no longer accepts your saved password."],
  ];

  it.each(refusals)("shows %s when adding", async (code, httpStatus, expected) => {
    handler = (url, method) => (url === "/api/mail/mailboxes" && method === "POST" ? refusal(httpStatus, code) : undefined);
    await render();
    await type(byLabel<HTMLInputElement>("Add a mailbox"), "x@corp.example");
    await click(button("Add"));
    expect(alerts().join(" ")).toContain(expected);
    // The address stays for the person to fix.
    expect(byLabel<HTMLInputElement>("Add a mailbox").value).toBe("x@corp.example");
  });

  it("reads the status again after the saved password was refused", async () => {
    handler = (url, method) =>
      url === "/api/mail/mailboxes" && method === "POST" ? refusal(400, "exchange_auth") : undefined;
    await render();
    await type(byLabel<HTMLInputElement>("Add a mailbox"), "x@corp.example");
    await click(button("Add"));
    expect(calls.filter((c) => c.url === "/api/mail/status")).toHaveLength(2);
  });

  it("removes a mailbox after the confirmation", async () => {
    handler = (url, method) =>
      url === "/api/mail/mailboxes/2" && method === "DELETE"
        ? json({ ...CONNECTION, mailboxes: [OWN, OPS] })
        : undefined;
    await render();
    dialogs.confirm.mockResolvedValueOnce(false);
    await click(button("Remove finance@corp.example"));
    expect(posts("/api/mail/mailboxes/2")).toHaveLength(0);

    await click(button("Remove finance@corp.example"));
    expect(dialogs.confirm).toHaveBeenLastCalledWith(
      expect.objectContaining({ title: "Remove mailbox", danger: true, confirmLabel: "Remove" }),
    );
    expect(posts("/api/mail/mailboxes/2")[0].method).toBe("DELETE");
    expect(document.querySelectorAll(".mail-mailbox-table tbody tr")).toHaveLength(2);
    expect(text()).toContain("finance@corp.example was removed.");
  });

  it("switches Use in chat and Notify for one mailbox", async () => {
    handler = (url, method, body) => {
      if (url === "/api/mail/mailboxes/2" && method === "PATCH") {
        const patch = body as { enabled?: boolean; notify?: boolean };
        return json({ ...CONNECTION, mailboxes: [OWN, { ...FINANCE, ...patch }, OPS] });
      }
      return undefined;
    };
    await render();
    await click(switchFor("Use finance@corp.example in chat"));
    expect(posts("/api/mail/mailboxes/2").at(-1)?.body).toEqual({ enabled: false });
    expect(switchFor("Use finance@corp.example in chat")?.getAttribute("aria-checked")).toBe("false");
    await click(switchFor("Notify about emails in finance@corp.example"));
    expect(posts("/api/mail/mailboxes/2").at(-1)?.body).toEqual({ notify: true });
  });

  it("says why the own mailbox cannot change", async () => {
    handler = (url, method) =>
      url === "/api/mail/mailboxes/1" && method === "PATCH" ? refusal(422, "own_mailbox") : undefined;
    await render();
    await click(switchFor("Notify about emails in s.karimi@corp.example"));
    expect(alerts().join(" ")).toContain("Your own mailbox cannot be turned off or removed.");
  });

  it("finds the Full Access mailboxes again and says what changed", async () => {
    const HR: Mailbox = { ...FINANCE, id: 5, smtp: "hr@corp.example", display_name: "HR" };
    handler = (url, method) =>
      url === "/api/mail/mailboxes/rediscover" && method === "POST"
        ? json({ ...CONNECTION, mailboxes: [OWN, HR, OPS] })
        : undefined;
    await render();
    await click(button("Find again"));
    expect(posts("/api/mail/mailboxes/rediscover")).toHaveLength(1);
    expect(text()).toContain("Found 1 new mailbox. 1 mailbox is no longer shared with you and was removed.");
    expect(text()).toContain("hr@corp.example");
  });

  it("hides Add, Find again and Notify when the administrator turned them off", async () => {
    status = {
      ...CONNECTED,
      capabilities: { ...CAPS, manual_mailboxes: false, full_access: false, notifications: false },
    };
    await render();
    expect(byLabel("Add a mailbox")).toBeNull();
    expect(button("Find again")).toBeUndefined();
    expect(switchFor("Tell me about emails that need my action")).toBeNull();
    expect(switchFor("Notify about emails in s.karimi@corp.example")).toBeNull();
    expect(document.querySelector(".mail-actions")).toBeNull();
    expect(calls.some((c) => c.url.startsWith("/api/mail/action-items"))).toBe(false);
  });
});

describe("waiting for your action", () => {
  const list = () => [...document.querySelectorAll<HTMLLIElement>(".mail-action")];

  it("lists the open emails with sender, subject, reason and when", async () => {
    await render();
    expect(calls.some((c) => c.url === "/api/mail/action-items?state=open&limit=50")).toBe(true);
    const [first, second] = list();
    expect(first.textContent).toContain("Budget approval for Q4");
    expect(first.textContent).toContain("Important");
    expect(first.textContent).toContain("Ali Rezaei");
    expect(first.textContent).toContain("25 min ago");
    expect(first.textContent).toContain("Asks you to approve");
    expect(first.textContent).not.toContain("s.karimi@corp.example");
    expect(second.textContent).toContain("(no subject)");
    expect(second.textContent).toContain("billing@vendor.example");
    expect(second.textContent).toContain("finance@corp.example");
    expect(document.querySelector(".mail-count")?.textContent).toBe("2");
  });

  it("links to Outlook only with a web address, in a new tab without the opener", async () => {
    await render();
    const [first, second] = list();
    const link = first.querySelector<HTMLAnchorElement>("a")!;
    expect(link.textContent).toBe("Open in Outlook");
    expect(link.href).toBe("https://mail.corp.example/owa/?ItemID=AAMk");
    expect(link.target).toBe("_blank");
    expect(link.rel).toBe("noopener noreferrer");
    expect(second.querySelector("a")).toBeNull();
  });

  it("marks an email done and takes it off the list", async () => {
    await render();
    await click(button("Done", list()[0]));
    expect(posts("/api/mail/action-items/7/done")).toHaveLength(1);
    expect(list()).toHaveLength(1);
    expect(list()[0].textContent).not.toContain("Budget approval");
    expect(announced).toBeGreaterThan(0);
  });

  it("dismisses an email", async () => {
    await render();
    await click(button("Dismiss", list()[1]));
    expect(posts("/api/mail/action-items/8/dismiss")).toHaveLength(1);
    expect(list()).toHaveLength(1);
    expect(list()[0].textContent).toContain("Budget approval");
  });

  it("keeps the email and says why when Done is refused", async () => {
    handler = (url, method) =>
      url === "/api/mail/action-items/7/done" && method === "POST" ? json({ detail: "Not found" }, 404) : undefined;
    await render();
    await click(button("Done", list()[0]));
    expect(list()).toHaveLength(2);
    expect(alerts().join(" ")).toContain("Not found");
  });

  it("asks Alpharouter: the prompt waits for a new chat and the chat opens", async () => {
    const prompt = 'Help me with this email (ref m7Q2xY): "Budget approval for Q4" from Ali Rezaei.';
    handler = (url, method) =>
      url === "/api/mail/action-items/7/ask" && method === "POST" ? json({ prompt }) : undefined;
    await render();
    await click(button("Ask Alpharouter", list()[0]));
    expect(posts("/api/mail/action-items/7/ask")).toHaveLength(1);
    expect(where()).toBe("/app/chat");
    expect(text()).toContain("chat page");
    expect(takeChatPrefill()).toBe(prompt);
  });

  it("asks from the admin panel and opens the admin panel's chat", async () => {
    handler = (url, method) =>
      url === "/api/mail/action-items/7/ask" && method === "POST" ? json({ prompt: "Help me" }) : undefined;
    await render("/admin/my-connections");
    await click(button("Ask Alpharouter", list()[0]));
    expect(where()).toBe("/admin/chat");
    expect(text()).toContain("admin chat page");
    expect(takeChatPrefill()).toBe("Help me");
  });

  it("says why Ask did not work and opens nothing", async () => {
    handler = (url, method) =>
      url === "/api/mail/action-items/7/ask" && method === "POST" ? refusal(409, "needs_password") : undefined;
    await render();
    await click(button("Ask Alpharouter", list()[0]));
    expect(alerts().join(" ")).toContain("Your password is needed again.");
    expect(where()).toBe("/app/connections");
    expect(takeChatPrefill()).toBeNull();
    expect(calls.filter((c) => c.url === "/api/mail/status")).toHaveLength(2);
  });

  it("says when nothing is waiting, and why when notifications are off", async () => {
    openItems = [];
    await render();
    expect(text()).toContain("Nothing is waiting for you.");

    act(() => root.unmount());
    root = createRoot(host);
    status = { ...CONNECTED, connection: { ...CONNECTION, notify_enabled: false } };
    await render();
    expect(text()).toContain("Turn on “Tell me about emails that need my action” above");
  });

  it("reads the list again when the mail changed elsewhere (a toast's Dismiss)", async () => {
    await render();
    const before = calls.filter((c) => c.url.startsWith("/api/mail/action-items?")).length;
    await act(async () => {
      window.dispatchEvent(new Event(MAIL_CHANGED_EVENT));
    });
    await settle();
    expect(calls.filter((c) => c.url.startsWith("/api/mail/action-items?")).length).toBe(before + 1);
  });

  it("scrolls to the list when opened from the N more toast", async () => {
    const scrolled = vi.fn();
    const original = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrolled;
    try {
      await render("/admin/my-connections#mail-actions");
      expect(scrolled).toHaveBeenCalled();
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });
});
