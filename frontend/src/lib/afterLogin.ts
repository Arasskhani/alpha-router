import { STORAGE_KEYS } from "./brand";

/**
 * Where to go after signing in, when a page sent the user to sign in first.
 *
 * Only the browser extension's connect page is ever resumed: anything else
 * found in storage is ignored, so this can never become an open redirect. The
 * entry lives in this tab's session storage, survives an SSO round trip, and
 * goes stale after ten minutes - an extension's connect attempt does too.
 */
const RESUMABLE = /^\/extension\/connect\?[^#]*$/;
const MAX_AGE_MS = 10 * 60 * 1000;

export function isResumable(target: string): boolean {
  return RESUMABLE.test(target);
}

export function rememberAfterLogin(target: string, now: number = Date.now()): void {
  if (!isResumable(target)) return;
  try {
    sessionStorage.setItem(STORAGE_KEYS.afterLogin, JSON.stringify({ target, at: now }));
  } catch {
    // Storage switched off: the user starts again from the extension.
  }
}

export function forgetAfterLogin(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEYS.afterLogin);
  } catch {
    // Nothing stored, nothing to forget.
  }
}

/** The page to resume, once; null when there is none, it is stale, or it is not resumable. */
export function takeAfterLogin(now: number = Date.now()): string | null {
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(STORAGE_KEYS.afterLogin);
  } catch {
    return null;
  }
  forgetAfterLogin();
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as { target?: unknown; at?: unknown };
    if (typeof value.target !== "string" || typeof value.at !== "number") return null;
    if (now - value.at > MAX_AGE_MS || value.at - now > 60_000) return null;
    return isResumable(value.target) ? value.target : null;
  } catch {
    return null;
  }
}
