/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { STORAGE_KEYS } from "./brand";
import { forgetAfterLogin, isResumable, rememberAfterLogin, takeAfterLogin } from "./afterLogin";

const CONNECT = "/extension/connect?redirect_uri=chrome-extension%3A%2F%2Fabc%2Fconnected.html&state=s";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("resuming a page after signing in", () => {
  it("gives the connect page back once", () => {
    rememberAfterLogin(CONNECT, 1_000);
    expect(takeAfterLogin(2_000)).toBe(CONNECT);
    expect(takeAfterLogin(2_000)).toBeNull();
  });

  it.each([
    "/admin",
    "/app/chat",
    "//evil.example/extension/connect?x=1",
    "https://evil.example/extension/connect?x=1",
    "/extension/connect",
    "/extension/connect?x=1#fragment",
    "/extension/connectx?y=1",
    " /extension/connect?x=1",
  ])("never remembers %s", (target) => {
    expect(isResumable(target)).toBe(false);
    rememberAfterLogin(target, 1_000);
    expect(sessionStorage.getItem(STORAGE_KEYS.afterLogin)).toBeNull();
  });

  it("ignores anything else written into storage, so it is never an open redirect", () => {
    sessionStorage.setItem(STORAGE_KEYS.afterLogin, JSON.stringify({ target: "https://evil.example/", at: 1_000 }));
    expect(takeAfterLogin(1_000)).toBeNull();
    expect(sessionStorage.getItem(STORAGE_KEYS.afterLogin)).toBeNull();
  });

  it("goes stale after ten minutes", () => {
    rememberAfterLogin(CONNECT, 0);
    expect(takeAfterLogin(10 * 60 * 1000 + 1)).toBeNull();
  });

  it("does not trust a time from the future", () => {
    rememberAfterLogin(CONNECT, 10 * 60 * 1000);
    expect(takeAfterLogin(0)).toBeNull();
  });

  it.each(["{broken", "[1,2]", JSON.stringify({ target: CONNECT }), JSON.stringify({ target: 5, at: 1 })])(
    "survives a damaged entry: %s",
    (raw) => {
      sessionStorage.setItem(STORAGE_KEYS.afterLogin, raw);
      expect(takeAfterLogin(1)).toBeNull();
    },
  );

  it("works without storage", () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    vi.stubGlobal("sessionStorage", { getItem: blocked, setItem: blocked, removeItem: blocked });
    expect(() => rememberAfterLogin(CONNECT)).not.toThrow();
    expect(takeAfterLogin()).toBeNull();
    expect(() => forgetAfterLogin()).not.toThrow();
  });
});
