const STATIC_CACHE = "initiative-static-v1";
const DATA_CACHE = "initiative-data-v1";
const STATIC_ASSETS = ["/", "/index.html", "/manifest.webmanifest", "/icons/logo.svg"];

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
            if (![STATIC_CACHE, DATA_CACHE].includes(key)) {
              return caches.delete(key);
            }
            return null;
          })
        )
      )
      .then(() => self.clients.claim())
  );
});

const API_PATTERN = /\/api\/v1\/(projects|tasks)/;

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  if (API_PATTERN.test(new URL(request.url).pathname)) {
    event.respondWith(
      caches.open(DATA_CACHE).then(async (cache) => {
        try {
          const networkResponse = await fetch(request);
          cache.put(request, networkResponse.clone());
          return networkResponse;
        } catch {
          const cached = await cache.match(request);
          if (cached) {
            return cached;
          }
          throw new Error("Network error and no cached data available");
        }
      })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          const responseClone = response.clone();
          caches.open(STATIC_CACHE).then((cache) => cache.put(request, responseClone));
          return response;
        })
    )
  );
});
