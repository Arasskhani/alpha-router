/**
 * public/sw.js: installability and an offline page, nothing else. It caches
 * only offline.html and answers only GET page loads of app routes.
 */
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { publicScript, runWorker } from "../test/serviceWorkerHarness";

const SOURCE = publicScript("sw.js");
const OFFLINE_HTML = "<!DOCTYPE html><title>Offline</title>";

/** A worker whose network serves offline.html and answers page loads with `page`. */
function worker(page: () => Promise<Response> = async () => new Response("the app", { status: 200 })) {
  return runWorker(SOURCE, {
    fetch: async (request) => {
      const url = typeof request === "string" ? request : (request as { url: string }).url;
      return url.endsWith("/offline.html") ? new Response(OFFLINE_HTML, { status: 200 }) : page();
    },
  });
}

async function installed(page?: () => Promise<Response>) {
  const w = worker(page);
  await w.lifecycle("install");
  await w.lifecycle("activate");
  w.network.mockClear();
  return w;
}

describe("installing", () => {
  it("caches offline.html and nothing else, fresh from the network", async () => {
    const w = worker();
    await w.lifecycle("install");
    const [name] = await w.caches.keys();
    expect(name).toMatch(/^alpharouter-offline-[0-9a-f]{12}$/);
    expect([...w.stores.get(name)!.keys()]).toEqual(["https://alpharouter.example/offline.html"]);
    expect((w.network.mock.calls[0][0] as Request).cache).toBe("reload");
    expect(w.self.skipWaiting).toHaveBeenCalled();
  });

  it("fails, and so is not used, when offline.html cannot be fetched", async () => {
    const w = runWorker(SOURCE, { fetch: async () => new Response("gone", { status: 404 }) });
    await expect(w.lifecycle("install")).rejects.toThrow();
    expect(w.self.skipWaiting).not.toHaveBeenCalled();
  });

  it("names its cache after offline.html's content, so a changed page is fetched again", () => {
    const rev = createHash("sha256").update(publicScript("offline.html")).digest("hex").slice(0, 12);
    // After editing offline.html, set OFFLINE_REV in sw.js to this value.
    expect(SOURCE).toContain(`const OFFLINE_REV = "${rev}";`);
  });
});

describe("activating", () => {
  it("deletes older Alpharouter caches only, and takes control of open pages", async () => {
    const w = worker();
    await (await w.caches.open("alpharouter-offline-000000000000")).put("/offline.html", new Response("old"));
    await (await w.caches.open("another-app")).put("/x", new Response("theirs"));
    await w.lifecycle("install");
    await w.lifecycle("activate");
    const keys = await w.caches.keys();
    expect(keys).toContain("another-app");
    expect(keys.filter((k) => k.startsWith("alpharouter-"))).toHaveLength(1);
    expect(keys).not.toContain("alpharouter-offline-000000000000");
    expect(w.self.clients.claim).toHaveBeenCalled();
  });
});

describe("what it answers", () => {
  it("lets every request that is not a page load through untouched", async () => {
    const w = await installed();
    for (const mode of ["cors", "no-cors", "same-origin"]) {
      for (const url of ["/api/chat/completions", "/assets/index-abc.js", "/api/media/1", "/app/chat"]) {
        expect(await w.dispatchFetch({ url, mode })).toBeUndefined();
      }
    }
    expect(w.network).not.toHaveBeenCalled();
  });

  it("lets a POST page load through, such as the SAML post", async () => {
    const w = await installed();
    expect(await w.dispatchFetch({ url: "/api/auth/saml/acs", method: "POST" })).toBeUndefined();
    expect(await w.dispatchFetch({ url: "/app/chat", method: "POST" })).toBeUndefined();
  });

  it("lets page loads outside the app's routes through: SSO callbacks, the gateway, probes, other sites", async () => {
    const w = await installed();
    for (const url of [
      "/api/auth/oidc/callback?code=1",
      "/api/auth/logout",
      "/v1/models",
      "/health",
      "/ready",
      "/metrics",
      "/docs",
      "/offline.html",
      "/application",
      "/administrator",
      "/loginx",
      "https://idp.example.com/app/sso",
    ]) {
      expect(await w.dispatchFetch({ url }), url).toBeUndefined();
    }
  });

  it("answers page loads of app routes from the network first", async () => {
    const w = await installed();
    for (const url of ["/", "/login", "/login?code=abc", "/app", "/app/chat", "/admin", "/admin/users"]) {
      const answer = await w.dispatchFetch({ url });
      expect(answer, url).toBeDefined();
      expect(await answer!.text()).toBe("the app");
    }
    expect(w.network).toHaveBeenCalledTimes(7);
  });

  it("passes the server's own answers through, errors included", async () => {
    for (const status of [200, 404, 500]) {
      const w = await installed(async () => new Response(`status ${status}`, { status }));
      const answer = await w.dispatchFetch({ url: "/app/chat" });
      expect(answer!.status).toBe(status);
      expect(await answer!.text()).toBe(`status ${status}`);
    }
  });

  it("shows our page when the network fails", async () => {
    const w = await installed(async () => {
      throw new TypeError("Failed to fetch");
    });
    const answer = await w.dispatchFetch({ url: "/app/chat" });
    expect(await answer!.text()).toBe(OFFLINE_HTML);
  });

  it("shows our page when a proxy says the app is down (502, 503, 504)", async () => {
    for (const status of [502, 503, 504]) {
      const w = await installed(async () => new Response("nginx error page", { status }));
      const answer = await w.dispatchFetch({ url: "/admin/users" });
      expect(await answer!.text(), String(status)).toBe(OFFLINE_HTML);
    }
  });

  it("falls back to what it had when its page is missing from the cache", async () => {
    const proxy = await installed(async () => new Response("nginx error page", { status: 503 }));
    proxy.stores.clear();
    const answer = await proxy.dispatchFetch({ url: "/app/chat" });
    expect(answer!.status).toBe(503);
    expect(await answer!.text()).toBe("nginx error page");

    const offline = await installed(async () => {
      throw new TypeError("Failed to fetch");
    });
    offline.stores.clear();
    expect((await offline.dispatchFetch({ url: "/app/chat" }))!.type).toBe("error");
  });
});
