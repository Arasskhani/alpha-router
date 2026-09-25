/**
 * @vitest-environment node
 */
import { describe, expect, it, vi } from "vitest";

import {
  DisconnectedError,
  TemporaryError,
  createTokenManager,
  type Lock,
  type PendingAttempt,
  type StoredAccess,
  type TokenStorage,
} from "./tokens";

const SERVER = "https://ai.example.com";
const NOW = 1_000_000_000_000;

function memoryStorage(access: StoredAccess | null, refresh: string | null, attempt: PendingAttempt | null = null) {
  const state = { access, refresh, attempt, writes: [] as string[] };
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
    getAttempt: async () => state.attempt,
    setAttempt: async (value) => {
      state.writes.push(value ? "attempt" : "attempt:cleared");
      state.attempt = value;
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

type RefreshBody = { grant_type: string; refresh_token: string; attempt: string };

/** What each refresh request sent, oldest first. */
function sent(fetchImpl: ReturnType<typeof vi.fn>): RefreshBody[] {
  return fetchImpl.mock.calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)) as RefreshBody);
}

/** 24 random bytes, base64url: what the server accepts, and hard to guess. */
const AN_ATTEMPT = /^[A-Za-z0-9_-]{32}$/;

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
    expect(JSON.parse(String(init.body))).toEqual({
      grant_type: "refresh_token",
      refresh_token: "alpha-router-ext-rt-0",
      attempt: expect.stringMatching(AN_ATTEMPT),
    });
    expect(state.refresh).toBe("alpha-router-ext-rt-1");
    expect(state.access).toEqual({ token: "alpha-router-ext-at-1", expiresAt: NOW + 3_600_000, sessionId: "session-1" });
    // The attempt is stored before the request and dropped once the new pair
    // is saved; the refresh token is written first. A crash anywhere in
    // between loses nothing.
    expect(state.writes).toEqual(["attempt", "refresh", "access", "attempt:cleared"]);
    expect(state.attempt).toBeNull();
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

  it("names every refresh anew", async () => {
    const { storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi.fn().mockResolvedValueOnce(json(200, pair(1))).mockResolvedValueOnce(json(200, pair(2)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    expect(await tokens.replaceRejected("alpha-router-ext-at-1")).toBe("alpha-router-ext-at-2");
    const [first, second] = sent(fetchImpl);
    expect([first.refresh_token, second.refresh_token]).toEqual(["alpha-router-ext-rt-0", "alpha-router-ext-rt-1"]);
    expect(second.attempt).toMatch(AN_ATTEMPT);
    expect(second.attempt).not.toBe(first.attempt);
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
    expect(state.attempt).toBeNull();
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

  it("retries a lost response once, with the same refresh token and attempt", async () => {
    const { storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(json(200, pair(1)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    const [first, retry] = sent(fetchImpl);
    expect([first.refresh_token, retry.refresh_token]).toEqual(["alpha-router-ext-rt-0", "alpha-router-ext-rt-0"]);
    // The server gives the pair again only to the attempt that replaced the token.
    expect(first.attempt).toMatch(AN_ATTEMPT);
    expect(retry.attempt).toBe(first.attempt);
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

describe("the attempt of a refresh whose answer never came", () => {
  /** Kept by a page that closed while its refresh was on the way. */
  const KEPT: PendingAttempt = { refresh: "alpha-router-ext-rt-0", attempt: "kept-attempt-of-a-page-that-closed" };

  it("is stored before the request goes out", async () => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const stored: Array<PendingAttempt | null> = [];
    const fetchImpl = vi.fn(async () => {
      stored.push(state.attempt);
      return json(200, pair(1));
    });
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    await tokens.accessToken();
    expect(stored).toEqual([{ refresh: "alpha-router-ext-rt-0", attempt: sent(fetchImpl)[0].attempt }]);
  });

  it("is sent again when the network lost the answer", async () => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const timedOut = new DOMException("The operation timed out.", "TimeoutError");
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(timedOut)
      .mockRejectedValueOnce(timedOut)
      .mockResolvedValueOnce(json(200, pair(1)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    await expect(tokens.accessToken()).rejects.toBeInstanceOf(TemporaryError);
    const [first] = sent(fetchImpl);
    expect(state.attempt).toEqual({ refresh: "alpha-router-ext-rt-0", attempt: first.attempt });
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    expect(sent(fetchImpl).map((body) => body.attempt)).toEqual([first.attempt, first.attempt, first.attempt]);
    expect(state.attempt).toBeNull();
  });

  it("is sent again when a proxy answered 502", async () => {
    const { storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(json(502, { detail: "Bad Gateway" }))
      .mockResolvedValueOnce(json(200, pair(1)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    await expect(tokens.accessToken()).rejects.toBeInstanceOf(TemporaryError);
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    const [first, again] = sent(fetchImpl);
    expect(again.attempt).toBe(first.attempt);
  });

  it("is sent by the next page when the page that sent it closed", async () => {
    const { storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0", KEPT);
    const fetchImpl = vi.fn(async () => json(200, pair(1)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    expect(sent(fetchImpl)[0].attempt).toBe(KEPT.attempt);
  });

  it.each([
    ["when it was kept for another refresh token", { ...KEPT, refresh: "alpha-router-ext-rt-older" }],
    ["when what was kept is no attempt", { ...KEPT, attempt: "not an attempt" }],
  ])("is not sent %s", async (_, kept) => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0", kept);
    const fetchImpl = vi.fn(async () => json(200, pair(1)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    expect(await tokens.accessToken()).toBe("alpha-router-ext-at-1");
    const [body] = sent(fetchImpl);
    expect(body.attempt).toMatch(AN_ATTEMPT);
    expect(body.attempt).not.toBe(kept.attempt);
    expect(state.writes[0]).toBe("attempt");
  });

  it("goes with the tokens when they are dropped", async () => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0", KEPT);
    const { tokens } = manager(storage, vi.fn() as unknown as typeof fetch);
    await tokens.clear();
    expect(state.attempt).toBeNull();
    // Before the refresh token, since it holds a copy of it.
    expect(state.writes).toEqual(["access:cleared", "attempt:cleared", "refresh:cleared"]);
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

  it("waits for a refresh in flight before dropping the tokens, so it cannot bring them back", async () => {
    const { state, storage } = memoryStorage(ENDED, "alpha-router-ext-rt-0");
    let answer!: (response: Response) => void;
    const fetchImpl = vi.fn(() => new Promise<Response>((resolve) => (answer = resolve)));
    const { tokens } = manager(storage, fetchImpl as unknown as typeof fetch);
    const refreshing = tokens.accessToken();
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
    const clearing = tokens.clear();
    answer(json(200, pair(1)));
    expect(await refreshing).toBe("alpha-router-ext-at-1");
    await clearing;
    expect(state.access).toBeNull();
    expect(state.refresh).toBeNull();
    expect(state.attempt).toBeNull();
    expect(state.writes.slice(-3)).toEqual(["access:cleared", "attempt:cleared", "refresh:cleared"]);
  });

  it("refuses a response without tokens", async () => {
    const { storage } = memoryStorage(null, null);
    const { tokens } = manager(storage, vi.fn() as unknown as typeof fetch);
    await expect(tokens.save({ ...pair(1), refresh_token: "" })).rejects.toThrow("no tokens");
  });
});
