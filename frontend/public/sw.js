// Alpharouter service worker: makes the app installable and shows our own page
// when the server cannot be reached.
//
// It caches one file, /offline.html, and answers only GET page loads of app
// routes (/, /login, /app/*, /admin/*). Everything else - API calls, chat
// streams, uploads, media, /assets, SSO callbacks under /api, POST navigations
// such as the SAML post - never reaches respondWith and goes to the network
// exactly as it would without a worker. The rule is an allow-list, so a route
// added to the backend later cannot be caught by accident.
//
// It does not cache the app itself: an installed app would then start an old
// build after every upgrade, and it needs the server for everything anyway.
//
// Served by the backend's /sw.js route with Cache-Control: no-cache. With
// PWA_SERVICE_WORKER_ENABLED=false that route serves sw-retire.js instead.

// First 12 hex digits of sha256(offline.html); a unit test keeps it in step.
const OFFLINE_REV = "c56aa2593062";
const CACHE = `alpharouter-offline-${OFFLINE_REV}`;
const OFFLINE_URL = "/offline.html";
const APP_ROUTE = /^\/(?:$|login$|app(?:\/|$)|admin(?:\/|$))/;

self.addEventListener("install", (event) => {
  // Any fetch handler makes every request wait for the worker to start, even
  // one it lets through. Where the browser supports static routing (Chrome 123
  // and later), requests that are not page loads - API calls, chat streams,
  // uploads, media - go straight to the network without starting the worker.
  // Feature-detected and never allowed to fail the install; other browsers
  // keep the small delay.
  try {
    if (typeof event.addRoutes === "function") {
      event.waitUntil(
        Promise.resolve(
          event.addRoutes([{ condition: { not: { requestMode: "navigate" } }, source: "network" }]),
        ).catch(() => undefined),
      );
    }
  } catch {
    // An older rule syntax: the fetch handler below still lets these through.
  }
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      // If this fails the install fails and the worker is simply not used; the
      // browser tries again on a later page load.
      await cache.add(new Request(OFFLINE_URL, { cache: "reload" }));
      // Safe: the worker serves no application code, so an old page and a new
      // worker cannot disagree.
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const key of await caches.keys()) {
        if (key.startsWith("alpharouter-") && key !== CACHE) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.mode !== "navigate" || request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !APP_ROUTE.test(url.pathname)) return;

  event.respondWith(
    (async () => {
      // Our page if it is cached; otherwise whatever we had (the proxy's page, or the browser's error).
      const fallback = async (original) =>
        (await caches.match(OFFLINE_URL, { cacheName: CACHE })) ?? original ?? Response.error();
      try {
        const response = await fetch(request);
        // A proxy saying the app is down (an upgrade, a restart): our page, not nginx's.
        // App routes only ever return index.html, so this hides no real error.
        return response.status === 502 || response.status === 503 || response.status === 504
          ? await fallback(response)
          : response;
      } catch {
        return fallback(undefined);
      }
    })(),
  );
});
