import { Capacitor } from "@capacitor/core";
import { apiClient } from "@/api/client";

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

  // On native platforms, prepend the API server origin (no Vite proxy)
  if (Capacitor.isNativePlatform()) {
    const baseUrl = apiClient.defaults.baseURL;
    if (baseUrl) {
      try {
        // Extract origin from the API base URL (e.g., "http://10.0.2.2:8000/api/v1" -> "http://10.0.2.2:8000")
        const url = new URL(baseUrl);
        return `${url.origin}${normalizedPath}`;
      } catch {
        // If URL parsing fails, try stripping /api/v1 suffix
        const origin = baseUrl.replace(/\/api\/v1\/?$/, "");
        if (origin) {
          return `${origin}${normalizedPath}`;
        }
      }
    }
  }

  // On web, return path as-is - Vite proxies /uploads in dev, same-origin in prod
  return path;
}
