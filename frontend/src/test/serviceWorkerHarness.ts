/**
 * Runs a script from public/ as if it were a service worker, with a fake
 * worker global: event listeners, Cache Storage, fetch and the registration.
 * Enough for the Alpharouter worker and its retirement script, no more.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";

const ORIGIN = "https://alpharouter.example";

type Listener = (event: unknown) => void;

/** A request as the worker sees it; mode "navigate" cannot be built with new Request() in Node. */
export type FakeRequest = { url: string; mode: string; method: string };

export function publicScript(name: string): string {
  return readFileSync(join(__dirname, "..", "..", "public", name), "utf8");
}

export function runWorker(
  source: string,
  options: { fetch?: (request: unknown) => Promise<Response> } = {},
) {
  const listeners = new Map<string, Listener>();
  const stores = new Map<string, Map<string, Response>>();
  const absolute = (input: unknown) =>
    new URL(typeof input === "string" ? input : (input as { url: string }).url, ORIGIN).href;

  const network = vi.fn(options.fetch ?? (async () => new Response("from the network", { status: 200 })));
  const cacheFor = (name: string) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name)!;
    return {
      add: async (request: unknown) => {
        const response = await network(request);
        if (!response.ok) throw new TypeError(`cache.add: ${response.status}`);
        store.set(absolute(request), response);
      },
      put: async (request: unknown, response: Response) => void store.set(absolute(request), response),
      match: async (request: unknown) => store.get(absolute(request))?.clone(),
    };
  };
  const caches = {
    open: vi.fn(async (name: string) => cacheFor(name)),
    keys: vi.fn(async () => [...stores.keys()]),
    delete: vi.fn(async (name: string) => stores.delete(name)),
    match: vi.fn(async (request: unknown, opts?: { cacheName?: string }) => {
      const names = opts?.cacheName ? [opts.cacheName] : [...stores.keys()];
      for (const name of names) {
        const hit = stores.get(name)?.get(absolute(request));
        if (hit) return hit.clone();
      }
      return undefined;
    }),
  };
  const self = {
    location: new URL(`${ORIGIN}/sw.js`),
    addEventListener: (type: string, listener: Listener) => void listeners.set(type, listener),
    skipWaiting: vi.fn(async () => undefined),
    clients: { claim: vi.fn(async () => undefined) },
    registration: { unregister: vi.fn(async () => true) },
  };
  class WorkerRequest extends Request {
    constructor(input: string, init?: RequestInit) {
      super(new URL(input, ORIGIN).href, init);
    }
  }

  new Function("self", "caches", "fetch", "Request", source)(self, caches, network, WorkerRequest);

  /** Fire a lifecycle event and wait for everything it passed to waitUntil. */
  async function lifecycle(type: "install" | "activate", extra: Record<string, unknown> = {}) {
    const pending: Promise<unknown>[] = [];
    listeners.get(type)?.({ ...extra, waitUntil: (p: Promise<unknown>) => void pending.push(p) });
    await Promise.all(pending);
  }

  /** Fire a fetch event. Resolves to the worker's answer, or undefined when it let the request through. */
  async function dispatchFetch(request: Partial<FakeRequest> & { url: string }): Promise<Response | undefined> {
    let answer: Promise<Response> | undefined;
    const full = { mode: "navigate", method: "GET", ...request, url: new URL(request.url, ORIGIN).href };
    listeners.get("fetch")?.({ request: full, respondWith: (p: Promise<Response>) => (answer = p) });
    return answer;
  }

  return { self, caches, stores, network, listeners, lifecycle, dispatchFetch };
}
