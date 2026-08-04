import { useEffect, useRef } from "react";

import {
  invalidateAllCounterGroups,
  invalidateAllQueues,
  invalidateCounterGroup,
  invalidateQueue,
} from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { buildGuildWsUrl } from "@/lib/wsUrl";

/**
 * Subscribe to a resource's realtime WebSocket and invalidate its queries on
 * every event, so React Query refetches the latest state through the normal
 * endpoints. The socket carries no resource content — it is a change signal
 * only. Authentication is sent as the first message after the socket opens,
 * matching the collaboration WebSocket.
 */
const useResourceRealtime = (
  resourceId: number | null,
  resource: string,
  invalidate: (resourceId: number) => void
): void => {
  const wsRef = useRef<WebSocket | null>(null);
  const { token } = useAuth();
  const { activeGuildId } = useGuilds();

  useEffect(() => {
    if (!resourceId || !activeGuildId) return;

    const ws = new WebSocket(buildGuildWsUrl(activeGuildId, `${resource}/${resourceId}/ws`));
    wsRef.current = ws;

    ws.onopen = () => {
      // Token may be null for cookie-based web sessions.
      ws.send(JSON.stringify({ token: token ?? null }));
    };

    ws.onmessage = () => {
      invalidate(resourceId);
    };

    ws.onclose = () => {
      wsRef.current = null;
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [resourceId, resource, invalidate, token, activeGuildId]);
};

// Module-level invalidators so the effect's dependency stays stable.

const invalidateQueueRealtime = (queueId: number) => {
  void invalidateQueue(queueId);
  void invalidateAllQueues();
};

/** Subscribe to real-time queue updates; refetches detail + list on any event. */
export function useQueueRealtime(queueId: number | null): void {
  useResourceRealtime(queueId, "queues", invalidateQueueRealtime);
}

const invalidateCounterGroupRealtime = (groupId: number) => {
  void invalidateCounterGroup(groupId);
  void invalidateAllCounterGroups();
};

/** Subscribe to real-time counter group updates; refetches detail + list on any event. */
export function useCounterGroupRealtime(groupId: number | null): void {
  useResourceRealtime(groupId, "counter-groups", invalidateCounterGroupRealtime);
}
