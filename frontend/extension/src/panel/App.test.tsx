/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createApi } from "../lib/api";
import { setClient } from "../lib/client";
import { resetConfigForTests } from "../lib/config";
import { createTokenManager, type PendingAttempt, type StoredAccess, type TokenStorage } from "../lib/tokens";
import { EXTENSION_ID, installChromeFake, type ChromeFake } from "../test/chromeFake";
import App from "./App";

const SERVER = "https://ai.example.com";
const NOW = Date.now();

const ME = {
  user: { username: "majid", display_name: "Majid A.", email: "m@example.com" },
  server: { name: "Alpharouter", url: SERVER },
  extension: { latest_version: "1.0.0.1", min_version: "1.0.0.0" },
  features: { chat: true, page_context: true, agent: false, auto_mode: false, private_mode: true },
  policy: { site_access: "per_site", allowed_sites: [], blocked_sites: [], page_content_models: [], agent_models: [], agent_max_steps: 25 },
};

let chromeFake: ChromeFake;
let host: HTMLDivElement;
let root: Root;
let routes: Record<string, (init?: RequestInit) => Response | Promise<Response>>;
let tokenState: { access: StoredAccess | null; refresh: string | null; attempt: PendingAttempt | null };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const serverFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  if (url.endsWith("/config.json")) return json(200, { serverUrl: SERVER, serverName: "Alpharouter", extensionVersion: "1.0.0.1" });
  const path = url.replace(SERVER, "");
  const route = routes[`${init?.method ?? "GET"} ${path}`];
  if (!route) throw new Error(`unexpected request ${init?.method ?? "GET"} ${path}`);
  return route(init);
});

function connectWith(access: StoredAccess | null, refresh: string | null) {
  tokenState = { access, refresh, attempt: null };
  const storage: TokenStorage = {
    getAccess: async () => tokenState.access,
    setAccess: async (v) => void (tokenState.access = v),
    getRefresh: async () => tokenState.refresh,
    setRefresh: async (v) => void (tokenState.refresh = v),
    getAttempt: async () => tokenState.attempt,
    setAttempt: async (v) => void (tokenState.attempt = v),
  };
  const serverUrl = async () => SERVER;
  const tokens = createTokenManager({ storage, lock: (fn) => fn(), serverUrl, fetch: serverFetch as unknown as typeof fetch });
  setClient({ tokens, api: createApi({ tokens, serverUrl, fetch: serverFetch as unknown as typeof fetch }) });
}

beforeEach(() => {
  chromeFake = installChromeFake();
  vi.stubGlobal("fetch", serverFetch);
  serverFetch.mockClear();
  resetConfigForTests();
  routes = {};
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  setClient(null);
  vi.unstubAllGlobals();
});

async function render() {
  await act(async () => {
    root.render(<App />);
  });
  await act(async () => undefined);
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((b) => b.textContent === label);
  if (!found) throw new Error(`no ${label} button in: ${host.textContent}`);
  return found;
}

describe("the side panel, not connected", () => {
  beforeEach(() => connectWith(null, null));

  it("offers to connect, and opens the consent page in a tab", async () => {
    await render();
    expect(host.textContent).toContain("Connect to Alpharouter");
    expect(host.textContent).toContain(SERVER);
    await act(async () => button("Connect").click());
    // Hashing the verifier finishes on a later turn of the event loop.
    await vi.waitFor(() => expect(chromeFake.tabs.created).toHaveLength(1));
    const [{ url }] = chromeFake.tabs.created;
    expect(url).toMatch(new RegExp(`^${SERVER}/extension/connect\\?`));
    expect(new URL(url!).searchParams.get("redirect_uri")).toBe(`chrome-extension://${EXTENSION_ID}/connected.html`);
    await vi.waitFor(() => expect(host.textContent).toContain("A tab opened on Alpharouter"));
  });

  it("forgets the attempt on Cancel", async () => {
    await render();
    await act(async () => button("Connect").click());
    await vi.waitFor(() => expect(host.textContent).toContain("A tab opened on Alpharouter"));
    await act(async () => button("Cancel").click());
    await act(async () => undefined);
    expect(await chrome.storage.session.get("alpharouter.pending-connect")).toEqual({});
    expect(host.textContent).toContain("Chat with your organization");
  });

  it("moves on when connected.html says the tokens arrived", async () => {
    routes["GET /api/extension/me"] = () => json(200, ME);
    routes["GET /api/chat/models"] = () => json(200, []);
    await render();
    tokenState.refresh = "rt";
    tokenState.access = { token: "at", expiresAt: NOW + 3_600_000, sessionId: "s1" };
    await act(async () => {
      chromeFake.runtime.deliver({ type: "auth-changed" }, { url: `chrome-extension://${EXTENSION_ID}/connected.html`, tab: { id: 4 } as chrome.tabs.Tab });
    });
    await act(async () => undefined);
    expect(host.textContent).toContain("Majid A.");
  });

  it("ignores the same message from a web page's content script", async () => {
    await render();
    tokenState.refresh = "rt";
    await act(async () => {
      chromeFake.runtime.deliver({ type: "auth-changed" }, { url: "https://evil.example/", tab: { id: 4 } as chrome.tabs.Tab });
    });
    expect(host.textContent).toContain("Connect to Alpharouter");
  });
});

describe("the side panel, connected", () => {
  beforeEach(() => {
    connectWith({ token: "at", expiresAt: NOW + 3_600_000, sessionId: "s1" }, "rt");
    routes["GET /api/chat/models"] = () => json(200, [{ id: "model::1", name: "GPT Test", kinds: ["text"] }]);
  });

  it("opens the chat for the user, and disconnects", async () => {
    routes["GET /api/extension/me"] = () => json(200, ME);
    const revoke = vi.fn(() => json(200, { ok: true }));
    routes["POST /api/extension/revoke"] = revoke;
    await render();
    expect(host.textContent).toContain("Ask anything, Majid A.");
    await act(async () => button("Disconnect").click());
    await act(async () => undefined);
    expect(revoke).toHaveBeenCalledOnce();
    expect(tokenState.refresh).toBeNull();
    expect(chromeFake.runtime.sent).toContainEqual({ type: "auth-changed" });
    expect(host.textContent).toContain("Connect to Alpharouter");
  });

  it("shows only the chat when the agent is not for this account", async () => {
    routes["GET /api/extension/me"] = () => json(200, ME);
    await render();
    expect(host.querySelector('[role="tablist"]')).toBeNull();
  });

  it("offers the chat and the agent side by side, and goes back to the chat for a right-click action", async () => {
    routes["GET /api/extension/me"] = () => json(200, { ...ME, features: { ...ME.features, agent: true } });
    await render();
    const tabs = [...host.querySelectorAll('[role="tab"]')] as HTMLButtonElement[];
    expect(tabs.map((t) => t.textContent)).toEqual(["Chat", "Agent"]);
    const agent = host.querySelector("main.agent") as HTMLElement;
    expect(agent.hidden).toBe(true);
    await act(async () => tabs[1].click());
    expect(agent.hidden).toBe(false);
    expect((host.querySelector(".shell__view") as HTMLElement).hidden).toBe(true);
    expect(host.textContent).toContain("Tell Alpharouter what to do in your browser.");
    // A right-click action or the shortcut left a question for the chat.
    await act(async () => {
      chromeFake.runtime.deliver({ type: "pending-action" });
    });
    await act(async () => undefined);
    expect(agent.hidden).toBe(true);
    expect((host.querySelector(".shell__view") as HTMLElement).hidden).toBe(false);
  });

  it("says when the extension is switched off for the user", async () => {
    routes["GET /api/extension/me"] = () => json(200, { ...ME, features: { ...ME.features, chat: false }, policy: null });
    await render();
    expect(host.textContent).toContain("not enabled for your account");
  });

  it("goes back to Connect when the server ended the session", async () => {
    routes["GET /api/extension/me"] = () => json(401, { detail: { code: "revoked", message: "This browser was disconnected." } });
    await render();
    expect(host.textContent).toContain("Connect to Alpharouter");
    expect(tokenState.refresh).toBeNull();
  });

  it("offers to try again when the server cannot be reached, keeping the tokens", async () => {
    routes["GET /api/extension/me"] = () => {
      throw new TypeError("Failed to fetch");
    };
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("could not be reached");
    expect(tokenState.refresh).toBe("rt");
    routes["GET /api/extension/me"] = () => json(200, ME);
    await act(async () => button("Try again").click());
    await act(async () => undefined);
    expect(host.textContent).toContain("Majid A.");
  });
});

describe("the side panel, when the answer does not come", () => {
  beforeEach(() => connectWith({ token: "at", expiresAt: NOW + 3_600_000, sessionId: "s1" }, "rt"));

  it("stops waiting for the server and offers to try again", async () => {
    const stop = new AbortController();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(stop.signal);
    try {
      routes["GET /api/extension/me"] = (init) =>
        new Promise<Response>((_, reject) =>
          init?.signal?.addEventListener("abort", () => reject(new DOMException("The operation timed out.", "TimeoutError"))),
        );
      await render();
      expect(host.querySelector("main")?.getAttribute("aria-busy")).toBe("true");
      await act(async () => stop.abort());
      await act(async () => undefined);
      expect(timeout).toHaveBeenCalledWith(15_000);
      expect(host.querySelector('[role="alert"]')?.textContent).toContain("could not be reached");
      expect(button("Try again")).toBeTruthy();
      expect(tokenState.refresh).toBe("rt");
    } finally {
      timeout.mockRestore();
    }
  });

  it("offers to try again when the panel cannot read its own storage", async () => {
    const failing = createTokenManager({
      storage: {
        getAccess: async () => null,
        setAccess: async () => undefined,
        getRefresh: async () => {
          throw new Error("IndexedDB is broken");
        },
        setRefresh: async () => undefined,
        getAttempt: async () => null,
        setAttempt: async () => undefined,
      },
      lock: (fn) => fn(),
      serverUrl: async () => SERVER,
      fetch: serverFetch as unknown as typeof fetch,
    });
    setClient({ tokens: failing, api: createApi({ tokens: failing, serverUrl: async () => SERVER, fetch: serverFetch as unknown as typeof fetch }) });
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("Something went wrong.");
    expect(button("Try again")).toBeTruthy();
  });
});

describe("a copy that belongs to no server", () => {
  it("says where to get one", async () => {
    connectWith(null, null);
    serverFetch.mockImplementationOnce(async () => json(200, { serverUrl: "" }));
    await render();
    expect(host.textContent).toContain("belongs to no Alpharouter server");
  });
});
