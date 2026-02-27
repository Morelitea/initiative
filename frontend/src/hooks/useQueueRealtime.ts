import { useEffect, useRef } from "react";

import { API_BASE_URL } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { invalidateAllQueues, invalidateQueue } from "@/api/query-keys";

/**
 * Subscribe to real-time queue updates via WebSocket.
 *
 * On any incoming message the hook invalidates both the specific queue
 * and the queue list so React Query re-fetches the latest state.
 *
 * Authentication is sent as the first message after the socket opens,
 * matching the pattern used by the collaboration WebSocket.
 */
export function useQueueRealtime(queueId: number | null): void {
  const wsRef = useRef<WebSocket | null>(null);
  const { token } = useAuth();
  const { activeGuildId } = useGuilds();

  useEffect(() => {
    if (!queueId || !activeGuildId) return;

    // Build the WebSocket URL from the API base
    const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
    const url = isAbsolute ? new URL(API_BASE_URL) : new URL(API_BASE_URL, window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const normalizedPath = url.pathname.endsWith("/")
      ? url.pathname.slice(0, -1)
      : url.pathname || "/api/v1";
    url.pathname = `${normalizedPath}/queues/${queueId}/ws`;

    const ws = new WebSocket(url.toString());
    wsRef.current = ws;

    ws.onopen = () => {
      // Send auth payload; token may be null for cookie-based web sessions
      ws.send(JSON.stringify({ token: token ?? null, guild_id: activeGuildId }));
    };

    ws.onmessage = () => {
      // Invalidate cache on any queue event for simplicity
      void invalidateQueue(queueId);
      void invalidateAllQueues();
    };

    ws.onclose = () => {
      wsRef.current = null;
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [queueId, token, activeGuildId]);
}
