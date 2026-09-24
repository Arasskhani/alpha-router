/**
 * @vitest-environment happy-dom
 *
 * When the install suggestion may appear, and how the user's answers are kept.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", () => ({ getCachedSession: () => null }));

import { BROWSER_EVENT_NAMES, STORAGE_KEYS } from "../brand";
import {
  MAX_DISMISSALS,
  SNOOZE_MS,
  loadPrefs,
  markInstallDone,
  recordAppOpened,
  recordReplyCompleted,
  shouldSuggest,
  snoozeSuggestion,
  type InstallPrefs,
  type SuggestionInput,
} from "./installSuggestion";

const DAY = 24 * 60 * 60 * 1000;
const NOW = new Date(2026, 8, 24, 10, 0, 0).getTime();
const used: InstallPrefs = { days: 2, lastDay: "2026-09-24", replied: false, dismissals: 0, snoozedUntil: 0, done: false };

function input(overrides: Partial<SuggestionInput> = {}): SuggestionInput {
  return { prefs: used, now: NOW, state: "can-prompt", switchOn: true, touch: true, path: "/app/chat", ...overrides };
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("shouldSuggest", () => {
  it("suggests on a touch screen under /app once the app has been used, where it can be installed", () => {
    expect(shouldSuggest(input())).toBe(true);
    expect(shouldSuggest(input({ state: "ios-manual" }))).toBe(true);
    expect(shouldSuggest(input({ path: "/app" }))).toBe(true);
  });

  it("waits until the user has used the app: a completed reply, or a second day", () => {
    expect(shouldSuggest(input({ prefs: { ...used, days: 1 } }))).toBe(false);
    expect(shouldSuggest(input({ prefs: { ...used, days: 1, replied: true } }))).toBe(true);
    expect(shouldSuggest(input({ prefs: { ...used, days: 2 } }))).toBe(true);
  });

  it("never suggests where it cannot install, or is already installed", () => {
    for (const state of ["unavailable", "running-installed"] as const) {
      expect(shouldSuggest(input({ state }))).toBe(false);
    }
  });

  it("stays out of the admin panel, off a touch screen, and when the server switches it off", () => {
    expect(shouldSuggest(input({ path: "/admin/users" }))).toBe(false);
    expect(shouldSuggest(input({ path: "/application" }))).toBe(false);
    expect(shouldSuggest(input({ touch: false }))).toBe(false);
    expect(shouldSuggest(input({ switchOn: false }))).toBe(false);
  });

  it("is quiet for 30 days after Not now, and for good after the third", () => {
    const snoozed = { ...used, dismissals: 1, snoozedUntil: NOW + SNOOZE_MS };
    expect(shouldSuggest(input({ prefs: snoozed }))).toBe(false);
    expect(shouldSuggest(input({ prefs: snoozed, now: NOW + SNOOZE_MS - 1 }))).toBe(false);
    expect(shouldSuggest(input({ prefs: snoozed, now: NOW + SNOOZE_MS }))).toBe(true);
    const third = { ...used, dismissals: MAX_DISMISSALS, snoozedUntil: NOW };
    expect(shouldSuggest(input({ prefs: third, now: NOW + 365 * DAY }))).toBe(false);
  });

  it("never suggests again once accepted or installed", () => {
    expect(shouldSuggest(input({ prefs: { ...used, done: true } }))).toBe(false);
  });

  it("is never shown without local storage, rather than on every visit", () => {
    expect(shouldSuggest(input({ prefs: null }))).toBe(false);
  });
});

describe("the saved answers", () => {
  it("count each calendar day the app is opened once", () => {
    recordAppOpened(NOW);
    recordAppOpened(NOW + 60_000);
    expect(loadPrefs()?.days).toBe(1);
    recordAppOpened(NOW + DAY);
    expect(loadPrefs()?.days).toBe(2);
  });

  it("remember a completed reply", () => {
    recordReplyCompleted();
    expect(loadPrefs()?.replied).toBe(true);
  });

  it("snooze for 30 days and count each Not now", () => {
    snoozeSuggestion(NOW);
    snoozeSuggestion(NOW + SNOOZE_MS);
    expect(loadPrefs()).toMatchObject({ dismissals: 2, snoozedUntil: NOW + 2 * SNOOZE_MS });
  });

  it("remember that the app was installed", () => {
    markInstallDone();
    expect(loadPrefs()?.done).toBe(true);
  });

  it("stay on this device under their own key", () => {
    recordReplyCompleted();
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.installPrompt)!)).toMatchObject({ replied: true });
  });

  it("are unavailable when storage refuses reads or writes, as some private modes do", () => {
    const refuses = (method: "getItem" | "setItem") =>
      ({
        getItem: () => null,
        setItem: () => undefined,
        [method]: () => {
          throw new DOMException("refused", "SecurityError");
        },
      }) as unknown as Storage;
    expect(loadPrefs(refuses("setItem"))).toBeNull();
    expect(loadPrefs(refuses("getItem"))).toBeNull();
  });

  it("survive a corrupt value by starting over", () => {
    localStorage.setItem(STORAGE_KEYS.installPrompt, "{not json");
    expect(loadPrefs()).toBeNull();
    localStorage.setItem(STORAGE_KEYS.installPrompt, "null");
    expect(loadPrefs()).toMatchObject({ days: 0, done: false });
  });
});

describe("startInstallSuggestion", () => {
  it("counts the visit and records completed replies and installs", async () => {
    vi.resetModules();
    const installed: Array<() => void> = [];
    vi.doMock("./installPrompt", () => ({ onAppInstalled: (fn: () => void) => installed.push(fn) }));
    const m = await import("./installSuggestion");
    m.startInstallSuggestion();
    m.startInstallSuggestion();
    expect(m.loadPrefs()?.days).toBe(1);
    window.dispatchEvent(new Event(BROWSER_EVENT_NAMES.chatReplyCompleted));
    expect(m.loadPrefs()?.replied).toBe(true);
    expect(installed).toHaveLength(1);
    installed[0]();
    expect(m.loadPrefs()?.done).toBe(true);
    vi.doUnmock("./installPrompt");
  });
});
