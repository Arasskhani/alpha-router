import { useCallback, useRef, useState } from "react";

import { STORAGE_KEYS } from "./brand";
import type { CachedTheme } from "./themeCache";

/**
 * The ALPHA BLACK greeting: "AR455 was HERE" fades in and out for about two
 * seconds when a person chooses the theme, and after each sign-in while it is
 * their theme. The sign-in page notes the sign-in in this tab's session
 * storage; the app shows the greeting once the account's theme is known.
 */
export const ALPHA_BLACK: CachedTheme = "alpha-black";
export const SPLASH_TEXT = "AR455 was HERE";
export const SPLASH_MS = 2000;
/** A note older than this is from a sign-in that never reached the app (the extension's connect page). */
const NOTE_MAX_AGE_MS = 2 * 60 * 1000;

export function noteSignIn(now: number = Date.now()): void {
  try {
    sessionStorage.setItem(STORAGE_KEYS.justSignedIn, String(now));
  } catch {
    // Storage switched off: no greeting after this sign-in.
  }
}

/** Whether a sign-in just finished and has not had its greeting yet. Reads only. */
export function signInPending(now: number = Date.now()): boolean {
  try {
    const at = Number(sessionStorage.getItem(STORAGE_KEYS.justSignedIn));
    return at > 0 && now - at <= NOTE_MAX_AGE_MS && at - now <= 60_000;
  } catch {
    return false;
  }
}

export function clearSignIn(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEYS.justSignedIn);
  } catch {
    // Nothing stored, nothing to clear.
  }
}

/**
 * When the greeting plays. `run` counts the times it was asked for (0: never);
 * the greeting restarts on each new count.
 */
export function useAlphaBlackSplash(initialTheme: CachedTheme) {
  // The theme kept on this device is already ALPHA BLACK: greet the sign-in at once.
  const [run, setRun] = useState(() => (signInPending() && initialTheme === ALPHA_BLACK ? 1 : 0));
  const greeted = useRef(run > 0);

  /** The person chose a theme in the Theme dropdown or the appearance buttons. */
  const chosen = useCallback((next: CachedTheme, previous: CachedTheme) => {
    if (next === ALPHA_BLACK && previous !== ALPHA_BLACK) setRun((n) => n + 1);
  }, []);

  /** The account's saved theme is known (or cannot be read): the sign-in is greeted if it is ALPHA BLACK. */
  const settled = useCallback((theme?: CachedTheme) => {
    if (signInPending() && theme === ALPHA_BLACK && !greeted.current) {
      greeted.current = true;
      setRun((n) => n + 1);
    }
    clearSignIn();
  }, []);

  return { run, chosen, settled };
}
