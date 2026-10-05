/**
 * @vitest-environment happy-dom
 *
 * Settings -> Security -> Password: the rules ticked while a new password is
 * typed include "not your username", which the server enforces too. Without
 * the account's name the rule was always ticked, and the server then refused.
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
  authFetch: vi.fn(async () => new Response("{}", { status: 404 })),
  formatApiError: (e: unknown) => String(e),
}));
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => ({ confirm: vi.fn(), prompt: vi.fn() }) }));
vi.mock("../lib/replyReadyNotify", () => ({ requestReplyNotifyPermission: vi.fn() }));

import { api } from "../api";
import { resetPasswordPolicyCache } from "../lib/passwordRules";
import SettingsModal from "./SettingsModal";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  resetPasswordPolicyCache();
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "/api/user/settings/security") {
      return {
        auth_provider: "local",
        username: "majid",
        email: "m.person@example.com",
        is_local: true,
        totp_enabled: false,
        password_change_available: true,
        two_factor_available: true,
      } as never;
    }
    return {} as never;
  });
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

async function click(el: Element | undefined) {
  await act(async () => el?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

async function typeNewPassword(value: string) {
  const input = document.querySelector<HTMLInputElement>('input[placeholder="New password"]');
  if (!input) throw new Error("no new password field");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function personalRuleMet(): boolean {
  const rules = [...document.querySelectorAll("#settings-new-password-rules li")];
  const personal = rules.find((li) => /username/i.test(li.textContent ?? ""));
  if (!personal) throw new Error("no personal rule");
  return personal.classList.contains("password-rules__rule--met");
}

describe("Settings → Security → Password", () => {
  it("does not tick the personal rule for a password with the username or the email's name", async () => {
    await act(async () => {
      root.render(<SettingsModal open onClose={() => {}} theme="light" onThemeChange={() => {}} />);
    });
    await click(button("Security"));
    await click(button("Change"));

    await typeNewPassword("Majid-2026!x");
    expect(personalRuleMet()).toBe(false);
    await typeNewPassword("M.Person-2026!x");
    expect(personalRuleMet()).toBe(false);
    await typeNewPassword("Quiet-River-2026!");
    expect(personalRuleMet()).toBe(true);
  });
});
