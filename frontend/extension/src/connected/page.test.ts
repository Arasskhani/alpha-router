/**
 * @vitest-environment happy-dom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startConnect } from "../lib/connect";
import { createTokenManager, type StoredAccess, type TokenStorage } from "../lib/tokens";
import { installChromeFake, type ChromeFake } from "../test/chromeFake";
import { runConnectedPage } from "./page";

const SERVER = "https://ai.example.com";

let chromeFake: ChromeFake;

beforeEach(() => {
  chromeFake = installChromeFake();
  document.body.innerHTML = '<main id="root"></main>';
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
  return { state, tokens: createTokenManager({ storage, lock: (fn) => fn(), serverUrl: async () => SERVER, fetch: vi.fn() as unknown as typeof fetch }) };
}

async function run(search: string, fetchImpl: ReturnType<typeof vi.fn>) {
  const { state, tokens } = memoryTokens();
  const closeTab = vi.fn();
  const timers: Array<[() => void, number]> = [];
  const location = { search, pathname: "/connected.html" } as Location;
  const history = { replaceState: vi.fn() } as unknown as History;
  const result = await runConnectedPage(document, location, history, {
    tokens,
    serverUrl: async () => SERVER,
    fetch: fetchImpl as unknown as typeof fetch,
    closeTab,
    setTimeout: (fn, ms) => void timers.push([fn, ms]),
  });
  return { result, state, closeTab, timers, history };
}

async function attemptState(): Promise<string> {
  await startConnect(SERVER);
  const saved = (await chrome.storage.session.get("alpharouter.pending-connect"))["alpharouter.pending-connect"] as { state: string };
  return saved.state;
}

describe("connected.html", () => {
  it("finishes the connection, tells the panel and closes itself", async () => {
    const state = await attemptState();
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ access_token: "at", token_type: "Bearer", expires_in: 3600, refresh_token: "rt", session_id: "s1" })),
    );
    const { result, state: stored, closeTab, timers, history } = await run(`?code=abc&state=${state}`, fetchImpl);
    expect(result).toEqual({ kind: "connected" });
    expect(stored.refresh).toBe("rt");
    expect(document.querySelector("h1")?.textContent).toBe("Connected");
    expect(chromeFake.runtime.sent).toContainEqual({ type: "auth-changed" });
    // The code leaves the address bar before anything else happens.
    expect(history.replaceState).toHaveBeenCalledWith(null, "", "/connected.html");
    expect(timers).toHaveLength(1);
    timers[0][0]();
    expect(closeTab).toHaveBeenCalledOnce();
  });

  it("says so when the user said no, and closes", async () => {
    const state = await attemptState();
    const { result, timers } = await run(`?error=access_denied&state=${state}`, vi.fn());
    expect(result).toEqual({ kind: "denied" });
    expect(document.body.textContent).toContain("You chose not to connect");
    expect(timers).toHaveLength(1);
  });

  it("stays open with the reason when it failed", async () => {
    const { result, timers } = await run("?code=abc&state=not-ours", vi.fn());
    expect(result.kind).toBe("failed");
    expect(document.querySelector('[role="status"]')?.textContent).toContain("does not belong to a connection");
    expect(timers).toHaveLength(0);
    expect(chromeFake.runtime.sent).toEqual([]);
  });
});
