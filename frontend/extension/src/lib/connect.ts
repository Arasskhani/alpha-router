/**
 * Connecting this browser to Alpharouter, and disconnecting it.
 *
 * 1. The panel keeps a PKCE verifier and a state in session storage (the
 *    extension's own pages only) and opens the server's consent page in a tab.
 * 2. The user, signed in there as usual (SSO and two-factor included), allows
 *    it. The server sends the tab to connected.html with a one-time code.
 * 3. connected.html checks the state, trades the code and the verifier for
 *    tokens, and tells the panel.
 *
 * The code is useless without the verifier, which never left the extension,
 * and the state ties the answer to the attempt this browser started.
 */

import { challengeFor, createState, createVerifier } from "./pkce";
import type { TokenManager, TokenResponse } from "./tokens";

const PENDING_KEY = "alpharouter.pending-connect";
/** An attempt older than this is dropped: the server's code lives two minutes anyway. */
export const CONNECT_ATTEMPT_MS = 10 * 60 * 1000;

type Pending = { state: string; verifier: string; createdAt: number };

function connectedPageUrl(): string {
  // Built by hand, not with getURL: the server accepts chrome-extension://
  // only, and this is that, in Chrome and Edge alike.
  return `chrome-extension://${chrome.runtime.id}/connected.html`;
}

/** The consent page's address for a new attempt, which is remembered until it ends. */
export async function startConnect(server: string, now: number = Date.now()): Promise<string> {
  const verifier = createVerifier();
  const state = createState();
  const pending: Pending = { state, verifier, createdAt: now };
  await chrome.storage.session.set({ [PENDING_KEY]: pending });
  const params = new URLSearchParams({
    redirect_uri: connectedPageUrl(),
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
    state,
  });
  return `${server}/extension/connect?${params.toString()}`;
}

export async function hasPendingConnect(now: number = Date.now()): Promise<boolean> {
  const pending = (await chrome.storage.session.get(PENDING_KEY))[PENDING_KEY] as Pending | undefined;
  return Boolean(pending && now - pending.createdAt < CONNECT_ATTEMPT_MS);
}

export async function cancelConnect(): Promise<void> {
  await chrome.storage.session.remove(PENDING_KEY);
}

/** "Chrome on Windows": shown in Settings → Extension to tell browsers apart. */
export function deviceName(nav: Navigator = navigator): string {
  const data = (nav as Navigator & { userAgentData?: { brands?: Array<{ brand: string }>; platform?: string } }).userAgentData;
  const ua = nav.userAgent || "";
  const brands = (data?.brands ?? []).map((b) => b.brand);
  const browser =
    brands.includes("Microsoft Edge") || /\bEdg\//.test(ua)
      ? "Edge"
      : brands.includes("Google Chrome") || /\bChrome\//.test(ua)
        ? "Chrome"
        : brands.includes("Chromium")
          ? "Chromium"
          : "Browser";
  const platform = data?.platform || (/Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "");
  return platform ? `${browser} on ${platform}` : browser;
}

export type ConnectResult =
  | { kind: "connected" }
  | { kind: "denied" }
  | { kind: "failed"; message: string };

export type FinishDeps = {
  tokens: TokenManager;
  serverUrl: () => Promise<string>;
  fetch: typeof fetch;
  now?: () => number;
};

/** connected.html's half: check the answer, trade the code, keep the tokens. */
export async function finishConnect(search: string, deps: FinishDeps): Promise<ConnectResult> {
  const params = new URLSearchParams(search);
  const state = params.get("state") ?? "";
  const pending = (await chrome.storage.session.get(PENDING_KEY))[PENDING_KEY] as Pending | undefined;
  const now = (deps.now ?? Date.now)();
  if (!pending || !state || pending.state !== state) {
    return { kind: "failed", message: "This answer does not belong to a connection this browser started. Start again from the extension's side panel." };
  }
  // One answer per attempt, whatever it is.
  await cancelConnect();
  if (now - pending.createdAt >= CONNECT_ATTEMPT_MS) {
    return { kind: "failed", message: "That took too long. Start again from the extension's side panel." };
  }
  if (params.get("error")) return { kind: "denied" };
  const code = params.get("code");
  if (!code) return { kind: "failed", message: "Alpharouter sent no connect code. Start again from the extension's side panel." };

  let response: Response;
  try {
    response = await deps.fetch(`${await deps.serverUrl()}/api/extension/token`, {
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "authorization_code",
        code,
        code_verifier: pending.verifier,
        redirect_uri: connectedPageUrl(),
        device_name: deviceName(),
      }),
    });
  } catch {
    return { kind: "failed", message: "Alpharouter could not be reached. Check your connection and start again." };
  }
  if (!response.ok) {
    let message = "Alpharouter refused the connection. Start again from the extension's side panel.";
    try {
      const body = (await response.json()) as { detail?: { message?: unknown } | string };
      if (typeof body.detail === "string") message = body.detail;
      else if (typeof body.detail?.message === "string") message = body.detail.message;
    } catch {
      // Keep the general message.
    }
    return { kind: "failed", message };
  }
  await deps.tokens.save((await response.json()) as TokenResponse);
  return { kind: "connected" };
}

/** How long Disconnect waits for the server before it lets go of the tokens anyway. */
const REVOKE_TIMEOUT_MS = 10_000;

/**
 * End this browser's connection: the server first (best effort, and not for
 * longer than `timeoutMs`), then the tokens here, whatever the server did.
 */
export async function disconnect(
  tokens: TokenManager,
  revoke: (signal: AbortSignal) => Promise<unknown>,
  timeoutMs: number = REVOKE_TIMEOUT_MS,
): Promise<void> {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), timeoutMs);
  const gaveUp = new Promise<never>((_, reject) => stop.signal.addEventListener("abort", () => reject(new Error("timeout"))));
  try {
    await Promise.race([revoke(stop.signal), gaveUp]);
  } catch {
    // Already ended, unreachable, or too slow: the tokens still go.
  } finally {
    clearTimeout(timer);
    stop.abort();
    await tokens.clear();
  }
}
