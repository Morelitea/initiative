import { Capacitor } from "@capacitor/core";

import { apiClient } from "@/api/client";
import { getUploadToken } from "@/lib/uploadToken";

/**
 * The root the API server is addressed at: its origin plus whatever path the
 * deployment is served under — "https://example.com/initiative" for a base URL
 * of "https://example.com/initiative/api/v1". "" when it can't be determined.
 *
 * Only meaningful on native: there the web bundle is served from its own local
 * origin, so a same-origin path resolves inside the bundle rather than at the
 * server that returned it. The path prefix is kept because a server reached at
 * one is reached there for everything — `normalizeServerUrl` preserves it when
 * the address is entered, so dropping it here would address a different root.
 */
function apiServerBase(): string {
  const baseUrl = apiClient.defaults.baseURL;
  if (!baseUrl) {
    return "";
  }
  const withoutApiPath = baseUrl.replace(/\/api\/v1\/?$/, "");
  try {
    const url = new URL(withoutApiPath);
    return `${url.origin}${url.pathname.replace(/\/$/, "")}`;
  } catch {
    // Not parseable as absolute (a same-origin base URL): nothing to prepend.
    return withoutApiPath.replace(/\/$/, "");
  }
}

/**
 * Resolve an `/api/v1/...` path for a request that can't carry an Authorization
 * header — a download served via iframe/window.open, or a `keepalive`/sendBeacon
 * POST fired on page unload. On native platforms, prepends the API server origin
 * and appends a SHORT-LIVED, uploads-scoped ?token= for auth (native WebViews
 * can't send Authorization headers or HttpOnly cookies). The long-lived session
 * JWT is never put in a URL — see {@link getUploadToken}. On web, returns the API
 * path as-is (same-origin, the HttpOnly session cookie handles auth — send the
 * request with `credentials: "include"`).
 */
export function resolveHeaderlessApiUrl(apiPath: string): string {
  if (!Capacitor.isNativePlatform()) {
    return apiPath;
  }

  const origin = apiServerBase();
  const resolved = origin ? `${origin}${apiPath}` : apiPath;
  const token = getUploadToken();
  if (token) {
    const sep = resolved.includes("?") ? "&" : "?";
    return `${resolved}${sep}token=${encodeURIComponent(token)}`;
  }
  return resolved;
}

/**
 * Resolve a document ID to its authorized download URL (current version).
 *
 * The download is guild-scoped (``/g/{guildId}/…``): served via iframe/
 * window.open, which can't send headers, so the guild rides in the path.
 */
export function resolveDocumentDownloadUrl(
  documentId: number,
  guildId: number,
  inline = false
): string | null {
  if (!documentId || !guildId) {
    return null;
  }
  const base = `/api/v1/g/${guildId}/documents/${documentId}/download`;
  return resolveHeaderlessApiUrl(inline ? `${base}?inline=1` : base);
}

/**
 * Resolve the authorized download URL for a specific stored version of a file
 * document. Shares the native-platform auth handling with
 * {@link resolveDocumentDownloadUrl}.
 */
export function resolveDocumentVersionDownloadUrl(
  documentId: number,
  versionId: number,
  guildId: number,
  inline = false
): string | null {
  if (!documentId || !versionId || !guildId) {
    return null;
  }
  const base = `/api/v1/g/${guildId}/documents/${documentId}/versions/${versionId}/download`;
  return resolveHeaderlessApiUrl(inline ? `${base}?inline=1` : base);
}

/**
 * Resolve an upload path to a full URL.
 * On native platforms, prepends the API server URL (no proxy available).
 * On web, returns the path as-is (Vite proxies /uploads in dev, same-origin in prod).
 */
export function resolveUploadUrl(path: string | null | undefined): string | null {
  if (!path) {
    return null;
  }

  // If it's already an absolute URL, return as-is
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }

  // If it's a data URI (base64), return as-is
  if (path.startsWith("data:")) {
    return path;
  }

  // Ensure path starts with /
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  let resolved: string;

  // On native platforms, prepend the API server origin (no Vite proxy)
  if (Capacitor.isNativePlatform()) {
    // e.g. "http://10.0.2.2:8000/api/v1" -> "http://10.0.2.2:8000/uploads/..."
    const origin = apiServerBase();
    resolved = origin ? `${origin}${normalizedPath}` : normalizedPath;
  } else {
    // On web, return path as-is - Vite proxies /uploads in dev, same-origin in prod
    resolved = normalizedPath;
  }

  // On native: append a short-lived, uploads-scoped token for /uploads/ paths so
  // <img> src attributes work (native WebViews can't send Authorization headers
  // or rely on HttpOnly cookies for media). The long-lived session JWT is never
  // placed in a URL — see getUploadToken.
  // On web: the HttpOnly session cookie is sent automatically by the browser — no token needed
  if (normalizedPath.startsWith("/uploads/") && Capacitor.isNativePlatform()) {
    const token = getUploadToken();
    if (token) {
      const sep = resolved.includes("?") ? "&" : "?";
      return `${resolved}${sep}token=${encodeURIComponent(token)}`;
    }
  }

  return resolved;
}

/**
 * Resolve a catalog artwork path — a marketplace listing's icon or screenshot,
 * and the artwork an installed app carries — to something a native WebView can
 * load.
 *
 * Two kinds of same-origin path arrive here. Artwork this build ships
 * (`/marketplace/…`, `/icons/…`) is already inside the native bundle, so it
 * stays relative — resolving it against the server would fetch a file that is
 * local. Artwork a registry's listings are served from lives only on the API
 * (`/api/v1/marketplace/media/…`); on native the bundle is its own origin, so
 * that path has to be addressed at the API origin or it resolves to nothing.
 * The media route is public and unauthenticated, so no token is added.
 */
export function resolveArtworkUrl(path: string | null | undefined): string | null {
  if (!path) {
    return null;
  }
  if (path.startsWith("http://") || path.startsWith("https://") || path.startsWith("data:")) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!Capacitor.isNativePlatform() || !normalizedPath.startsWith("/api/")) {
    return normalizedPath;
  }

  const origin = apiServerBase();
  return origin ? `${origin}${normalizedPath}` : normalizedPath;
}
