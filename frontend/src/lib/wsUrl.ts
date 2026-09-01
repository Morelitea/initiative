import { API_BASE_URL } from "@/api/client";

/**
 * Build the ws/wss URL for an API WebSocket endpoint from the API base (which
 * may be relative in dev, where Vite proxies it). `subpath` is relative to the
 * API root, e.g. `notifications/stream`.
 */
export const buildApiWsUrl = (subpath: string): string => {
  const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
  const url = isAbsolute ? new URL(API_BASE_URL) : new URL(API_BASE_URL, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const normalizedPath = url.pathname.endsWith("/")
    ? url.pathname.slice(0, -1)
    : url.pathname || "/api/v1";
  url.pathname = `${normalizedPath}/${subpath}`;
  url.search = "";
  url.hash = "";
  return url.toString();
};

/**
 * Build the ws/wss URL for a guild-scoped WebSocket endpoint. `subpath` is
 * relative to the guild root, e.g. `queues/5/ws`.
 */
export const buildGuildWsUrl = (guildId: number, subpath: string): string =>
  buildApiWsUrl(`g/${guildId}/${subpath}`);
