// Kill switch. The service worker caused stale assets more than once, and a
// private always-connected bridge gains little from offline caching. This version
// removes the worker entirely: on activate it deletes every cache, unregisters
// itself, and reloads any open tabs onto fresh network assets. app.js no longer
// registers a worker, so a fresh load never brings one back.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
      await self.registration.unregister();
      const clients = await self.clients.matchAll({ type: "window" });
      for (const c of clients) {
        try {
          c.navigate(c.url); // reload each tab onto the fresh, uncached files
        } catch (_) {
          /* some browsers disallow navigate(); a manual reload still recovers */
        }
      }
    })(),
  );
});

// No fetch handler: every request goes straight to the network.
