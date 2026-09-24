// Alpharouter: served as /sw.js while PWA_SERVICE_WORKER_ENABLED=false.
// It replaces the real worker on each device the next time the app is opened,
// deletes Alpharouter's caches and unregisters itself. Pages keep working; they
// are simply no longer controlled by a service worker.
self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const key of await caches.keys()) {
        if (key.startsWith("alpharouter-")) await caches.delete(key);
      }
      await self.registration.unregister();
    })(),
  );
});
