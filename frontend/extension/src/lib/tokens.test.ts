/**
 * @vitest-environment node
 */
import { describe, expect, it, vi } from "vitest";

import { DisconnectedError, TemporaryError, createTokenManager, type Lock, type StoredAccess, type TokenStorage } from "./tokens";

const SERVER = "https://ai.example.com";
const NOW = 1_000_000_000_000;

function memoryStorage(access: StoredAccess | null, refresh: string | null) {
  const state = { access, refresh, writes: [] as string[] };
  const storage: TokenStorage = {
    getAccess: async () => state.access,
    setAccess: async (value) => {
      state.writes.push(value ? "access" : "access:cleared");
      state.access = value;
    },
    getRefresh: async () => state.refresh,
    setRefresh: async (value) => {
      state.writes.push(value ? "refresh" : "refresh:cleared");
      state.refresh = value;
    },
  };
  return { state, storage };
}

/** One holder at a time, in call order - what navigator.locks gives across pages. */
function mutex(): Lock {
  let chain: Promise<unknown> = Promise.resolve();
  return <T>(fn: () => Promise<T>) => {
    const run = chain.then(fn);
    chain = run.catch(() => undefined);
    return run;
  };
}

function pair(n: number) {
  return {
    access_token: `alpha-router-ext-at-${n}`,
    token_type: "Bearer",
    expires_in: 3600,
    refresh_token: `alpha-router-ext-rt-${n}`,
    session_id: "session-1",
  };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const FRESH: StoredAccess = { token: "alpha-router-ext-at-0", expiresAt: NOW + 3_600_000, sessionId: "session-1" };
const ENDED: StoredAccess = { token: "alpha-router-ext-at-0", expiresAt: NOW + 30_000, sessionId: "session-1" };

function manager(storage: TokenStorage, fetchImpl: typeof fetch, onDisconnected = vi.fn()) {
  return {
    onDisconnected,
    tokens: createTokenManager({
      storage,
      lock: mutex(),
      serverUrl: async () => SERVER,
      fetch: fetchImpl,
      now: () => NOW,
      onDisconnected,
    }),
  };
}

describe("the access token", () => {
  it("is used as it is while it lasts", async () => {
    const { storage } = memoryStorage(FRESH, "alpha-router-ext-rt-0");
    const fetchImpl = vi.fn();
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.accessToken()).toBe(FRESH.token);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("is refreshed a minute before it ends, without cookies", async () => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi.fn(async () => json(200, pair(1)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${SERVER}/api/extension/token`);
    expect(init.credentials).toBe("omit");
    expect(JSON.parse(String(init.body))).toEqual({ grant_type: "refresh_token", refresh_token: "alpha-router-ext-rt-0" });
    expect(state.refresh).toBe("alpha-router-ext-rt-1");
    expect(state.access).toEqual({ token: "alpha-router-ext-at-1", expiresAt: NOW + 3_600_000, sessionId: "session-1" });
    // The refresh token is written first: a crash in between loses nothing.
    expect(state.writes).toEqual(["refresh", "access"]);
  });

  it("is refreshed once when two callers need it at the same time", async () => {
    const { storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const fetchImpl = vi.fn(async () => {
      await gate;
      return json(200, pair(1));
    });
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    const both = Promise.all([tokens.accessToken(), tokens.accessToken()]);
    release();
    expect(await both).toEqual(["alpha-router-ext-at-1", "alpha-router-ext-at-1"]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

describe("after a 401", () => {
  it("uses the token another page already got instead of refreshing again", async () => {
    const replaced: StoredAccess = { ...FRESH, token: "alpha-router-ext-at-9" };
    const { storage } = memoryStorage(replaced, "alpha-router-ext-rt-9");
    const fetchImpl = vi.fn();
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.replaceRejected("alpha-router-ext-at-0")).toBe("alpha-router-ext-at-9");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refreshes when the rejected token is still the stored one", async () => {
    const { storage } = memoryStorage(FRESH, "alpha-router-ext-rt-0");
    const fetchImpl = vi.fn(async () => json(200, pair(2)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.replaceRejected(FRESH.token)).toBe("alpha-router-ext-at-2");
  });
});

describe("a refresh the server refuses", () => {
  it("disconnects: the tokens go and the panel is told", async () => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi.fn(async () =>
      json(400, { detail: { code: "invalid_grant", message: "You signed out; connect this browser again." } }),
    );
    const { tokens, onDisconnected } = manager(storage, fetchImpl as unknown as typeof fetch);
    const error = await tokens.accessToken().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(DisconnectedError);
    expect((error as Error).message).toBe("You signed out; connect this browser again.");
    expect(state.access).toBeNull();
    expect(state.refresh).toBeNull();
    expect(onDisconnected).toHaveBeenCalledOnce();
  });

  it("needs a refresh token to begin with", async () => {
    const { storage } = memoryStorage(null, null);
    const fetchImpl = vi.fn();
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    await expect(tokens.accessToken()).rejects.toBeInstanceOf(DisconnectedError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("a refresh that cannot happen right now", () => {
  it.each([429, 500, 502, 503])("keeps the tokens on %i", async (status) => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi.fn(async () => json(status, { detail: "busy" }));
    const { tokens, onDisconnected } = manager(storage, fetchImpl as unknown as typeof fetch);
    await expect(tokens.accessToken()).rejects.toBeInstanceOf(TemporaryError);
    expect(state.refresh).toBe("alpha-router-ext-rt-0");
    expect(onDisconnected).not.toHaveBeenCalled();
  });

  it("retries a lost response once, with the same refresh token", async () => {
    const { storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(json(200, pair(1)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    const bodies = fetchImpl.mock.calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)).refresh_token);
    expect(bodies).toEqual(["alpha-router-ext-rt-0", "alpha-router-ext-rt-0"]);
  });

  it("keeps the tokens when the network stays down", async () => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    await expect(tokens.accessToken()).rejects.toBeInstanceOf(TemporaryError);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(state.refresh).toBe("alpha-router-ext-rt-0");
  });
});

describe("connecting and disconnecting", () => {
  it("saves a connect response and forgets it on request", async () => {
    const { state, storage } = memoryStorage(null, null);
    const { tokens, onDisconnected } = manager(storage, vi.fn() as unknown as typeof fetch);
    expect(await tokens.isConnected()).toBe(false);
    await tokens.save(pair(5));
    expect(await tokens.isConnected()).toBe(true);
    expect(await tokens.sessionId()).toBe("session-1");
    await tokens.forget();
    expect(state.access).toBeNull();
    expect(state.refresh).toBeNull();
    expect(onDisconnected).toHaveBeenCalledOnce();
  });

  it("refuses a response without tokens", async () => {
    const { storage } = memoryStorage(null, null);
    const { tokens } = manager(storage, vi.fn() as unknown as typeof fetch);
    await expect(tokens.save({ ...pair(1), refresh_token: "" })).rejects.toThrow("no tokens");
  });
});
