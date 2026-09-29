import { useEffect } from "react";

import { getAuthToken } from "@/api/client";
import { invalidate, q } from "@/api/query-keys";
import { useGuilds } from "@/hooks/useGuilds";
import { openLiveSocket } from "@/lib/liveSocket";
import { buildGuildWsUrl } from "@/lib/wsUrl";

/**
 * Subscribe to one resource's change signal and refetch it on every change, so
 * React Query reads the latest state through the normal endpoints. A frame
 * names a change and never carries the resource.
 *
 * Built on the shared live socket, so it authenticates in its first frame,
 * reconnects with jittered backoff, and notices a connection that has gone
 * quiet. The credential is read as each first frame is written, so a renewed
 * token does not tear the socket down; a reconnect refetches, since whatever
 * changed while it was away was said to nobody.
 */
const useResourceRealtime = (
  resourceId: number | null,
  resource: string,
  refetch: (resourceId: number) => void
): void => {
  const { activeGuildId } = useGuilds();

  useEffect(() => {
    if (!resourceId || !activeGuildId) return;

    let opened = 0;
    const connection = openLiveSocket({
      url: buildGuildWsUrl(activeGuildId, `${resource}/${resourceId}/ws`),
      // Null is fine — the server reads the session cookie, which is the web
      // path.
      auth: () => ({ token: getAuthToken() }),
      onFrame: (frame) => {
        if ((frame as { heartbeat?: boolean } | null)?.heartbeat) return;
        refetch(resourceId);
      },
      onStatus: (connected) => {
        if (!connected) return;
        opened += 1;
        if (opened > 1) refetch(resourceId);
      },
    });

    return () => connection.close();
  }, [resourceId, resource, refetch, activeGuildId]);
};

// Module-level invalidators so the effect's dependency stays stable.

const invalidateQueueRealtime = (queueId: number) => {
  void invalidate(q.queue(queueId), q.allQueues());
};

/** Subscribe to real-time queue updates; refetches detail + list on any event. */
export function useQueueRealtime(queueId: number | null): void {
  useResourceRealtime(queueId, "queues", invalidateQueueRealtime);
}

const invalidateCounterGroupRealtime = (groupId: number) => {
  void invalidate(q.counterGroup(groupId), q.allCounterGroups());
};

/** Subscribe to real-time counter group updates; refetches detail + list on any event. */
export function useCounterGroupRealtime(groupId: number | null): void {
  useResourceRealtime(groupId, "counter-groups", invalidateCounterGroupRealtime);
}
