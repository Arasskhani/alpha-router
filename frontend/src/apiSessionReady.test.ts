/**
 * @vitest-environment happy-dom
 *
 * onSessionReady: start-up work (the service worker) waits for the session,
 * which carries the server's switches.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

function serveSession(ok: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ username: "sara", role: "user" }), { status: ok ? 200 : 401 })),
  );
}

describe("onSessionReady", () => {
  it("calls back when the server confirms a session, and at once for a later listener", async () => {
    serveSession(true);
    const api = await import("./api");
    const early = vi.fn();
    api.onSessionReady(early);
    expect(early).not.toHaveBeenCalled();
    await api.bootstrapSession();
    expect(early).toHaveBeenCalledWith(expect.objectContaining({ username: "sara" }));
    const late = vi.fn();
    api.onSessionReady(late);
    expect(late).toHaveBeenCalledTimes(1);
  });

  it("does not call back without a session, and a failing listener does not break sign-in", async () => {
    serveSession(false);
    const api = await import("./api");
    const listener = vi.fn();
    api.onSessionReady(listener);
    window.history.replaceState(null, "", "/login");
    await expect(api.bootstrapSession()).rejects.toThrow();
    expect(listener).not.toHaveBeenCalled();

    serveSession(true);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    api.onSessionReady(() => {
      throw new Error("boom");
    });
    await expect(api.bootstrapSession(true)).resolves.toMatchObject({ username: "sara" });
    expect(listener).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("stops calling back once unsubscribed", async () => {
    serveSession(true);
    const api = await import("./api");
    const listener = vi.fn();
    const stop = api.onSessionReady(listener);
    stop();
    await api.bootstrapSession();
    expect(listener).not.toHaveBeenCalled();
  });
});
