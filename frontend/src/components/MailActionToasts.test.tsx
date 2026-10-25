/**
 * @vitest-environment happy-dom
 *
 * The mail toasts: only while the mailbox is connected and working, a read of
 * the open items on start, every two minutes while the tab is visible and on
 * focus; a toast for each new email (at most three, then "N more"), the server
 * told which were shown, never the same email twice in a tab; Ask Alpharouter
 * and Dismiss on each toast; and a toast closed when its email is handled
 * elsewhere.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../api", () => ({ authFetch: vi.fn() }));
const sessionState = vi.hoisted(() => ({ value: null as Record<string, unknown> | null }));
vi.mock("../hooks/useCachedSession", () => ({ useCachedSession: () => sessionState.value }));

import { authFetch } from "../api";
import { takeChatPrefill } from "../lib/chatPrefill";
import { MAIL_CHANGED_EVENT, type ActionItem } from "../lib/exchangeMail";
import { resetToastHost } from "../lib/toastHost";
import MailActionToasts, { MAIL_POLL_MS, resetMailActionToasts } from "./MailActionToasts";

const LIST_URL = "/api/mail/action-items?state=open&limit=50";

function item(id: number, patch: Partial<ActionItem> = {}): ActionItem {
  return {
    id,
    mailbox: "s.karimi@corp.example",
    subject: `Email ${id}`,
    sender_name: "Ali Rezaei",
    sender_email: "a.rezaei@corp.example",
    received_at: "2026-10-25T08:00:00Z",
    reason: "Asks you to approve",
    action: "approve",
    importance: "Normal",
    status: "new",
    owa_url: null,
    created_at: "2026-10-25T08:01:00Z",
    ...patch,
  };
}

type Call = { url: string; method: string; body: unknown };

let host: HTMLDivElement;
let root: Root;
let calls: Call[];
let openItems: ActionItem[];
let handler: (url: string, method: string) => Response | undefined;
let hidden: boolean;
let announced: number;

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

const onAnnounce = () => {
  announced += 1;
};

beforeEach(() => {
  vi.useFakeTimers();
  resetToastHost();
  resetMailActionToasts();
  takeChatPrefill();
  sessionState.value = { role: "user", features: { connections: true, exchange_mail: true } };
  calls = [];
  announced = 0;
  openItems = [item(1), item(2, { status: "notified" })];
  handler = () => undefined;
  hidden = false;
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockImplementation(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    const custom = handler(url, method);
    if (custom) return custom;
    if (url === LIST_URL) return json({ items: openItems, open_count: openItems.length });
    if (url === "/api/mail/action-items/notified") {
      const ids = (body as { ids: number[] }).ids;
      openItems = openItems.map((i) => (ids.includes(i.id) ? { ...i, status: "notified" } : i));
      return json({ ok: true });
    }
    return json({});
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
  resetToastHost();
  vi.useRealTimers();
});

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.hash}</output>;
}

async function settle() {
  for (let i = 0; i < 6; i += 1) await act(async () => undefined);
}

async function render(path = "/app/media") {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <MailActionToasts />
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await settle();
}

const toasts = () => [...document.querySelectorAll<HTMLElement>(".app-toast")];
const titles = () => toasts().map((t) => t.querySelector(".app-toast__title")?.textContent);
const reads = () => calls.filter((c) => c.url === LIST_URL).length;
const posted = (url: string) => calls.filter((c) => c.url === url && c.method === "POST");
const where = () => document.querySelector('[data-testid="where"]')?.textContent;
const action = (toast: HTMLElement, label: string) =>
  [...toast.querySelectorAll<HTMLButtonElement>(".app-toast__action")].find((b) => b.textContent === label);

async function press(el: HTMLElement | undefined) {
  expect(el, "button to press").toBeTruthy();
  await act(async () => {
    el!.click();
  });
  await settle();
}

describe("when it runs", () => {
  it("does nothing unless the mailbox is connected and working", async () => {
    sessionState.value = { role: "user", features: { connections: true, exchange_mail: false } };
    await render();
    vi.advanceTimersByTime(MAIL_POLL_MS * 2);
    await settle();
    expect(calls).toHaveLength(0);
    expect(toasts()).toHaveLength(0);
  });

  it("reads on start, every two minutes while visible, and on focus", async () => {
    await render();
    expect(reads()).toBe(1);
    await act(async () => {
      vi.advanceTimersByTime(MAIL_POLL_MS);
    });
    await settle();
    expect(reads()).toBe(2);

    // Hidden: the tick is skipped, and made up when the tab shows again.
    hidden = true;
    await act(async () => {
      vi.advanceTimersByTime(MAIL_POLL_MS);
    });
    await settle();
    expect(reads()).toBe(2);
    hidden = false;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await settle();
    expect(reads()).toBe(3);

    await act(async () => {
      vi.advanceTimersByTime(10_000);
      window.dispatchEvent(new Event("focus"));
    });
    await settle();
    expect(reads()).toBe(4);
    // Focus right after another read does not ask again.
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await settle();
    expect(reads()).toBe(4);
  });

  it("stops and closes its toasts when the mailbox stops working", async () => {
    await render();
    expect(toasts()).toHaveLength(1);
    sessionState.value = { role: "user", features: { connections: true, exchange_mail: false } };
    await render();
    expect(toasts()).toHaveLength(0);
    await act(async () => {
      vi.advanceTimersByTime(MAIL_POLL_MS * 2);
    });
    await settle();
    expect(reads()).toBe(1);
  });
});

describe("the toasts", () => {
  it("shows each new email once, with its sender, reason and two actions, and tells the server", async () => {
    await render();
    expect(titles()).toEqual(["Email 1"]);
    const [toast] = toasts();
    expect(toast.textContent).toContain("Needs your action");
    expect(toast.textContent).toContain("Ali Rezaei · Asks you to approve");
    expect([...toast.querySelectorAll(".app-toast__action")].map((b) => b.textContent)).toEqual([
      "Ask Alpharouter",
      "Dismiss",
    ]);
    expect(posted("/api/mail/action-items/notified").map((c) => c.body)).toEqual([{ ids: [1] }]);

    // The next read finds it notified: no second toast, no second call.
    resetToastHost();
    await act(async () => {
      vi.advanceTimersByTime(MAIL_POLL_MS);
    });
    await settle();
    expect(toasts()).toHaveLength(0);
    expect(posted("/api/mail/action-items/notified")).toHaveLength(1);
  });

  it("does not show an email twice in a tab even when the server was not told", async () => {
    handler = (url) => (url === "/api/mail/action-items/notified" ? json({ detail: "busy" }, 503) : undefined);
    await render();
    expect(titles()).toEqual(["Email 1"]);
    resetToastHost();
    await act(async () => {
      vi.advanceTimersByTime(MAIL_POLL_MS);
    });
    await settle();
    expect(toasts()).toHaveLength(0);
  });

  it("shows three emails as three toasts", async () => {
    openItems = [item(1), item(2), item(3)];
    await render();
    expect(titles()).toEqual(["Email 1", "Email 2", "Email 3"]);
    expect(posted("/api/mail/action-items/notified")[0].body).toEqual({ ids: [1, 2, 3] });
  });

  it("keeps to three toasts: past three, the last says how many more", async () => {
    openItems = [item(1), item(2), item(3), item(4), item(5), item(6, { status: "notified" })];
    await render();
    expect(titles()).toEqual(["Email 1", "Email 2", "3 more emails need your action"]);
    expect(posted("/api/mail/action-items/notified")[0].body).toEqual({ ids: [1, 2, 3, 4, 5] });
  });

  it("takes the N more toast to Connections, in the person's panel", async () => {
    openItems = [item(1), item(2), item(3), item(4)];
    await render();
    await press(toasts().find((t) => t.textContent?.includes("more emails need your action")));
    expect(where()).toBe("/app/connections#mail-actions");

    act(() => root.unmount());
    root = createRoot(host);
    resetToastHost();
    resetMailActionToasts();
    openItems = [item(11), item(12), item(13), item(14)];
    sessionState.value = { role: "full_administrator", features: { connections: true, exchange_mail: true } };
    await render("/admin");
    await press(toasts().find((t) => t.textContent?.includes("more emails need your action")));
    expect(where()).toBe("/admin/my-connections#mail-actions");
  });

  it("Ask Alpharouter opens a new chat with the prompt waiting in the composer", async () => {
    const prompt = 'Help me with this email (ref m7Q2xY): "Email 1" from Ali Rezaei.';
    handler = (url, method) => (url === "/api/mail/action-items/1/ask" && method === "POST" ? json({ prompt }) : undefined);
    await render();
    await press(action(toasts()[0], "Ask Alpharouter"));
    expect(posted("/api/mail/action-items/1/ask")).toHaveLength(1);
    expect(toasts()).toHaveLength(0);
    expect(where()).toBe("/app/chat");
    expect(takeChatPrefill()).toBe(prompt);
  });

  it("Ask Alpharouter on the chat page stays there", async () => {
    handler = (url, method) =>
      url === "/api/mail/action-items/1/ask" && method === "POST" ? json({ prompt: "Help me" }) : undefined;
    await render("/admin/chat");
    await press(action(toasts()[0], "Ask Alpharouter"));
    expect(where()).toBe("/admin/chat");
    expect(takeChatPrefill()).toBe("Help me");
  });

  it("says when Ask Alpharouter did not work", async () => {
    handler = (url, method) =>
      url === "/api/mail/action-items/1/ask" && method === "POST"
        ? json({ detail: { code: "needs_password", message: "x" } }, 409)
        : undefined;
    await render();
    await press(action(toasts()[0], "Ask Alpharouter"));
    expect(where()).toBe("/app/media");
    const [failure] = toasts();
    expect(failure.className).toContain("app-toast--danger");
    expect(failure.textContent).toContain("This email could not be opened in a chat.");
    expect(failure.textContent).toContain("Your password is needed again.");
  });

  it("Dismiss closes the email on the server and tells the page", async () => {
    await render();
    await press(action(toasts()[0], "Dismiss"));
    expect(posted("/api/mail/action-items/1/dismiss")).toHaveLength(1);
    expect(announced).toBe(1);
    expect(toasts()).toHaveLength(0);
  });

  it("says when Dismiss did not work", async () => {
    handler = (url, method) =>
      url === "/api/mail/action-items/1/dismiss" && method === "POST" ? json({ detail: "Gone" }, 404) : undefined;
    await render();
    await press(action(toasts()[0], "Dismiss"));
    expect(titles()).toEqual(["This email could not be dismissed."]);
    expect(announced).toBe(0);
  });

  it("closes a toast whose email was handled elsewhere", async () => {
    openItems = [item(1), item(2)];
    await render();
    expect(titles()).toEqual(["Email 1", "Email 2"]);
    openItems = openItems.filter((i) => i.id !== 1);
    await act(async () => {
      window.dispatchEvent(new Event(MAIL_CHANGED_EVENT));
    });
    await settle();
    expect(titles()).toEqual(["Email 2"]);
  });

  it("stays quiet when the list cannot be read", async () => {
    handler = (url) => (url === LIST_URL ? json({ detail: "down" }, 502) : undefined);
    await render();
    expect(toasts()).toHaveLength(0);
    expect(posted("/api/mail/action-items/notified")).toHaveLength(0);
  });
});
