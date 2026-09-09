const STATIC_CACHE = "initiative-static-v3";
const STATIC_ASSETS = ["/manifest.webmanifest", "/icons/logo.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.map((key) => {
            if (key !== STATIC_CACHE) {
              return caches.delete(key);
            }
            return null;
          })
        )
      )
      .then(() => self.clients.claim())
  );
});

// API responses are not cached here. Cache Storage is keyed by URL alone, with
// no notion of who asked, how long an entry should live, or when to drop it.
// Offline reading is handled in src/lib/offlineCache.ts, which has answers for
// all three.

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  const requestUrl = new URL(request.url);

  // Only this app's own origin is ours to answer. In the native app the API is
  // a different origin entirely, and taking one of its requests over here would
  // re-issue it from the worker — a separate context, with its own rules about
  // what it may load, and nothing gained by the move.
  if (requestUrl.origin !== self.location.origin) {
    return;
  }

  const requestPath = requestUrl.pathname;

  // Not cached here (see above), so there is nothing to add: leaving it alone
  // is what passing it through means.
  if (requestPath.startsWith("/api/")) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          const networkResponse = await fetch(request);
          const cache = await caches.open(STATIC_CACHE);
          cache.put("index.html", networkResponse.clone());
          return networkResponse;
        } catch (error) {
          const cache = await caches.open(STATIC_CACHE);
          const cachedPage = await cache.match("index.html");
          if (cachedPage) {
            return cachedPage;
          }
          throw error;
        }
      })()
    );
    return;
  }

  if (STATIC_ASSETS.includes(requestPath)) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(async (cache) => {
        const cached = await cache.match(requestPath);
        if (cached) {
          return cached;
        }
        const response = await fetch(request);
        if (response.ok) {
          await cache.put(requestPath, response.clone());
        }
        return response;
      })
    );
    return;
  }

  // Everything else — the hashed Vite assets included — is left to the browser.
  // `respondWith(fetch(request))` reads as "pass it through", but it moves the
  // request into the worker to do nothing with it.
});
