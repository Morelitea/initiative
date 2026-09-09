import fs from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

/**
 * `public/sw.js` ships as-is and is never imported by the app, so it is loaded
 * here the way a browser loads it: evaluated against a `self` of our own.
 *
 * What these guard is one distinction that is easy to lose. Returning from the
 * fetch handler leaves a request to the browser; `event.respondWith(fetch(request))`
 * looks like the same thing but re-issues it *from the worker*, a separate
 * context with its own rules about what it is allowed to load. The native app
 * talks to an API on another origin, and laundering those requests through the
 * worker is how they end up blocked.
 */

const ORIGIN = "https://app.example";

type FetchEvent = {
  request: { url: string; method: string; mode?: string };
  respondWith: ReturnType<typeof vi.fn>;
};

const loadServiceWorker = () => {
  const source = fs.readFileSync(path.resolve(__dirname, "../../public/sw.js"), "utf-8");

  const handlers: Record<string, (event: unknown) => void> = {};
  const self = {
    addEventListener: (type: string, handler: (event: unknown) => void) => {
      handlers[type] = handler;
    },
    location: { origin: ORIGIN },
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn() },
  };
  const caches = {
    open: vi.fn().mockResolvedValue({ match: vi.fn(), put: vi.fn(), addAll: vi.fn() }),
    keys: vi.fn().mockResolvedValue([]),
  };
  // Enough of a Response for the branches that do serve a request: they clone
  // it into the cache and check whether it was ok.
  const fetchStub = vi.fn().mockResolvedValue({ ok: true, clone: () => ({}) });

  // eslint-disable-next-line no-new-func -- loading a worker script, not app code
  new Function("self", "caches", "fetch", source)(self, caches, fetchStub);

  return (request: FetchEvent["request"]): FetchEvent => {
    const event: FetchEvent = { request, respondWith: vi.fn() };
    handlers.fetch?.(event);
    return event;
  };
};

const get = (url: string, mode = "cors") => ({ url, method: "GET", mode });

describe("the service worker's fetch handler", () => {
  it("leaves another origin's request to the browser", () => {
    const dispatch = loadServiceWorker();

    const event = dispatch(get("http://10.0.2.2:8000/api/v1/version"));

    expect(event.respondWith).not.toHaveBeenCalled();
  });

  it("leaves an API request alone rather than re-issuing it", () => {
    const dispatch = loadServiceWorker();

    const event = dispatch(get(`${ORIGIN}/api/v1/me/tasks`));

    expect(event.respondWith).not.toHaveBeenCalled();
  });

  it("leaves a hashed asset to the browser", () => {
    const dispatch = loadServiceWorker();

    const event = dispatch(get(`${ORIGIN}/assets/index-abc123.js`));

    expect(event.respondWith).not.toHaveBeenCalled();
  });

  it("ignores anything that is not a GET", () => {
    const dispatch = loadServiceWorker();

    const event = dispatch({ url: `${ORIGIN}/api/v1/tasks`, method: "POST" });

    expect(event.respondWith).not.toHaveBeenCalled();
  });

  it("still serves a navigation, which is what it caches for", () => {
    const dispatch = loadServiceWorker();

    const event = dispatch(get(`${ORIGIN}/c/1/projects`, "navigate"));

    expect(event.respondWith).toHaveBeenCalled();
  });

  it("still serves the static assets it keeps a copy of", () => {
    const dispatch = loadServiceWorker();

    const event = dispatch(get(`${ORIGIN}/manifest.webmanifest`));

    expect(event.respondWith).toHaveBeenCalled();
  });
});
