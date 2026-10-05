import { STORAGE_KEYS } from "./brand";
import type { CodeStarted } from "./emailAuth";

/**
 * A sign-up or password reset by email in progress, kept in this tab's session
 * storage so it outlives a reload. On a phone the person switches to the mail
 * app for the code, and the browser may reload or discard the tab meanwhile:
 * without this they came back to the sign-in form, could not ask for a new
 * code for a minute, and the code in their inbox was useless without its token.
 *
 * Kept only as long as the server keeps the step open: until the code expires,
 * then 30 minutes from entering it. Cleared when the flow ends or is left.
 */
export type EmailFlow = {
  flow: "signup" | "reset";
  step: "code" | "details" | "password";
  started: CodeStarted;
  /** The account's username, once the reset code is entered. */
  username?: string;
  /** When this step began (ms). */
  at: number;
};

/** The server's window for the last step after the code was entered (COMPLETE_TTL). */
const AFTER_CODE_MS = 30 * 60 * 1000;

export function saveEmailFlow(value: Omit<EmailFlow, "at">, now: number = Date.now()): void {
  try {
    sessionStorage.setItem(STORAGE_KEYS.emailFlow, JSON.stringify({ ...value, at: now }));
  } catch {
    // Storage switched off: a reload starts again, as before.
  }
}

export function clearEmailFlow(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEYS.emailFlow);
  } catch {
    // Nothing stored, nothing to clear.
  }
}

/** The flow in progress, or null when there is none, it has expired, or it is not one we wrote. */
export function loadEmailFlow(now: number = Date.now()): EmailFlow | null {
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(STORAGE_KEYS.emailFlow);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<EmailFlow>;
    const started = value.started;
    const valid =
      (value.flow === "signup" || value.flow === "reset") &&
      (value.step === "code" || value.step === "details" || value.step === "password") &&
      typeof value.at === "number" &&
      !!started &&
      typeof started.token === "string" &&
      typeof started.email === "string" &&
      typeof started.code_length === "number";
    if (!valid) {
      clearEmailFlow();
      return null;
    }
    const life = value.step === "code" ? Number(started.expires_in || 0) * 1000 : AFTER_CODE_MS;
    if (now - (value.at as number) > life || (value.at as number) - now > 60_000) {
      clearEmailFlow();
      return null;
    }
    return value as EmailFlow;
  } catch {
    clearEmailFlow();
    return null;
  }
}
