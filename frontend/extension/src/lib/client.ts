/**
 * The extension's token manager and API client, wired to the real browser.
 *
 * Created on first use; tests put their own in place with setClient().
 */

import { createApi } from "./api";
import { serverUrl } from "./config";
import { broadcast } from "./messages";
import { browserTokenStorage, tokenLock } from "./storage";
import { createTokenManager, type TokenManager } from "./tokens";

export type Client = { tokens: TokenManager; api: ReturnType<typeof createApi> };

let current: Client | null = null;

function browserClient(): Client {
  const request: typeof fetch = (input, init) => fetch(input, init);
  const tokens = createTokenManager({
    storage: browserTokenStorage,
    lock: tokenLock,
    serverUrl,
    fetch: request,
    onDisconnected: () => void broadcast({ type: "auth-changed" }),
  });
  return { tokens, api: createApi({ tokens, serverUrl, fetch: request }) };
}

export function getClient(): Client {
  current ??= browserClient();
  return current;
}

export function setClient(client: Client | null): void {
  current = client;
}
