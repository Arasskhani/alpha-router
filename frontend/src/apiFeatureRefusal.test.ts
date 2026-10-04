/**
 * @vitest-environment happy-dom
 *
 * A section Feature Access closed while the page was open: the first refusal
 * re-reads the session, so the menus and SectionGate follow.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

const flush = () => new Promise((done) => setTimeout(done, 0));

describe("a feature_not_enabled refusal", () => {
  it("re-reads the session and tells its listeners", async () => {
    const fetch = vi.fn(async (path: string) => {
      if (path === "/api/auth/session") {
        return new Response(JSON.stringify({ username: "sara", role: "user", features: { chat: false } }));
      }
      return new Response(JSON.stringify({ detail: { code: "feature_not_enabled", feature: "chat", message: "x" } }), {
        status: 403,
      });
    });
    vi.stubGlobal("fetch", fetch);
    const api = await import("./api");
    const listener = vi.fn();
    api.onSessionReady(listener);
    await expect(api.api("/api/user/chats")).rejects.toThrow("x");
    await flush();
    await flush();
    expect(fetch.mock.calls.map((call) => call[0])).toContain("/api/auth/session");
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({ features: { chat: false } }));
    expect(api.getCachedSession()?.features).toEqual({ chat: false });
  });

  it("leaves any other 403 alone", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ detail: "Admin only" }), { status: 403 }));
    vi.stubGlobal("fetch", fetch);
    const api = await import("./api");
    await expect(api.api("/api/admin/users")).rejects.toThrow("Admin only");
    await flush();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
