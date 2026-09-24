/**
 * When to suggest installing the app, and what the user answered. Everything
 * stays in this device's local storage (STORAGE_KEYS.installPrompt); nothing
 * about installing is sent to the server.
 *
 * The suggestion appears only after the user has used the app here (a chat
 * reply has completed, or this is at least the second day it has been opened),
 * on a touch screen, under /app, while the server's switch is on. "Not now"
 * hides it for 30 days; after the third it never comes back on its own. Once
 * accepted or installed it never shows again. Without local storage (private
 * mode) it is not shown at all, rather than on every visit.
 */
import { getCachedSession } from "../../api";
import { BROWSER_EVENT_NAMES, STORAGE_KEYS } from "../brand";
import { onAppInstalled, type InstallState } from "./installPrompt";

export const SNOOZE_MS = 30 * 24 * 60 * 60 * 1000;
export const MAX_DISMISSALS = 3;

export type InstallPrefs = {
  /** Distinct calendar days the app has been opened on this device. */
  days: number;
  /** The last of those days, YYYY-MM-DD in local time. */
  lastDay: string;
  /** A chat reply has completed on this device. */
  replied: boolean;
  /** How many times "Not now" (or its equivalent) was chosen. */
  dismissals: number;
  /** Not shown again before this time (ms since the epoch). */
  snoozedUntil: number;
  /** Accepted or installed: never shown again. */
  done: boolean;
};

const EMPTY: InstallPrefs = { days: 0, lastDay: "", replied: false, dismissals: 0, snoozedUntil: 0, done: false };

/** The saved answers, or null when local storage cannot be used here. */
export function loadPrefs(storage: Storage | undefined = globalThis.localStorage): InstallPrefs | null {
  try {
    if (!storage) return null;
    const raw = storage.getItem(STORAGE_KEYS.installPrompt);
    const saved = raw ? (JSON.parse(raw) as Partial<InstallPrefs>) : {};
    const prefs = { ...EMPTY, ...(saved && typeof saved === "object" ? saved : {}) };
    // Some private modes read but refuse writes; an answer that cannot be kept
    // would bring the suggestion back on every visit.
    storage.setItem(STORAGE_KEYS.installPrompt, JSON.stringify(prefs));
    return prefs;
  } catch {
    return null;
  }
}

function savePrefs(prefs: InstallPrefs, storage: Storage | undefined = globalThis.localStorage): boolean {
  try {
    storage?.setItem(STORAGE_KEYS.installPrompt, JSON.stringify(prefs));
    return Boolean(storage);
  } catch {
    return false;
  }
}

function update(change: (prefs: InstallPrefs) => InstallPrefs): void {
  const prefs = loadPrefs();
  if (prefs) savePrefs(change(prefs));
}

function localDay(now: number): string {
  const d = new Date(now);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Count today as a day the app was opened here. */
export function recordAppOpened(now: number = Date.now()): void {
  const today = localDay(now);
  update((p) => (p.lastDay === today ? p : { ...p, days: p.days + 1, lastDay: today }));
}

/** A chat reply completed on this device. */
export function recordReplyCompleted(): void {
  update((p) => (p.replied ? p : { ...p, replied: true }));
}

/** "Not now": hidden for 30 days; the third time, for good. */
export function snoozeSuggestion(now: number = Date.now()): void {
  update((p) => ({ ...p, dismissals: p.dismissals + 1, snoozedUntil: now + SNOOZE_MS }));
}

/** Accepted or installed: never suggested again. */
export function markInstallDone(): void {
  update((p) => ({ ...p, done: true }));
}

export type SuggestionInput = {
  prefs: InstallPrefs | null;
  now: number;
  state: InstallState;
  /** The server's switch (features.pwa_install_prompt); unknown means on. */
  switchOn: boolean;
  /** A touch screen: (pointer: coarse). */
  touch: boolean;
  path: string;
};

export function shouldSuggest({ prefs, now, state, switchOn, touch, path }: SuggestionInput): boolean {
  if (!prefs || !switchOn || !touch) return false;
  if (state !== "can-prompt" && state !== "ios-manual") return false;
  if (path !== "/app" && !path.startsWith("/app/")) return false;
  if (prefs.done || prefs.dismissals >= MAX_DISMISSALS || now < prefs.snoozedUntil) return false;
  return prefs.replied || prefs.days >= 2;
}

/** The inputs from this page as it is now. */
export function suggestionInputFor(path: string, state: InstallState, now: number = Date.now()): SuggestionInput {
  const features = getCachedSession()?.features as Record<string, unknown> | null | undefined;
  return {
    prefs: loadPrefs(),
    now,
    state,
    switchOn: features?.pwa_install_prompt !== false,
    touch: window.matchMedia?.("(pointer: coarse)").matches ?? false,
    path,
  };
}

let started = false;

/** Count this visit and start recording use. Call once at start-up. */
export function startInstallSuggestion(): void {
  if (started) return;
  started = true;
  recordAppOpened();
  window.addEventListener(BROWSER_EVENT_NAMES.chatReplyCompleted, () => recordReplyCompleted());
  onAppInstalled(() => markInstallDone());
}
