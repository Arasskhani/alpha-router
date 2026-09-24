/**
 * @vitest-environment happy-dom
 * @vitest-environment-options {"settings": {"disableJavaScriptFileLoading": true, "handleDisabledFileLoadingAsSuccess": true}}
 *
 * The new-version check: compares the server's entry script with the running
 * one when the app comes back into view (at most every 15 minutes) and hourly
 * while visible, and shows a notice without ever reloading by itself.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Module = typeof import("./appUpdate");

const update = vi.fn(async () => undefined);
let served = '<script type="module" crossorigin src="/assets/index-OLD1.js"></script>';

async function fresh(): Promise<Module> {
  vi.resetModules();
  return import("./appUpdate");
}

function visibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  document.head.innerHTML = '<script type="module" crossorigin src="/assets/index-OLD1.js"></script>';
  served = '<script type="module" crossorigin src="/assets/index-OLD1.js"></script>';
  update.mockClear();
  Object.defineProperty(navigator, "serviceWorker", {
    value: { getRegistration: async () => ({ update }) },
    configurable: true,
  });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(served, { status: 200 })));
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("checkForUpdate", () => {
  it("reads the running build from the page's entry script", async () => {
    const m = await fresh();
    expect(m.runningEntry()).toBe("/assets/index-OLD1.js");
  });

  it("stays quiet while the server has the same build, fetching past every cache", async () => {
    const m = await fresh();
    expect(await m.checkForUpdate()).toBe(false);
    expect(fetch).toHaveBeenCalledWith("/", { cache: "no-store", credentials: "same-origin" });
  });

  it("shows the notice when the server has a new build, and asks the worker to update too", async () => {
    const m = await fresh();
    served = '<script type="module" crossorigin src="/assets/index-NEW2.js"></script>';
    expect(await m.checkForUpdate()).toBe(true);
    expect(update).toHaveBeenCalled();
  });

  it("reads the server's build from its module script, not from a preload that shares the name", async () => {
    const m = await fresh();
    served =
      '<link rel="modulepreload" href="/assets/index-OLD1.js">' +
      '<script type="module" crossorigin src="/assets/index-NEW2.js"></script>';
    expect(await m.checkForUpdate()).toBe(true);
  });

  it("says nothing while the server cannot be reached or answers with an error", async () => {
    const m = await fresh();
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    expect(await m.checkForUpdate()).toBe(false);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Bad gateway", { status: 502 })));
    expect(await m.checkForUpdate()).toBe(false);
  });
});

describe("startUpdateChecks", () => {
  it("checks when the app comes back into view, at most every 15 minutes", async () => {
    vi.useFakeTimers({ now: new Date(2026, 8, 24, 9, 0) });
    vi.stubEnv("PROD", true);
    const m = await fresh();
    m.startUpdateChecks();
    visibility("hidden");
    visibility("visible");
    expect(fetch).not.toHaveBeenCalled();
    vi.setSystemTime(Date.now() + m.VISIBLE_CHECK_GAP_MS);
    visibility("hidden");
    visibility("visible");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("checks hourly while the app is visible, not while it is hidden", async () => {
    vi.useFakeTimers({ now: new Date(2026, 8, 24, 9, 0) });
    vi.stubEnv("PROD", true);
    const m = await fresh();
    m.startUpdateChecks();
    vi.advanceTimersByTime(m.HOURLY_MS);
    expect(fetch).toHaveBeenCalledTimes(1);
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    vi.advanceTimersByTime(m.HOURLY_MS);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does nothing in a development build", async () => {
    vi.useFakeTimers();
    vi.stubEnv("PROD", false);
    const m = await fresh();
    m.startUpdateChecks();
    vi.advanceTimersByTime(m.HOURLY_MS * 2);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("UpdateNotice", () => {
  it("offers a reload once a new version is known, and never reloads by itself", async () => {
    const m = await fresh();
    const { default: UpdateNotice } = await import("../../components/UpdateNotice");
    const reload = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, reload }, configurable: true });
    const host = document.createElement("div");
    const root = createRoot(host);
    await act(async () => root.render(<UpdateNotice />));
    expect(host.textContent).toBe("");
    await act(async () => m.markUpdateAvailable());
    expect(host.querySelector('[role="status"]')?.textContent).toContain("A new version of Alpharouter is available.");
    expect(reload).not.toHaveBeenCalled();
    await act(async () => host.querySelector("button")!.click());
    expect(reload).toHaveBeenCalledTimes(1);
    act(() => root.unmount());
  });
});
