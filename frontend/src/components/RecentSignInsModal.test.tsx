/**
 * @vitest-environment happy-dom
 *
 * Settings → Security shows a button, not a list: the history opens in a
 * dialog over Settings and is fetched afresh each time it opens. Inside,
 * failures read as plainly as successes and the current session is marked.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  Object.defineProperty(globalThis.navigator, "locks", {
    configurable: true,
    value: { request: async () => undefined },
  });
});

vi.mock("../api", () => ({
  api: vi.fn(),
  authFetch: vi.fn(),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: vi.fn(), prompt: vi.fn() }) }));
vi.mock("../lib/replyReadyNotify", () => ({ requestReplyNotifyPermission: vi.fn() }));

import { api } from "../api";
import RecentSignInsModal, { deviceHint } from "./RecentSignInsModal";
import SettingsModal from "./SettingsModal";

const SIGN_INS = {
  auth_provider: "local",
  limit: 20,
  items: [
    {
      occurred_at: "2026-09-21T09:00:00",
      event_type: "login_success",
      outcome: "success",
      reason_code: null,
      auth_method: "local",
      ip: "203.0.113.7",
      user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
      current_session: true,
    },
    {
      occurred_at: "2026-09-21T02:10:00",
      event_type: "login_failed",
      outcome: "failure",
      reason_code: "bad_password",
      auth_method: "local",
      ip: "198.51.100.9",
      user_agent: null,
      current_session: false,
    },
    {
      occurred_at: "2026-09-21T02:09:00",
      event_type: "login_failed",
      outcome: "failure",
      reason_code: "bad_password",
      auth_method: "local",
      ip: "198.51.100.9",
      user_agent: null,
      current_session: false,
    },
  ],
};

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(api).mockReset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

function button(label: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find((b) => b.textContent === label);
}

function click(el: Element | undefined) {
  return act(async () => el?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

describe("deviceHint", () => {
  it("names the browser and platform when the string says", () => {
    expect(deviceHint(SIGN_INS.items[0].user_agent)).toBe("Chrome · Windows");
    expect(deviceHint("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605 Version/17 Safari/604")).toBe(
      "Safari · iOS",
    );
    expect(deviceHint("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0")).toBe(
      "Firefox · Linux",
    );
    expect(deviceHint("curl/8.0")).toBe("");
    expect(deviceHint(null)).toBe("");
  });
});

describe("the dialog", () => {
  async function render(open: boolean) {
    await act(async () => {
      root.render(<RecentSignInsModal open={open} onClose={() => {}} />);
    });
  }

  it("fetches only when open, and afresh on each open", async () => {
    vi.mocked(api).mockResolvedValue(SIGN_INS);
    await render(false);
    expect(vi.mocked(api)).not.toHaveBeenCalled();
    await render(true);
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).toEqual(["/api/user/settings/sign-ins"]);
    await render(false);
    await render(true);
    expect(vi.mocked(api)).toHaveBeenCalledTimes(2);
  });

  it("shows failures as plainly as successes, counts them, and marks this session", async () => {
    vi.mocked(api).mockResolvedValue(SIGN_INS);
    await render(true);
    const text = document.body.textContent || "";
    expect(text).toContain("2 failed attempts");
    expect(text).toContain("Wrong password");
    expect(text).toContain("198.51.100.9");
    expect(text).toContain("This session");
    expect(text).toContain("Chrome · Windows");
    expect(document.querySelectorAll(".recent-sign-ins__item.is-current")).toHaveLength(1);
    expect(document.querySelectorAll(".status-badge--failed")).toHaveLength(2);
    expect(text).not.toContain("identity provider");
  });

  it("refers a federated account's sign-out to the identity provider", async () => {
    vi.mocked(api).mockResolvedValue({ ...SIGN_INS, auth_provider: "oidc" });
    await render(true);
    expect(document.body.textContent).toContain("recorded by your identity provider");
  });

  it("says when nothing has been recorded rather than showing an empty box", async () => {
    vi.mocked(api).mockResolvedValue({ ...SIGN_INS, items: [] });
    await render(true);
    expect(document.body.textContent).toContain("No sign-ins have been recorded yet");
  });
});

describe("Settings → Security", () => {
  it("offers a View button and opens the history in a dialog rather than inline", async () => {
    vi.mocked(api).mockImplementation(async (path: string) => {
      if (path === "/api/user/settings/security") {
        return {
          auth_provider: "local",
          is_local: true,
          totp_enabled: false,
          password_change_available: true,
          two_factor_available: true,
        };
      }
      if (path === "/api/user/settings/sign-ins") return SIGN_INS;
      return {};
    });
    await act(async () => {
      root.render(<SettingsModal open onClose={() => {}} theme="light" onThemeChange={() => {}} />);
    });
    await click(button("Security"));

    expect(host.textContent).toContain("Recent sign-ins");
    // Nothing of the history is on the Security tab itself.
    expect(host.textContent).not.toContain("198.51.100.9");
    expect(vi.mocked(api).mock.calls.map((c) => c[0])).not.toContain("/api/user/settings/sign-ins");

    await click(button("View"));
    const dialogs = document.querySelectorAll('[role="dialog"]');
    expect(dialogs).toHaveLength(2);
    expect(dialogs[1].getAttribute("aria-label")).toBe("Recent sign-ins");
    expect(dialogs[1].textContent).toContain("198.51.100.9");
  });
});
