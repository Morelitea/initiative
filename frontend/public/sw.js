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
const AUTH_PATTERN = /\/api\/v1\/auth\//;

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  const requestUrl = new URL(request.url);
  const requestPath = requestUrl.pathname;

  if (AUTH_PATTERN.test(requestPath)) {
    event.respondWith(fetch(request));
    return;
  }

  if (API_PATTERN.test(requestPath)) {
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

  if (requestPath.startsWith("/api/")) {
    event.respondWith(fetch(request));
    return;
  }

  const isStaticAsset = STATIC_ASSETS.includes(requestPath) || request.mode === "navigate";

  if (!isStaticAsset) {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith(
    caches.open(STATIC_CACHE).then(async (cache) => {
      const cached = await cache.match(requestPath === "/" ? "index.html" : requestPath);
      if (cached) {
        return cached;
      }
      const response = await fetch(request);
      // Only cache successful responses
      if (response.ok) {
        const cacheKey = requestPath === "/" ? "index.html" : requestPath;
        await cache.put(cacheKey, response.clone());
      }
      return response;
    })
  );
});
