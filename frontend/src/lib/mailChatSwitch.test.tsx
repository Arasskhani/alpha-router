/**
 * @vitest-environment happy-dom
 *
 * The Exchange mailbox in the chat: where the envelope shows (connected, a
 * personal chat, no Agent), the per-chat switch and how it is kept with the
 * chat's stored settings, and the `tools.exchange_mail` flag a turn sends.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const session = vi.hoisted(() => ({
  current: null as Record<string, unknown> | null,
  listeners: new Set<(s: Record<string, unknown>) => void>(),
}));
vi.mock("../api", () => ({
  authFetch: vi.fn(),
  getCachedSession: () => session.current,
  onSessionReady: (listener: (s: Record<string, unknown>) => void) => {
    session.listeners.add(listener);
    if (session.current) listener(session.current);
    return () => session.listeners.delete(listener);
  },
  bootstrapSession: vi.fn(async () => session.current),
}));

import { bootstrapSession } from "../api";
import { copyFreshChatTools, normalizeChatTools, toolsToApiPayload } from "./chatTools";
import { MAIL_CHANGED_EVENT } from "./exchangeMail";
import {
  exchangeMailConnected,
  mailIndicatorShown,
  mailOnForChat,
  mailToolRequested,
  toggleMailForChat,
  useExchangeMailConnected,
  withMailSwitchFrom,
  withMailTool,
} from "./mailChatSwitch";

const personal = { connected: true, projectChat: false, agentMode: false };

describe("where the envelope shows", () => {
  it("needs the server to say the mailbox is connected, in so many words", () => {
    expect(exchangeMailConnected({ username: "s", role: "user", is_active: true, auth_provider: "ldap", features: { exchange_mail: true } })).toBe(true);
    expect(exchangeMailConnected({ username: "s", role: "user", is_active: true, auth_provider: "ldap", features: { exchange_mail: false } })).toBe(false);
    // An older server sends no block, or no key: that is no mailbox, not "unknown means on".
    expect(exchangeMailConnected({ username: "s", role: "user", is_active: true, auth_provider: "ldap", features: {} })).toBe(false);
    expect(exchangeMailConnected({ username: "s", role: "user", is_active: true, auth_provider: "ldap" })).toBe(false);
    expect(exchangeMailConnected({ username: "s", role: "user", is_active: true, auth_provider: "ldap", features: { exchange_mail: "yes" } })).toBe(false);
    expect(exchangeMailConnected(null)).toBe(false);
  });

  it("shows in a personal chat only: not in a project chat, not with an Agent, not without a mailbox", () => {
    expect(mailIndicatorShown(personal)).toBe(true);
    expect(mailIndicatorShown({ ...personal, connected: false })).toBe(false);
    expect(mailIndicatorShown({ ...personal, projectChat: true })).toBe(false);
    expect(mailIndicatorShown({ ...personal, agentMode: true })).toBe(false);
  });
});

describe("the per-chat switch", () => {
  it("is on in a new chat and turns off and on again", () => {
    const fresh = copyFreshChatTools();
    expect(mailOnForChat(fresh)).toBe(true);
    const off = toggleMailForChat(fresh);
    expect(off.mailOff).toBe(true);
    expect(mailOnForChat(off)).toBe(false);
    const on = toggleMailForChat(off);
    expect(mailOnForChat(on)).toBe(true);
    // Back on, the chat's settings read as if never touched.
    expect(on).toEqual(fresh);
    expect("mailOff" in on).toBe(false);
    // The other toggles are left alone.
    expect(toggleMailForChat({ ...fresh, webSearch: true }).webSearch).toBe(true);
  });

  it("is kept with the chat's stored settings, and only when set", () => {
    expect(normalizeChatTools({ mailOff: true }).mailOff).toBe(true);
    expect("mailOff" in normalizeChatTools({ mailOff: false })).toBe(false);
    expect("mailOff" in normalizeChatTools({ webSearch: true })).toBe(false);
    expect("mailOff" in normalizeChatTools(null)).toBe(false);
  });

  it("carries a choice made before the chat existed to the chat created for the first message", () => {
    const before = toggleMailForChat(copyFreshChatTools());
    expect(withMailSwitchFrom(copyFreshChatTools(), before).mailOff).toBe(true);
    expect("mailOff" in withMailSwitchFrom(copyFreshChatTools(), copyFreshChatTools())).toBe(false);
  });
});

describe("the request's tools", () => {
  const payload = toolsToApiPayload(copyFreshChatTools());

  it("ask for mail only when the envelope shows and is on", () => {
    const on = withMailTool(payload, mailToolRequested(personal, copyFreshChatTools()));
    expect(on.tools).toEqual({ ...payload.tools, exchange_mail: true });
    expect(on.web_search).toBe(payload.web_search);

    const offTools = toggleMailForChat(copyFreshChatTools());
    for (const [ctx, tools] of [
      [personal, offTools],
      [{ ...personal, connected: false }, copyFreshChatTools()],
      [{ ...personal, projectChat: true }, copyFreshChatTools()],
      [{ ...personal, agentMode: true }, copyFreshChatTools()],
    ] as const) {
      const body = withMailTool(payload, mailToolRequested(ctx, tools));
      expect(body).toBe(payload);
      expect("exchange_mail" in body.tools).toBe(false);
    }
  });

  it("never carry the switch itself to the server's tool list", () => {
    expect("mailOff" in toolsToApiPayload(toggleMailForChat(copyFreshChatTools())).tools).toBe(false);
  });
});

describe("useExchangeMailConnected", () => {
  let host: HTMLDivElement;
  let root: Root;

  function Probe() {
    return <output data-testid="mail">{useExchangeMailConnected() ? "on" : "off"}</output>;
  }
  const shown = () => document.querySelector('[data-testid="mail"]')?.textContent;

  beforeEach(() => {
    session.current = { username: "s", role: "user", is_active: true, auth_provider: "ldap", features: { exchange_mail: false } };
    session.listeners.clear();
    vi.mocked(bootstrapSession).mockClear();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it("follows the session, and reads it again when the mailbox connection changes", async () => {
    await act(async () => root.render(<Probe />));
    expect(shown()).toBe("off");

    const connected = { ...session.current, features: { exchange_mail: true } };
    vi.mocked(bootstrapSession).mockImplementationOnce(async () => {
      session.current = connected;
      for (const listener of session.listeners) listener(connected);
      return connected as never;
    });
    await act(async () => {
      window.dispatchEvent(new Event(MAIL_CHANGED_EVENT));
    });
    expect(bootstrapSession).toHaveBeenCalledWith(true);
    expect(shown()).toBe("on");

    act(() => root.unmount());
    root = createRoot(host);
    window.dispatchEvent(new Event(MAIL_CHANGED_EVENT));
    // Unmounted: no more reads, no listener left behind.
    expect(bootstrapSession).toHaveBeenCalledTimes(1);
    expect(session.listeners.size).toBe(0);
  });
});
