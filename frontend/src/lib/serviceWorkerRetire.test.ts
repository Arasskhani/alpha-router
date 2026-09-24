/**
 * public/sw-retire.js: what /sw.js serves while PWA_SERVICE_WORKER_ENABLED=false.
 * It takes over at once, deletes Alpharouter's caches and unregisters.
 */
import { describe, expect, it } from "vitest";

import { publicScript, runWorker } from "../test/serviceWorkerHarness";

describe("the retirement script", () => {
  it("takes over from the real worker at once", async () => {
    const worker = runWorker(publicScript("sw-retire.js"));
    await worker.lifecycle("install");
    expect(worker.self.skipWaiting).toHaveBeenCalled();
  });

  it("deletes only Alpharouter's caches and unregisters itself", async () => {
    const worker = runWorker(publicScript("sw-retire.js"));
    await (await worker.caches.open("alpharouter-offline-abc")).put("/offline.html", new Response("x"));
    await (await worker.caches.open("someone-else")).put("/x", new Response("y"));
    await worker.lifecycle("activate");
    expect(await worker.caches.keys()).toEqual(["someone-else"]);
    expect(worker.self.registration.unregister).toHaveBeenCalledTimes(1);
  });

  it("answers no request", async () => {
    const worker = runWorker(publicScript("sw-retire.js"));
    expect(worker.listeners.has("fetch")).toBe(false);
  });
});
