/**
 * The extension's tokens, and the only code that refreshes them.
 *
 * - The access token (one hour) lives in chrome.storage.session: memory only,
 *   gone when the browser closes, and readable by the extension's own pages
 *   alone (content scripts are refused by default).
 * - The refresh token lives in the extension's IndexedDB: it survives a
 *   restart, and a content script - which runs with the page's origin - has
 *   no way to reach it. storage.local would not do: content scripts can read
 *   it.
 *
 * Refreshing is single-flight across every page of the extension (a Web Lock),
 * and the lock holder re-reads storage first: whoever waited behind a refresh
 * uses its result instead of spending the refresh token again. A lost response
 * is retried once; the server hands out the same pair for a retry within its
 * two-minute grace.
 *
 * Outcomes: a token; DisconnectedError (the server refused the refresh token -
 * connect again); TemporaryError (network, 429, 5xx - the tokens are kept and
 * the caller tries later).
 */

export type StoredAccess = { token: string; expiresAt: number; sessionId: string };

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
  session_id: string;
};

export interface TokenStorage {
  getAccess(): Promise<StoredAccess | null>;
  setAccess(value: StoredAccess | null): Promise<void>;
  getRefresh(): Promise<string | null>;
  setRefresh(value: string | null): Promise<void>;
}

/** Runs `fn` while holding the extension-wide token lock. */
export type Lock = <T>(fn: () => Promise<T>) => Promise<T>;

export class DisconnectedError extends Error {
  constructor(message = "This browser is not connected to Alpharouter.") {
    super(message);
    this.name = "DisconnectedError";
  }
}

export class TemporaryError extends Error {
  constructor(message = "Alpharouter could not be reached. Trying again shortly.") {
    super(message);
    this.name = "TemporaryError";
  }
}

/** An access token this close to its end is treated as ended. */
const EXPIRY_MARGIN_MS = 60_000;
const REFRESH_TIMEOUT_MS = 30_000;

export type TokenManagerDeps = {
  storage: TokenStorage;
  lock: Lock;
  serverUrl: () => Promise<string>;
  fetch: typeof fetch;
  now?: () => number;
  /** Called once the server has refused the refresh token and the tokens are gone. */
  onDisconnected?: () => void;
};

export type TokenManager = ReturnType<typeof createTokenManager>;

export function createTokenManager(deps: TokenManagerDeps) {
  const now = deps.now ?? Date.now;

  function usable(access: StoredAccess | null): access is StoredAccess {
    return Boolean(access && access.token && access.expiresAt - EXPIRY_MARGIN_MS > now());
  }

  async function save(response: TokenResponse): Promise<void> {
    if (!response.access_token || !response.refresh_token) throw new Error("The server sent no tokens.");
    // The refresh token first: a crash between the two writes then leaves a
    // new refresh token and an old access token, which the next call replaces.
    await deps.storage.setRefresh(response.refresh_token);
    await deps.storage.setAccess({
      token: response.access_token,
      expiresAt: now() + Math.max(0, Number(response.expires_in) || 0) * 1000,
      sessionId: response.session_id,
    });
  }

  async function clearStored(): Promise<void> {
    await deps.storage.setAccess(null);
    await deps.storage.setRefresh(null);
  }

  /**
   * Drop the tokens. Under the lock: a refresh in flight finishes first, so it
   * cannot save a new pair afterwards and connect the browser again.
   */
  async function clear(): Promise<void> {
    await deps.lock(clearStored);
  }

  /** The server said this browser is disconnected: drop the tokens and say so. */
  async function forget(): Promise<void> {
    await clear();
    deps.onDisconnected?.();
  }

  /** forget(), for the refresh, which already holds the lock (it is not reentrant). */
  async function forgetLocked(): Promise<void> {
    await clearStored();
    deps.onDisconnected?.();
  }

  async function isConnected(): Promise<boolean> {
    return Boolean(await deps.storage.getRefresh());
  }

  async function sessionId(): Promise<string | null> {
    return (await deps.storage.getAccess())?.sessionId ?? null;
  }

  async function post(refreshToken: string): Promise<Response> {
    const url = `${await deps.serverUrl()}/api/extension/token`;
    return deps.fetch(url, {
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ grant_type: "refresh_token", refresh_token: refreshToken }),
      signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
    });
  }

  /** Spend the refresh token. Only ever called while holding the lock. */
  async function refreshLocked(): Promise<string> {
    const refreshToken = await deps.storage.getRefresh();
    if (!refreshToken) throw new DisconnectedError();
    let response: Response | null = null;
    for (let attempt = 0; attempt < 2 && !response; attempt += 1) {
      try {
        response = await post(refreshToken);
      } catch {
        response = null; // A lost response: the same token gets the same pair again.
      }
    }
    if (!response) throw new TemporaryError();
    if (response.ok) {
      const body = (await response.json()) as TokenResponse;
      await save(body);
      return body.access_token;
    }
    if (response.status === 400) {
      // invalid_grant: revoked, expired, or signed out everywhere. Any other
      // 400 can never succeed either, and retrying it forever helps nobody.
      const message = await refusalMessage(response);
      await forgetLocked();
      throw new DisconnectedError(message);
    }
    throw new TemporaryError();
  }

  /** A usable access token, refreshing first when the stored one has ended. */
  async function accessToken(): Promise<string> {
    const stored = await deps.storage.getAccess();
    if (usable(stored)) return stored.token;
    return deps.lock(async () => {
      const again = await deps.storage.getAccess();
      if (usable(again)) return again.token; // Refreshed while we waited.
      return refreshLocked();
    });
  }

  /** After a 401 for `rejected`: a new token, unless another page already replaced it. */
  async function replaceRejected(rejected: string): Promise<string> {
    return deps.lock(async () => {
      const again = await deps.storage.getAccess();
      if (usable(again) && again.token !== rejected) return again.token;
      return refreshLocked();
    });
  }

  return { save, clear, forget, isConnected, sessionId, accessToken, replaceRejected };
}

async function refusalMessage(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: { message?: unknown } };
    return typeof body.detail?.message === "string" ? body.detail.message : undefined;
  } catch {
    return undefined;
  }
}
