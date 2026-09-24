/**
 * @vitest-environment happy-dom
 *
 * The install state: kept from the browser's events, which can arrive before
 * React renders, and never letting the browser prompt on its own.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const IPHONE_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const IPAD_SAFARI =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const IOS_CHROME =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1";
const IOS_GOOGLE_APP =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) GSA/330.0 Mobile/15E148 Safari/604.1";
const IOS_INSTAGRAM =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 350.0";
const ANDROID_FIREFOX = "Mozilla/5.0 (Android 14; Mobile; rv:130.0) Gecko/130.0 Firefox/130.0";

type Module = typeof import("./installPrompt");

let standalone = false;

async function fresh(): Promise<Module> {
  vi.resetModules();
  return import("./installPrompt");
}

function installEvent(outcome: "accepted" | "dismissed" = "accepted") {
  const event = new Event("beforeinstallprompt", { cancelable: true }) as Event & {
    prompt: ReturnType<typeof vi.fn>;
    userChoice: Promise<{ outcome: string; platform: string }>;
  };
  event.prompt = vi.fn(async () => undefined);
  event.userChoice = Promise.resolve({ outcome, platform: "web" });
  return event;
}

beforeEach(() => {
  standalone = false;
  window.matchMedia = ((query: string) => ({
    matches: standalone && query === "(display-mode: standalone)",
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  Object.defineProperty(navigator, "userAgent", { value: "Mozilla/5.0 (X11; Linux x86_64) Chrome/129.0", configurable: true });
  Object.defineProperty(navigator, "maxTouchPoints", { value: 0, configurable: true });
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  delete (navigator as unknown as Record<string, unknown>).standalone;
});

afterEach(() => {
  delete (navigator as unknown as Record<string, unknown>).standalone;
});

describe("the install state", () => {
  it("keeps an install event that fires before anything renders, and stops the browser prompting", async () => {
    const m = await fresh();
    m.startInstallListeners();
    expect(m.getInstallState()).toBe("unavailable");
    const event = installEvent();
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(m.getInstallState()).toBe("can-prompt");
  });

  it("opens the browser's dialog at once, inside the click, and uses each event only once", async () => {
    const m = await fresh();
    m.startInstallListeners();
    const event = installEvent("accepted");
    window.dispatchEvent(event);
    const answer = m.promptInstall();
    // Synchronous: a browser refuses prompt() outside the user's gesture.
    expect(event.prompt).toHaveBeenCalledTimes(1);
    expect(await answer).toBe("accepted");
    expect(m.getInstallState()).toBe("unavailable");
    expect(await m.promptInstall()).toBe("unavailable");
    expect(event.prompt).toHaveBeenCalledTimes(1);
  });

  it("reports a dismissed dialog", async () => {
    const m = await fresh();
    m.startInstallListeners();
    window.dispatchEvent(installEvent("dismissed"));
    expect(await m.promptInstall()).toBe("dismissed");
  });

  it("offers nothing more once the app is installed, and says so", async () => {
    const m = await fresh();
    m.startInstallListeners();
    const installed = vi.fn();
    m.onAppInstalled(installed);
    window.dispatchEvent(installEvent());
    window.dispatchEvent(new Event("appinstalled"));
    expect(installed).toHaveBeenCalledTimes(1);
    expect(m.getInstallState()).toBe("unavailable");
  });

  it("knows when it is already running as the installed app", async () => {
    const m = await fresh();
    m.startInstallListeners();
    window.dispatchEvent(installEvent());
    standalone = true;
    expect(m.getInstallState()).toBe("running-installed");
    standalone = false;
    Object.defineProperty(navigator, "standalone", { value: true, configurable: true });
    expect(m.getInstallState()).toBe("running-installed");
  });

  it("offers the Add to Home Screen steps on an iPhone or iPad", async () => {
    const m = await fresh();
    Object.defineProperty(navigator, "userAgent", { value: IPHONE_SAFARI, configurable: true });
    expect(m.getInstallState()).toBe("ios-manual");
    Object.defineProperty(navigator, "userAgent", { value: IPAD_SAFARI, configurable: true });
    Object.defineProperty(navigator, "maxTouchPoints", { value: 5, configurable: true });
    expect(m.getInstallState()).toBe("ios-manual");
  });

  it("re-renders a component when the state changes", async () => {
    const m = await fresh();
    m.startInstallListeners();
    const host = document.createElement("div");
    const root = createRoot(host);
    function Probe() {
      return <output>{m.useInstallState()}</output>;
    }
    await act(async () => root.render(<Probe />));
    expect(host.textContent).toBe("unavailable");
    await act(async () => void window.dispatchEvent(installEvent()));
    expect(host.textContent).toBe("can-prompt");
    act(() => root.unmount());
  });
});

describe("canAddToHomeScreen", () => {
  it("says which iOS browsers have Add to Home Screen", async () => {
    const { canAddToHomeScreen } = await fresh();
    expect(canAddToHomeScreen(IPHONE_SAFARI, 5, true)).toBe(true);
    expect(canAddToHomeScreen(IOS_CHROME, 5, true)).toBe(true);
    expect(canAddToHomeScreen(IPAD_SAFARI, 5, true)).toBe(true);
    // A Mac: the same user agent as an iPad, without touch.
    expect(canAddToHomeScreen(IPAD_SAFARI, 0, true)).toBe(false);
    expect(canAddToHomeScreen(IOS_GOOGLE_APP, 5, true)).toBe(false);
    expect(canAddToHomeScreen(IOS_INSTAGRAM, 5, true)).toBe(false);
    expect(canAddToHomeScreen(ANDROID_FIREFOX, 5, true)).toBe(false);
    // Plain HTTP: nothing installs there.
    expect(canAddToHomeScreen(IPHONE_SAFARI, 5, false)).toBe(false);
  });
});
