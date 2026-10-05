import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({ authFetch: vi.fn() }));

import { authFetch } from "../api";
import { EmailAuthError, cleanCode, signupStart } from "./emailAuth";

afterEach(() => vi.mocked(authFetch).mockReset());

describe("the email sign-up client", () => {
  it("returns what the server answered", async () => {
    vi.mocked(authFetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ token: "t", email: "a@example.com", expires_in: 600, resend_in: 60, code_length: 6 })),
    );
    expect((await signupStart("a@example.com")).token).toBe("t");
    const [path, init] = vi.mocked(authFetch).mock.calls[0];
    expect(path).toBe("/api/auth/signup/start");
    expect(JSON.parse(String(init?.body))).toEqual({ email: "a@example.com" });
  });

  it("throws the refusal's code, message and the rest", async () => {
    vi.mocked(authFetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: { code: "email_taken", message: "An account already uses this email.", reset_available: true } }),
        { status: 409 },
      ),
    );
    const err = await signupStart("a@example.com").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EmailAuthError);
    expect((err as EmailAuthError).code).toBe("email_taken");
    expect((err as EmailAuthError).message).toBe("An account already uses this email.");
    expect((err as EmailAuthError).extra.reset_available).toBe(true);
  });

  it("says when the server cannot be reached", async () => {
    vi.mocked(authFetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(signupStart("a@example.com")).rejects.toMatchObject({ code: "network" });
  });

  it("keeps only the digits of a typed or pasted code", () => {
    expect(cleanCode(" 12 34-56 78")).toBe("123456");
  });
});
