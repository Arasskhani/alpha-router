/**
 * @vitest-environment happy-dom
 *
 * The install suggestion bar: shown once the rules allow, decided on start-up
 * and route changes only, out of the way of the keyboard, and each answer kept.
 */
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const install = vi.hoisted(() => ({
  state: "can-prompt" as string,
  outcome: "accepted" as string,
  switchOn: true,
  listeners: new Set<() => void>(),
}));

vi.mock("../api", () => ({ getCachedSession: () => ({ features: { pwa_install_prompt: install.switchOn } }) }));
vi.mock("../lib/pwa/installPrompt", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useInstallState: () =>
      useSyncExternalStore(
        (fn: () => void) => {
          install.listeners.add(fn);
          return () => install.listeners.delete(fn);
        },
        () => install.state,
      ),
    promptInstall: vi.fn(() => Promise.resolve(install.outcome)),
    onAppInstalled: () => () => {},
  };
});

import { promptInstall } from "../lib/pwa/installPrompt";
import { STORAGE_KEYS } from "../lib/brand";
import { loadPrefs } from "../lib/pwa/installSuggestion";
import InstallBanner from "./InstallBanner";

let host: HTMLDivElement;
let root: Root;
let go: (path: string) => void = () => {};

function Nav() {
  const navigate = useNavigate();
  useEffect(() => {
    go = navigate;
  }, [navigate]);
  return null;
}

function setPrefs(prefs: Record<string, unknown>) {
  localStorage.setItem(STORAGE_KEYS.installPrompt, JSON.stringify(prefs));
}

async function render(path = "/app/chat") {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Nav />
        <input aria-label="Message" />
        <InstallBanner />
      </MemoryRouter>,
    );
  });
}

const banner = () => host.querySelector<HTMLElement>(".install-banner");
const button = (label: string) =>
  [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) ?? null;

beforeEach(() => {
  install.state = "can-prompt";
  install.outcome = "accepted";
  install.switchOn = true;
  vi.mocked(promptInstall).mockClear();
  localStorage.clear();
  setPrefs({ days: 2, lastDay: "2026-09-23" });
  window.matchMedia = ((query: string) => ({ matches: query === "(pointer: coarse)", media: query })) as typeof window.matchMedia;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = "";
});

describe("InstallBanner", () => {
  it("suggests installing, as a labelled region with finger-sized buttons", async () => {
    await render();
    expect(banner()?.getAttribute("role")).toBe("region");
    expect(banner()?.getAttribute("aria-label")).toBe("Install app");
    expect(banner()?.textContent).toContain("Install Alpharouter as an app");
    expect(button("Install")).not.toBeNull();
    expect(button("Not now")).not.toBeNull();
  });

  it("stays hidden until the app has been used here", async () => {
    setPrefs({ days: 1, lastDay: "2026-09-24" });
    await render();
    expect(banner()).toBeNull();
  });

  it("opens the browser's dialog once from Install, and never comes back once accepted", async () => {
    await render();
    await act(async () => button("Install")!.click());
    expect(promptInstall).toHaveBeenCalledTimes(1);
    expect(banner()).toBeNull();
    expect(loadPrefs()?.done).toBe(true);
  });

  it("counts a dismissed browser dialog as Not now", async () => {
    install.outcome = "dismissed";
    await render();
    await act(async () => button("Install")!.click());
    expect(loadPrefs()?.dismissals).toBe(1);
  });

  it("keeps Not now for 30 days", async () => {
    await render();
    await act(async () => button("Not now")!.click());
    expect(banner()).toBeNull();
    const prefs = loadPrefs()!;
    expect(prefs.dismissals).toBe(1);
    expect(prefs.snoozedUntil).toBeGreaterThan(Date.now() + 29 * 24 * 60 * 60 * 1000);
    await act(async () => go("/app/projects"));
    expect(banner()).toBeNull();
  });

  it("on an iPhone shows how to install, and counts that as the answer", async () => {
    install.state = "ios-manual";
    await render();
    await act(async () => button("How to install")!.click());
    expect(promptInstall).not.toHaveBeenCalled();
    expect(banner()).toBeNull();
    expect(document.body.textContent).toContain("Add to Home Screen");
    expect(document.body.textContent).toContain("Open this page in Safari if you don't see these options.");
    expect(loadPrefs()?.dismissals).toBe(1);
  });

  it("steps aside while the keyboard is up", async () => {
    await render();
    const field = host.querySelector<HTMLInputElement>('input[aria-label="Message"]')!;
    await act(async () => field.focus());
    expect(banner()).toBeNull();
    await act(async () => field.blur());
    expect(banner()).not.toBeNull();
  });

  it("does not pop up in the middle of a page, only after a route change", async () => {
    install.state = "unavailable";
    await render();
    expect(banner()).toBeNull();
    // The browser's event arrives while the user reads a reply: nothing moves.
    await act(async () => {
      install.state = "can-prompt";
      install.listeners.forEach((fn) => fn());
    });
    expect(banner()).toBeNull();
    await act(async () => go("/app/projects"));
    expect(banner()).not.toBeNull();
  });

  it("goes as soon as the app can no longer be installed from here", async () => {
    await render();
    await act(async () => {
      install.state = "unavailable";
      install.listeners.forEach((fn) => fn());
    });
    expect(banner()).toBeNull();
  });

  it("stays out of the admin panel and when the server switches it off", async () => {
    await render("/admin/users");
    expect(banner()).toBeNull();
    install.switchOn = false;
    await act(async () => go("/app/chat"));
    expect(banner()).toBeNull();
    install.switchOn = true;
    await act(async () => go("/app/projects"));
    expect(banner()).not.toBeNull();
  });
});
