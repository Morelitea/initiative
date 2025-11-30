const STATIC_CACHE = "initiative-static-v2";
const DATA_CACHE = "initiative-data-v1";
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

  if (!STATIC_ASSETS.includes(requestPath)) {
    event.respondWith(fetch(request));
    return;
  }

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
});
