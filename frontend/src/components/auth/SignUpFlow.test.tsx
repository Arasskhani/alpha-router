/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ authFetch: vi.fn() }));

import { authFetch } from "../../api";
import { resetPasswordPolicyCache } from "../../lib/passwordRules";
import SignUpFlow from "./SignUpFlow";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Reply = { status?: number; body: unknown };
let replies: Record<string, Reply | ((body: Record<string, unknown>) => Reply)>;
let calls: { path: string; body: Record<string, unknown> }[];

beforeEach(() => {
  resetPasswordPolicyCache();
  calls = [];
  replies = {};
  vi.mocked(authFetch).mockImplementation(async (path: string, init?: RequestInit) => {
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    calls.push({ path, body });
    const reply = replies[path];
    if (!reply) return new Response("{}", { status: 404 });
    const value = typeof reply === "function" ? reply(body) : reply;
    return new Response(JSON.stringify(value.body), { status: value.status ?? 200 });
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

let host: HTMLDivElement;
let root: Root;

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const STARTED = { token: "tok-1", email: "new.person@example.com", expires_in: 600, resend_in: 60, code_length: 6 };

async function render(props: Partial<Parameters<typeof SignUpFlow>[0]> = {}) {
  const handlers = { onSignedIn: vi.fn(), onSignIn: vi.fn(), onResetPassword: vi.fn(), ...props };
  await act(async () => {
    root.render(<SignUpFlow {...handlers} />);
  });
  return handlers;
}

async function type(id: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`#${id}`);
  if (!input) throw new Error(`no #${id}`);
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function last(path: string) {
  return calls.filter((call) => call.path === path).at(-1);
}

async function submit() {
  const form = host.querySelector("form");
  await act(async () => {
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

describe("creating an account", () => {
  it("goes from the email to the code to the account", async () => {
    replies["/api/auth/signup/start"] = { body: STARTED };
    replies["/api/auth/signup/verify"] = {
      body: { verified: true, email: STARTED.email, suggested_username: "new.person" },
    };
    replies["/api/auth/signup/username-available"] = (body) => ({
      body: { username: body.username, available: true, code: null, message: null },
    });
    replies["/api/auth/signup/complete"] = { body: { role: "user", is_active: true } };
    const handlers = await render();

    await type("signup-email", "New.Person@example.com");
    await submit();
    expect(calls[0]).toEqual({ path: "/api/auth/signup/start", body: { email: "New.Person@example.com" } });
    expect(host.textContent).toContain("We sent a 6-digit code to new.person@example.com");

    await type("signup-code", "12 34 56");
    expect(host.querySelector<HTMLInputElement>("#signup-code")?.value).toBe("123456");
    await submit();
    expect(last("/api/auth/signup/verify")).toEqual({ path: "/api/auth/signup/verify", body: { token: "tok-1", code: "123456" } });
    expect(host.querySelector<HTMLInputElement>("#signup-username")?.value).toBe("new.person");

    await type("signup-password", "Strong-Pass-2026!");
    await type("signup-confirm", "Strong-Pass-2026!");
    await submit();
    expect(last("/api/auth/signup/complete")).toEqual({
      path: "/api/auth/signup/complete",
      body: { token: "tok-1", username: "new.person", password: "Strong-Pass-2026!", display_name: null },
    });
    expect(handlers.onSignedIn).toHaveBeenCalledTimes(1);
  });

  it("says a taken username as it is typed", async () => {
    vi.useFakeTimers();
    replies["/api/auth/signup/start"] = { body: STARTED };
    replies["/api/auth/signup/verify"] = { body: { verified: true, email: STARTED.email, suggested_username: "x" } };
    replies["/api/auth/signup/username-available"] = {
      body: { username: "taken", available: false, code: "username_taken", message: "That username is taken. Choose another." },
    };
    await render();
    await type("signup-email", STARTED.email);
    await submit();
    await type("signup-code", "123456");
    await submit();
    await type("signup-username", "taken");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(host.textContent).toContain("That username is taken. Choose another.");
    expect(host.querySelector<HTMLButtonElement>("button[type=submit]")?.disabled).toBe(true);
  });

  it("offers to reset the password of an address that has an account", async () => {
    replies["/api/auth/signup/start"] = {
      status: 409,
      body: {
        detail: {
          code: "email_taken",
          message: "An account already uses this email. Sign in, or reset its password if you have forgotten it.",
          reset_available: true,
        },
      },
    };
    const handlers = await render();
    await type("signup-email", "someone@example.com");
    await submit();
    expect(host.textContent).toContain("An account already uses this email.");
    const reset = [...host.querySelectorAll("button")].find((b) => b.textContent === "Reset password");
    await act(async () => reset?.click());
    expect(handlers.onResetPassword).toHaveBeenCalledWith("someone@example.com");
    const signIn = [...host.querySelectorAll("button")].find((b) => b.textContent === "Sign in");
    await act(async () => signIn?.click());
    expect(handlers.onSignIn).toHaveBeenCalled();
  });

  it("offers no reset when it is not possible", async () => {
    replies["/api/auth/signup/start"] = {
      status: 409,
      body: { detail: { code: "email_taken", message: "An account already uses this email.", reset_available: false } },
    };
    await render();
    await type("signup-email", "someone@example.com");
    await submit();
    expect([...host.querySelectorAll("button")].some((b) => b.textContent === "Reset password")).toBe(false);
  });

  it("waits before a new code can be asked for", async () => {
    vi.useFakeTimers();
    replies["/api/auth/signup/start"] = { body: { ...STARTED, resend_in: 3 } };
    await render();
    await type("signup-email", STARTED.email);
    await submit();
    const resend = () => [...host.querySelectorAll("button")].find((b) => b.textContent?.startsWith("Send a new code"));
    expect(resend()?.textContent).toBe("Send a new code in 3s");
    expect(resend()?.disabled).toBe(true);
    for (let second = 0; second < 4; second += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    }
    expect(resend()?.textContent).toBe("Send a new code");
    expect(resend()?.disabled).toBe(false);
  });

  it("refuses two different passwords before asking the server", async () => {
    replies["/api/auth/signup/start"] = { body: STARTED };
    replies["/api/auth/signup/verify"] = { body: { verified: true, email: STARTED.email, suggested_username: "new.person" } };
    replies["/api/auth/signup/username-available"] = { body: { username: "new.person", available: true, code: null, message: null } };
    await render();
    await type("signup-email", STARTED.email);
    await submit();
    await type("signup-code", "123456");
    await submit();
    await type("signup-password", "Strong-Pass-2026!");
    await type("signup-confirm", "Strong-Pass-2027!");
    await submit();
    expect(host.textContent).toContain("The two passwords are not the same.");
    expect(calls.some((c) => c.path === "/api/auth/signup/complete")).toBe(false);
  });
});
