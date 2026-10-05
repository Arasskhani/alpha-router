/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ authFetch: vi.fn() }));

import { authFetch } from "../../api";
import { resetPasswordPolicyCache } from "../../lib/passwordRules";
import PasswordResetFlow from "./PasswordResetFlow";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let replies: Record<string, { status?: number; body: unknown }>;
let calls: { path: string; body: Record<string, unknown> }[];
let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  resetPasswordPolicyCache();
  calls = [];
  replies = {};
  vi.mocked(authFetch).mockImplementation(async (path: string, init?: RequestInit) => {
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : {} });
    const reply = replies[path];
    if (!reply) return new Response("{}", { status: 404 });
    return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200 });
  });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function type(id: string, value: string) {
  const input = host.querySelector<HTMLInputElement>(`#${id}`);
  if (!input) throw new Error(`no #${id}`);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    host.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

describe("resetting a forgotten password", () => {
  it("goes from the email to the code to the new password", async () => {
    replies["/api/auth/password-reset/start"] = {
      body: { token: "tok-r", email: "sara@example.com", expires_in: 600, resend_in: 60, code_length: 6 },
    };
    replies["/api/auth/password-reset/verify"] = { body: { verified: true, email: "sara@example.com", username: "sara" } };
    replies["/api/auth/password-reset/complete"] = { body: { ok: true, username: "sara" } };
    const onDone = vi.fn();
    await act(async () => {
      root.render(<PasswordResetFlow initialEmail="sara@example.com" onDone={onDone} />);
    });
    expect(host.querySelector<HTMLInputElement>("#reset-email")?.value).toBe("sara@example.com");
    await submit();
    await type("reset-code", "654321");
    await submit();
    expect(host.textContent).toContain("Choose a new password for sara");
    await type("reset-password", "New-Pass-2026!");
    await type("reset-confirm", "New-Pass-2026!");
    await submit();
    expect(calls.at(-1)).toEqual({
      path: "/api/auth/password-reset/complete",
      body: { token: "tok-r", password: "New-Pass-2026!" },
    });
    expect(onDone).toHaveBeenCalledWith("sara");
  });

  it("shows why an address cannot be reset", async () => {
    replies["/api/auth/password-reset/start"] = {
      status: 404,
      body: { detail: { code: "email_unknown", message: "No account uses this email address." } },
    };
    await act(async () => {
      root.render(<PasswordResetFlow onDone={vi.fn()} />);
    });
    await type("reset-email", "nobody@example.com");
    await submit();
    expect(host.querySelector("[role=alert]")?.textContent).toBe("No account uses this email address.");
  });

  it("goes back to the start when the code ran out before the last step", async () => {
    replies["/api/auth/password-reset/start"] = {
      body: { token: "tok-r", email: "sara@example.com", expires_in: 600, resend_in: 60, code_length: 6 },
    };
    replies["/api/auth/password-reset/verify"] = { body: { verified: true, email: "sara@example.com", username: "sara" } };
    replies["/api/auth/password-reset/complete"] = {
      status: 400,
      body: { detail: { code: "code_expired", message: "This step has expired. Start again." } },
    };
    await act(async () => {
      root.render(<PasswordResetFlow initialEmail="sara@example.com" onDone={vi.fn()} />);
    });
    await submit();
    await type("reset-code", "654321");
    await submit();
    await type("reset-password", "New-Pass-2026!");
    await type("reset-confirm", "New-Pass-2026!");
    await submit();
    expect(host.querySelector("#reset-email")).not.toBeNull();
    expect(host.textContent).toContain("This step has expired. Start again.");
  });
});
