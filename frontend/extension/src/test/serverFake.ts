/**
 * A pretend Alpharouter server for panel tests: routes by method and path,
 * a connected client wired to it, and chat streams the test controls.
 */

import { vi } from "vitest";

import { createApi } from "../lib/api";
import { setClient } from "../lib/client";
import { createTokenManager, type StoredAccess, type TokenStorage } from "../lib/tokens";

export const SERVER = "https://ai.example.com";

type Route = (init: RequestInit & { url: string }) => Response | Promise<Response>;

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const frame = (value: unknown) => `data: ${JSON.stringify(value)}\n\n`;
export const textFrame = (content: string) => frame({ choices: [{ delta: { content } }] });

/**
 * A text/event-stream response. With `open`, it stays open until the test
 * calls finish(), and an abort signal on the request errors it as fetch would.
 */
export function sse(frames: string[], options: { open?: boolean; signal?: AbortSignal | null } = {}) {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
      for (const f of frames) c.enqueue(encoder.encode(f));
      if (!options.open) c.close();
    },
  });
  options.signal?.addEventListener("abort", () => {
    try {
      controller.error(new DOMException("The operation was aborted.", "AbortError"));
    } catch {
      // Already closed.
    }
  });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    push: (f: string) => controller.enqueue(encoder.encode(f)),
    finish: () => controller.close(),
  };
}

export function createServerFake() {
  const routes: Record<string, Route> = {};
  /** Routes matched by a pattern over "METHOD /path", for ids the code makes up. */
  const patterns: Array<[RegExp, Route]> = [];
  const calls: Array<{ method: string; path: string; body: unknown; headers: Headers }> = [];
  const tokenState: { access: StoredAccess | null; refresh: string | null } = {
    access: { token: "at", expiresAt: Date.now() + 3_600_000, sessionId: "s1" },
    refresh: "rt",
  };

  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    if (url.endsWith("/config.json")) return json(200, { serverUrl: SERVER, serverName: "Alpharouter", extensionVersion: "1.0.0.1" });
    const method = init.method ?? "GET";
    const path = url.replace(SERVER, "");
    let body: unknown = init.body;
    if (typeof init.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }
    calls.push({ method, path, body, headers: new Headers(init.headers) });
    const key = `${method} ${path}`;
    const route = routes[key] ?? patterns.find(([pattern]) => pattern.test(key))?.[1];
    if (!route) throw new Error(`unexpected request ${key}`);
    return route({ ...init, url });
  });

  const storage: TokenStorage = {
    getAccess: async () => tokenState.access,
    setAccess: async (v) => void (tokenState.access = v),
    getRefresh: async () => tokenState.refresh,
    setRefresh: async (v) => void (tokenState.refresh = v),
  };
  const serverUrl = async () => SERVER;
  const tokens = createTokenManager({ storage, lock: (fn) => fn(), serverUrl, fetch: fetchImpl as unknown as typeof fetch });
  setClient({ tokens, api: createApi({ tokens, serverUrl, fetch: fetchImpl as unknown as typeof fetch }) });
  vi.stubGlobal("fetch", fetchImpl);

  return {
    routes,
    patterns,
    calls,
    tokenState,
    fetch: fetchImpl,
    /** The requests made to one route, oldest first. */
    callsTo: (method: string, path: string) => calls.filter((c) => c.method === method && c.path === path),
  };
}

export type ServerFake = ReturnType<typeof createServerFake>;
