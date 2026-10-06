/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AlphaBlackSplash from "../components/AlphaBlackSplash";
import { STORAGE_KEYS } from "./brand";
import { clearSignIn, noteSignIn, signInPending, useAlphaBlackSplash, SPLASH_TEXT } from "./alphaBlackSplash";
import type { CachedTheme } from "./themeCache";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  sessionStorage.clear();
  vi.useRealTimers();
});

describe("the sign-in note", () => {
  it("is pending for two minutes, then not", () => {
    noteSignIn(1_000_000);
    expect(signInPending(1_000_000 + 119_000)).toBe(true);
    expect(signInPending(1_000_000 + 121_000)).toBe(false);
    clearSignIn();
    expect(sessionStorage.getItem(STORAGE_KEYS.justSignedIn)).toBeNull();
  });
});

describe("the greeting", () => {
  it("says AR455 was HERE for two seconds, and again on the next run", async () => {
    vi.useFakeTimers();
    await act(async () => root.render(<AlphaBlackSplash run={1} />));
    expect(host.textContent).toBe(SPLASH_TEXT);
    expect(SPLASH_TEXT).toBe("AR455 was HERE");
    expect(host.querySelector(".alpha-black-splash")?.getAttribute("aria-hidden")).toBe("true");
    await act(async () => vi.advanceTimersByTime(1900));
    expect(host.textContent).toBe(SPLASH_TEXT);
    await act(async () => vi.advanceTimersByTime(200));
    expect(host.textContent).toBe("");
    await act(async () => root.render(<AlphaBlackSplash run={2} />));
    expect(host.textContent).toBe(SPLASH_TEXT);
  });

  it("shows nothing before it is asked for", async () => {
    await act(async () => root.render(<AlphaBlackSplash run={0} />));
    expect(host.textContent).toBe("");
  });
});

type Splash = ReturnType<typeof useAlphaBlackSplash>;
let current: Splash;
function Probe({ theme }: { theme: CachedTheme }) {
  current = useAlphaBlackSplash(theme);
  return null;
}

describe("when it plays", () => {
  it("plays when ALPHA BLACK is chosen, not when it is chosen again or another theme is", async () => {
    await act(async () => root.render(<Probe theme="light" />));
    expect(current.run).toBe(0);
    await act(async () => current.chosen("alpha-black", "light"));
    expect(current.run).toBe(1);
    await act(async () => current.chosen("alpha-black", "alpha-black"));
    await act(async () => current.chosen("dark", "alpha-black"));
    expect(current.run).toBe(1);
  });

  it("plays at once after a sign-in when this device already keeps ALPHA BLACK, and only once", async () => {
    noteSignIn();
    await act(async () => root.render(<Probe theme="alpha-black" />));
    expect(current.run).toBe(1);
    await act(async () => current.settled("alpha-black"));
    expect(current.run).toBe(1);
    expect(signInPending()).toBe(false);
  });

  it("plays after a sign-in once the account's saved theme turns out to be ALPHA BLACK", async () => {
    noteSignIn();
    await act(async () => root.render(<Probe theme="light" />));
    expect(current.run).toBe(0);
    await act(async () => current.settled("alpha-black"));
    expect(current.run).toBe(1);
  });

  it("does not play without a sign-in, or for another theme", async () => {
    await act(async () => root.render(<Probe theme="alpha-black" />));
    expect(current.run).toBe(0);
    await act(async () => current.settled("alpha-black"));
    expect(current.run).toBe(0);
    noteSignIn();
    await act(async () => current.settled("dark"));
    expect(current.run).toBe(0);
    expect(signInPending()).toBe(false);
  });
});
