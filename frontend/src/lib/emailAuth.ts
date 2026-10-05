/**
 * The sign-in page's calls for creating an account and resetting a password
 * with a code sent by email (`/api/auth/signup/*`, `/api/auth/password-reset/*`).
 *
 * Every refusal from these routes is `{detail: {code, message, ...}}`; it is
 * thrown as an EmailAuthError so a step can react to the code (an address that
 * already has an account, a code to wait for) and show the message.
 */
import { authFetch } from "../api";

export type CodeStarted = {
  token: string;
  email: string;
  expires_in: number;
  resend_in: number;
  code_length: number;
};

export class EmailAuthError extends Error {
  code: string;
  status: number;
  extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await authFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new EmailAuthError(0, "network", "Cannot reach the server. Check your connection and try again.");
  }
  const raw = await res.text();
  let data: unknown = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === "object") {
      const { code, message, ...extra } = detail as { code?: string; message?: string } & Record<string, unknown>;
      throw new EmailAuthError(res.status, code || "error", message || `Request failed (${res.status})`, extra);
    }
    const message = typeof detail === "string" && detail ? detail : `Request failed (${res.status})`;
    throw new EmailAuthError(res.status, res.status === 429 ? "rate_limited" : "error", message);
  }
  return data as T;
}

export const signupStart = (email: string) => post<CodeStarted>("/api/auth/signup/start", { email });

export const signupVerify = (token: string, code: string) =>
  post<{ verified: true; email: string; suggested_username: string }>("/api/auth/signup/verify", { token, code });

export const signupUsernameAvailable = (token: string, username: string) =>
  post<{ username: string; available: boolean; code: string | null; message: string | null }>(
    "/api/auth/signup/username-available",
    { token, username },
  );

export const signupComplete = (token: string, username: string, password: string, displayName: string) =>
  post<{ role: string; is_active: boolean }>("/api/auth/signup/complete", {
    token,
    username,
    password,
    display_name: displayName || null,
  });

export const resetStart = (email: string) => post<CodeStarted>("/api/auth/password-reset/start", { email });

export const resetVerify = (token: string, code: string) =>
  post<{ verified: true; email: string; username: string | null }>("/api/auth/password-reset/verify", { token, code });

export const resetComplete = (token: string, password: string) =>
  post<{ ok: true; username: string }>("/api/auth/password-reset/complete", { token, password });

/** Only digits, at most `length` of them: what a code field keeps of what is typed or pasted. */
export function cleanCode(value: string, length = 6): string {
  return value.replace(/\D/g, "").slice(0, length);
}
