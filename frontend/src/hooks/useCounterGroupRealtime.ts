import { useEffect, useRef } from "react";

import { API_BASE_URL } from "@/api/client";
import { invalidateAllCounterGroups, invalidateCounterGroup } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";

/**
 * Subscribe to real-time counter group updates via WebSocket.
 *
 * Invalidates both the group detail and the list on every event so
 * React Query refetches the latest state.
 */
export function useCounterGroupRealtime(groupId: number | null): void {
  const wsRef = useRef<WebSocket | null>(null);
  const { token } = useAuth();
  const { activeGuildId } = useGuilds();

  useEffect(() => {
    if (!groupId || !activeGuildId) return;

    const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
    const url = isAbsolute ? new URL(API_BASE_URL) : new URL(API_BASE_URL, window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const normalizedPath = url.pathname.endsWith("/")
      ? url.pathname.slice(0, -1)
      : url.pathname || "/api/v1";
    url.pathname = `${normalizedPath}/g/${activeGuildId}/counter-groups/${groupId}/ws`;

    const ws = new WebSocket(url.toString());
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token: token ?? null }));
    };

    ws.onmessage = () => {
      void invalidateCounterGroup(groupId);
      void invalidateAllCounterGroups();
    };

    ws.onclose = () => {
      wsRef.current = null;
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [groupId, token, activeGuildId]);
}
