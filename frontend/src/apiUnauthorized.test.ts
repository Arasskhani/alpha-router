/**
 * @vitest-environment happy-dom
 *
 * A refused session sends the page to /login, except where the page already
 * decides that itself: /login, and "/" (HomeRedirect).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const realLocation = window.location;

afterEach(() => {
  Object.defineProperty(window, "location", { value: realLocation, configurable: true });
  vi.unstubAllGlobals();
  vi.resetModules();
});

async function refusedSessionAt(pathname: string) {
  const assign = vi.fn();
  Object.defineProperty(window, "location", { value: { ...realLocation, pathname, assign }, configurable: true });
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  const api = await import("./api");
  await expect(api.bootstrapSession()).rejects.toThrow();
  return assign;
}

describe("a refused session", () => {
  it("sends a protected page to the sign-in page", async () => {
    expect(await refusedSessionAt("/app/chat")).toHaveBeenCalledWith("/login");
  });

  it("leaves / to decide for itself, so the sign-in page loads once", async () => {
    expect(await refusedSessionAt("/")).not.toHaveBeenCalled();
  });

  it("does nothing on the sign-in page itself", async () => {
    expect(await refusedSessionAt("/login")).not.toHaveBeenCalled();
  });
});
