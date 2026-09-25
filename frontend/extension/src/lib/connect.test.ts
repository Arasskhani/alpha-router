/**
 * @vitest-environment node
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EXTENSION_ID, installChromeFake } from "../test/chromeFake";
import { CONNECT_ATTEMPT_MS, deviceName, disconnect, finishConnect, hasPendingConnect, startConnect } from "./connect";
import { challengeFor } from "./pkce";
import { createTokenManager, type StoredAccess, type TokenStorage } from "./tokens";

const SERVER = "https://ai.example.com";
const REDIRECT = `chrome-extension://${EXTENSION_ID}/connected.html`;
const NOW = 1_000_000_000_000;

beforeEach(() => {
  installChromeFake();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function memoryTokens() {
  const state = { access: null as StoredAccess | null, refresh: null as string | null };
  const storage: TokenStorage = {
    getAccess: async () => state.access,
    setAccess: async (v) => void (state.access = v),
    getRefresh: async () => state.refresh,
    setRefresh: async (v) => void (state.refresh = v),
  };
  const tokens = createTokenManager({
    storage,
    lock: (fn) => fn(),
    serverUrl: async () => SERVER,
    fetch: vi.fn() as unknown as typeof fetch,
    now: () => NOW,
  });
  return { state, tokens };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function pending() {
  return (await chrome.storage.session.get("alpharouter.pending-connect"))["alpharouter.pending-connect"] as
    | { state: string; verifier: string; createdAt: number }
    | undefined;
}

async function answer(search: string, fetchImpl: ReturnType<typeof vi.fn>, now = NOW + 1000) {
  const { state, tokens } = memoryTokens();
  const result = await finishConnect(search, {
    tokens,
    serverUrl: async () => SERVER,
    fetch: fetchImpl as unknown as typeof fetch,
    now: () => now,
  });
  return { result, state };
}

describe("starting a connection", () => {
  it("opens the consent page with this extension's page, a challenge and a state", async () => {
    const url = new URL(await startConnect(SERVER, NOW));
    const saved = await pending();
    expect(url.origin + url.pathname).toBe(`${SERVER}/extension/connect`);
    expect(url.searchParams.get("redirect_uri")).toBe(REDIRECT);
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("state")).toBe(saved?.state);
    expect(url.searchParams.get("code_challenge")).toBe(await challengeFor(saved!.verifier));
    // The verifier itself never leaves the extension.
    expect(url.toString()).not.toContain(saved!.verifier);
  });

  it("keeps the attempt for ten minutes", async () => {
    await startConnect(SERVER, NOW);
    expect(await hasPendingConnect(NOW + CONNECT_ATTEMPT_MS - 1)).toBe(true);
    expect(await hasPendingConnect(NOW + CONNECT_ATTEMPT_MS)).toBe(false);
  });
});

describe("finishing a connection", () => {
  it("trades the code and the verifier for tokens", async () => {
    await startConnect(SERVER, NOW);
    const { state: attemptState, verifier } = (await pending())!;
    const fetchImpl = vi.fn(async () =>
      json(200, { access_token: "at", token_type: "Bearer", expires_in: 3600, refresh_token: "rt", session_id: "s1" }),
    );
    const { result, state } = await answer(`?code=the-code&state=${attemptState}`, fetchImpl);
    expect(result).toEqual({ kind: "connected" });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${SERVER}/api/extension/token`);
    expect(init.credentials).toBe("omit");
    expect(JSON.parse(String(init.body))).toEqual({
      grant_type: "authorization_code",
      code: "the-code",
      code_verifier: verifier,
      redirect_uri: REDIRECT,
      device_name: expect.any(String),
    });
    expect(state.refresh).toBe("rt");
    expect(await pending()).toBeUndefined();
  });

  it("refuses an answer to an attempt this browser did not start, and keeps the real one", async () => {
    await startConnect(SERVER, NOW);
    const fetchImpl = vi.fn();
    const { result } = await answer("?code=x&state=someone-elses-state", fetchImpl);
    expect(result.kind).toBe("failed");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(await pending()).toBeDefined();
  });

  it("refuses an answer when nothing was started", async () => {
    const fetchImpl = vi.fn();
    const { result } = await answer("?code=x&state=abc", fetchImpl);
    expect(result.kind).toBe("failed");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses an answer that came too late", async () => {
    await startConnect(SERVER, NOW);
    const { state: attemptState } = (await pending())!;
    const fetchImpl = vi.fn();
    const { result } = await answer(`?code=x&state=${attemptState}`, fetchImpl, NOW + CONNECT_ATTEMPT_MS);
    expect(result).toEqual({ kind: "failed", message: expect.stringContaining("too long") });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(await pending()).toBeUndefined();
  });

  it("takes no for an answer", async () => {
    await startConnect(SERVER, NOW);
    const { state: attemptState } = (await pending())!;
    const fetchImpl = vi.fn();
    const { result } = await answer(`?error=access_denied&state=${attemptState}`, fetchImpl);
    expect(result).toEqual({ kind: "denied" });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(await pending()).toBeUndefined();
  });

  it("shows the server's reason when it refuses the code", async () => {
    await startConnect(SERVER, NOW);
    const { state: attemptState } = (await pending())!;
    const fetchImpl = vi.fn(async () =>
      json(400, { detail: { code: "not_permitted", message: "The browser extension is not enabled for your account." } }),
    );
    const { result, state } = await answer(`?code=x&state=${attemptState}`, fetchImpl);
    expect(result).toEqual({ kind: "failed", message: "The browser extension is not enabled for your account." });
    expect(state.refresh).toBeNull();
  });

  it("says so when the server cannot be reached", async () => {
    await startConnect(SERVER, NOW);
    const { state: attemptState } = (await pending())!;
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const { result } = await answer(`?code=x&state=${attemptState}`, fetchImpl);
    expect(result).toEqual({ kind: "failed", message: expect.stringContaining("could not be reached") });
  });
});

describe("the browser's name", () => {
  it.each([
    [{ userAgentData: { brands: [{ brand: "Microsoft Edge" }, { brand: "Chromium" }], platform: "Windows" }, userAgent: "" }, "Edge on Windows"],
    [{ userAgentData: { brands: [{ brand: "Google Chrome" }], platform: "macOS" }, userAgent: "" }, "Chrome on macOS"],
    [{ userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36" }, "Chrome on Linux"],
    [{ userAgent: "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36 Edg/141.0" }, "Edge on Windows"],
    [{ userAgent: "" }, "Browser"],
  ])("reads %o as %s", (nav, expected) => {
    expect(deviceName(nav as unknown as Navigator)).toBe(expected);
  });
});

describe("disconnecting", () => {
  it("tells the server, then forgets the tokens", async () => {
    const { state, tokens } = memoryTokens();
    await tokens.save({ access_token: "at", token_type: "Bearer", expires_in: 3600, refresh_token: "rt", session_id: "s1" });
    const revoke = vi.fn(async () => undefined);
    await disconnect(tokens, revoke);
    expect(revoke).toHaveBeenCalledOnce();
    expect(state.refresh).toBeNull();
    expect(state.access).toBeNull();
  });

  it("forgets the tokens even when the server cannot be told", async () => {
    const { state, tokens } = memoryTokens();
    await tokens.save({ access_token: "at", token_type: "Bearer", expires_in: 3600, refresh_token: "rt", session_id: "s1" });
    await disconnect(tokens, async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(state.refresh).toBeNull();
  });
});
