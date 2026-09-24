/**
 * @vitest-environment happy-dom
 *
 * The service worker is registered once, after sign-in, in a production build
 * over a secure connection, when the server's switch is explicitly on, and never
 * in an automated browser such as the server's own PDF renderer.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ session: null as null | { features?: Record<string, unknown> | null } }));
vi.mock("../../api", () => ({ getCachedSession: () => state.session }));

const register = vi.fn(async () => ({}));

function setUp({
  prod = true,
  secure = true,
  webdriver = false,
  serviceWorker = true,
  readyState = "complete",
}: { prod?: boolean; secure?: boolean; webdriver?: boolean; serviceWorker?: boolean; readyState?: string } = {}) {
  vi.stubEnv("PROD", prod);
  Object.defineProperty(window, "isSecureContext", { value: secure, configurable: true });
  Object.defineProperty(navigator, "webdriver", { value: webdriver, configurable: true });
  if (serviceWorker) Object.defineProperty(navigator, "serviceWorker", { value: { register }, configurable: true });
  else delete (navigator as unknown as Record<string, unknown>).serviceWorker;
  Object.defineProperty(document, "readyState", { value: readyState, configurable: true });
}

async function freshModule() {
  vi.resetModules();
  return import("./registerServiceWorker");
}

beforeEach(() => {
  register.mockClear();
  state.session = { features: { pwa_service_worker: true } };
});

afterEach(() => {
  vi.unstubAllEnvs();
  Object.defineProperty(navigator, "serviceWorker", { value: { register }, configurable: true });
});

describe("registerAppServiceWorker", () => {
  it("registers /sw.js for the whole app, never served from the HTTP cache", async () => {
    setUp();
    (await freshModule()).registerAppServiceWorker();
    expect(register).toHaveBeenCalledWith("/sw.js", { scope: "/", updateViaCache: "none" });
  });

  it("registers once per page", async () => {
    setUp();
    const { registerAppServiceWorker } = await freshModule();
    registerAppServiceWorker();
    registerAppServiceWorker();
    expect(register).toHaveBeenCalledTimes(1);
  });

  it("waits for the load event when the page is still loading", async () => {
    setUp({ readyState: "loading" });
    (await freshModule()).registerAppServiceWorker();
    expect(register).not.toHaveBeenCalled();
    window.dispatchEvent(new Event("load"));
    expect(register).toHaveBeenCalledTimes(1);
  });

  it("does nothing in a development build", async () => {
    setUp({ prod: false });
    (await freshModule()).registerAppServiceWorker();
    expect(register).not.toHaveBeenCalled();
  });

  it("does nothing over plain HTTP or without service worker support", async () => {
    setUp({ secure: false });
    (await freshModule()).registerAppServiceWorker();
    setUp({ serviceWorker: false });
    (await freshModule()).registerAppServiceWorker();
    expect(register).not.toHaveBeenCalled();
  });

  it("does nothing in an automated browser, such as the server's PDF renderer", async () => {
    setUp({ webdriver: true });
    (await freshModule()).registerAppServiceWorker();
    expect(register).not.toHaveBeenCalled();
  });

  it("does nothing unless the server's switch is explicitly on", async () => {
    for (const session of [null, {}, { features: null }, { features: {} }, { features: { pwa_service_worker: false } }]) {
      state.session = session;
      setUp();
      (await freshModule()).registerAppServiceWorker();
    }
    expect(register).not.toHaveBeenCalled();
  });

  it("tries again once the session with the switch arrives", async () => {
    setUp();
    const { registerAppServiceWorker } = await freshModule();
    state.session = null;
    registerAppServiceWorker();
    state.session = { features: { pwa_service_worker: true } };
    registerAppServiceWorker();
    expect(register).toHaveBeenCalledTimes(1);
  });

  it("logs a failed registration and shows nothing", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    register.mockRejectedValueOnce(new Error("SecurityError"));
    setUp();
    (await freshModule()).registerAppServiceWorker();
    await Promise.resolve();
    await Promise.resolve();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
