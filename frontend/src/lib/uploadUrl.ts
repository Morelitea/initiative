import { Capacitor } from "@capacitor/core";

import { apiClient } from "@/api/client";
import { getUploadToken } from "@/lib/uploadToken";

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

  const baseUrl = apiClient.defaults.baseURL;
  let origin = "";
  if (baseUrl) {
    try {
      origin = new URL(baseUrl).origin;
    } catch {
      origin = baseUrl.replace(/\/api\/v1\/?$/, "");
    }
  }
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
    const baseUrl = apiClient.defaults.baseURL;
    if (baseUrl) {
      try {
        // Extract origin from the API base URL (e.g., "http://10.0.2.2:8000/api/v1" -> "http://10.0.2.2:8000")
        const url = new URL(baseUrl);
        resolved = `${url.origin}${normalizedPath}`;
      } catch {
        // If URL parsing fails, try stripping /api/v1 suffix
        const origin = baseUrl.replace(/\/api\/v1\/?$/, "");
        resolved = origin ? `${origin}${normalizedPath}` : normalizedPath;
      }
    } else {
      resolved = normalizedPath;
    }
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
