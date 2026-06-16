import { Capacitor } from "@capacitor/core";

import { apiClient } from "@/api/client";

/**
 * Native-only scoped upload-token cache.
 *
 * Native (Capacitor) WebViews can't attach the Authorization header or the
 * HttpOnly session cookie to <img>/<iframe> media loads, so those URLs carry
 * auth as a `?token=` query param. We must NOT put the long-lived session JWT
 * there (it leaks via logs, history, and Referer). Instead the app mints a
 * short-lived, uploads-scoped token from `POST /api/v1/auth/upload-token` and
 * stamps that into the URL.
 *
 * `resolveUploadUrl`/`resolveDownloadApiPath` are synchronous (they're called
 * during render), so this module keeps the current token in memory and serves
 * it synchronously while refreshing it in the background before it expires.
 * On web this module is never exercised — cookie auth handles media loads.
 */

interface CachedUploadToken {
  token: string;
  // Epoch millis at which the token is treated as stale and refreshed.
  refreshAt: number;
}

let cached: CachedUploadToken | null = null;
let inFlight: Promise<string | null> | null = null;
// Bumped by clearUploadToken (logout / server switch). A refresh that was
// already in flight when the cache was cleared must not commit its result —
// otherwise a freshly-minted token (valid ~10 min server-side) silently
// re-enters the cache after logout and gets stamped into media URLs.
let generation = 0;

// Refresh this many milliseconds before the server-reported expiry so a token
// stamped into a URL is still valid by the time the media request lands. The
// server lifetime is ~10 min; we refresh with a minute of headroom.
const REFRESH_SKEW_MS = 60_000;

/**
 * Force a network refresh of the scoped upload token. Concurrent callers share
 * a single in-flight request. Returns the new token, or null on failure (caller
 * falls back to whatever it has, or to an unauthenticated URL).
 */
export const refreshUploadToken = async (): Promise<string | null> => {
  if (inFlight) {
    return inFlight;
  }
  const requestGeneration = generation;
  inFlight = (async () => {
    try {
      const { data } = await apiClient.post<{
        upload_token: string;
        expires_in: number;
      }>("/auth/upload-token");
      if (generation !== requestGeneration) {
        // clearUploadToken ran while this request was in flight (logout):
        // drop the result instead of reviving the cleared cache.
        return null;
      }
      const lifetimeMs = Math.max(0, (data.expires_in ?? 0) * 1000);
      cached = {
        token: data.upload_token,
        refreshAt: Date.now() + Math.max(0, lifetimeMs - REFRESH_SKEW_MS),
      };
      return cached.token;
    } catch {
      // Leave any existing cached token in place; a transient failure
      // shouldn't blank out media that's currently rendering.
      return generation === requestGeneration ? (cached?.token ?? null) : null;
    } finally {
      if (generation === requestGeneration) {
        inFlight = null;
      }
    }
  })();
  return inFlight;
};

/**
 * Synchronously return the current scoped upload token for stamping into a
 * native media URL. Triggers a background refresh when the cached token is
 * missing or nearing expiry; returns the (possibly slightly stale) cached
 * token meanwhile, or null if we've never fetched one yet.
 */
export const getUploadToken = (): string | null => {
  if (!Capacitor.isNativePlatform()) {
    return null;
  }
  if (!cached || Date.now() >= cached.refreshAt) {
    // Fire-and-forget; the next render picks up the refreshed token.
    void refreshUploadToken();
  }
  return cached?.token ?? null;
};

/** Drop the cached token (e.g. on logout / server switch). */
export const clearUploadToken = (): void => {
  generation += 1;
  cached = null;
  inFlight = null;
};
