/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  authFetch: vi.fn(),
  bootstrapSession: vi.fn(),
}));
vi.mock("../lib/themeCache", () => ({ applyThemeToDocument: () => {} }));
vi.mock("../lib/session", () => ({ markLoggedIn: () => {} }));

import { authFetch } from "../api";
import { resetPasswordPolicyCache } from "../lib/passwordRules";
import Login from "./Login";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let methods: Record<string, boolean>;

beforeEach(() => {
  resetPasswordPolicyCache();
  methods = { ldap: false, saml: false, oidc: false, email_signup: true, password_reset: true };
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockImplementation(async (path: string) => {
    if (path === "/api/auth/methods") return new Response(JSON.stringify(methods));
    if (path === "/api/auth/password-reset/start") {
      return new Response(
        JSON.stringify({ token: "tok-r", email: "me@example.com", expires_in: 600, resend_in: 60, code_length: 6 }),
      );
    }
    if (path === "/api/auth/password-reset/verify") {
      return new Response(JSON.stringify({ verified: true, email: "me@example.com", username: "me" }));
    }
    if (path === "/api/auth/password-reset/complete") return new Response(JSON.stringify({ ok: true, username: "me" }));
    return new Response("{}", { status: 404 });
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function render() {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/login"]}>
        <Login />
      </MemoryRouter>,
    );
  });
}

function button(text: string): HTMLButtonElement | undefined {
  return [...host.querySelectorAll("button")].find((b) => b.textContent === text);
}

async function click(text: string) {
  const found = button(text);
  if (!found) throw new Error(`no button "${text}"`);
  await act(async () => found.click());
}

async function type(id: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`#${id}`);
  if (!input) throw new Error(`no #${id}`);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  const form = host.querySelector("form");
  await act(async () => {
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

describe("the sign-in page with email sign-up", () => {
  it("offers neither link when both are off", async () => {
    methods.email_signup = false;
    methods.password_reset = false;
    await render();
    expect(button("Create an account")).toBeUndefined();
    expect(button("Forgot password?")).toBeUndefined();
  });

  it("opens the sign-up form and comes back", async () => {
    await render();
    await click("Create an account");
    expect(host.querySelector(".login-panel__title")?.textContent).toBe("Create an account");
    expect(host.querySelector("#signup-email")).not.toBeNull();
    expect(host.querySelector("#login-username")).toBeNull();
    await click("Back to sign in");
    expect(host.querySelector(".login-panel__title")?.textContent).toBe("Sign in");
    expect(host.querySelector("#login-username")).not.toBeNull();
  });

  it("resets a password and returns to sign in with the username filled in", async () => {
    await render();
    await click("Forgot password?");
    expect(host.querySelector(".login-panel__title")?.textContent).toBe("Reset password");
    await type("reset-email", "me@example.com");
    await submit();
    await type("reset-code", "123456");
    await submit();
    expect(host.textContent).toContain("Choose a new password for me");
    expect(document.activeElement?.id).toBe("reset-password");
    await type("reset-password", "Fresh-Start-2026!");
    await type("reset-confirm", "Fresh-Start-2026!");
    await submit();
    expect(host.querySelector(".login-panel__title")?.textContent).toBe("Sign in");
    expect(host.querySelector<HTMLInputElement>("#login-username")?.value).toBe("me");
    expect(document.activeElement?.id).toBe("login-password");
    expect(host.textContent).toContain("Your password has been changed. Sign in with your new password.");
  });
});
