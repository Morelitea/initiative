import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  NotificationCountResponse,
  NotificationListResponse,
  NotificationRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListNotificationsApiV1NotificationsGetQueryKey,
  listNotificationsApiV1NotificationsGet,
  markAllNotificationsReadApiV1NotificationsReadAllPost,
  markNotificationReadApiV1NotificationsNotificationIdReadPost,
} from "@/api/generated/notifications/notifications";
import { invalidateNotifications } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

// ── Queries ─────────────────────────────────────────────────────────────────

// `refetchInterval: false` turns polling off — what a caller passes once the
// notification push channel is carrying the updates instead.
export const useNotifications = (options?: {
  enabled?: boolean;
  refetchInterval?: number | false;
}) => {
  return useQuery<NotificationListResponse>({
    queryKey: getListNotificationsApiV1NotificationsGetQueryKey(),
    queryFn: () => listNotificationsApiV1NotificationsGet(),
    enabled: options?.enabled,
    refetchInterval: options?.refetchInterval,
  });
};

// ── Reading, applied before the server has said so ──────────────────────────

/**
 * Fold a read into the cached inbox.
 *
 * Marking read is a statement about the reader, not a negotiation: the badge
 * and the dot move on the click, and the refetch that follows settles it. What
 * this removes is the wait, which on a notification you are already navigating
 * away from was the whole of what you saw.
 *
 * A failure invalidates, so the server's answer replaces this rather than the
 * optimistic state standing.
 */
const applyRead = (client: QueryClient, matches: (notification: NotificationRead) => boolean) =>
  client.setQueryData<NotificationListResponse>(
    getListNotificationsApiV1NotificationsGetQueryKey(),
    (current) => {
      if (!current) {
        return current;
      }
      const readAt = new Date().toISOString();
      let cleared = 0;
      const notifications = current.notifications.map((notification) => {
        if (notification.read_at || !matches(notification)) {
          return notification;
        }
        cleared += 1;
        return { ...notification, read_at: readAt };
      });
      if (cleared === 0) {
        return current;
      }
      return {
        ...current,
        notifications,
        unread_count: Math.max(0, current.unread_count - cleared),
      };
    }
  );

// ── Mutations ───────────────────────────────────────────────────────────────

export const useMarkNotificationRead = (options?: MutationOpts<NotificationRead, number>) => {
  // The client this component reads from, not the module's own: the optimistic
  // write has to land in the cache the badge is rendered off.
  const client = useQueryClient();
  return useApiMutation<NotificationRead, number>(
    {
      mutationFn: (notificationId) =>
        markNotificationReadApiV1NotificationsNotificationIdReadPost(notificationId),
      invalidate: () => invalidateNotifications(),
    },
    {
      ...options,
      onMutate: (...args) => {
        const [notificationId] = args;
        applyRead(client, (notification) => notification.id === notificationId);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        // The optimistic read gives way to what the server says rather than
        // standing; `invalidate` above only fires on success.
        void client.invalidateQueries({
          queryKey: getListNotificationsApiV1NotificationsGetQueryKey(),
        });
        options?.onError?.(...args);
      },
    }
  );
};

export const useMarkAllNotificationsRead = (
  options?: MutationOpts<NotificationCountResponse, void>
) => {
  const client = useQueryClient();
  return useApiMutation<NotificationCountResponse, void>(
    {
      mutationFn: () => markAllNotificationsReadApiV1NotificationsReadAllPost(),
      invalidate: () => invalidateNotifications(),
    },
    {
      ...options,
      onMutate: (...args) => {
        applyRead(client, () => true);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        void client.invalidateQueries({
          queryKey: getListNotificationsApiV1NotificationsGetQueryKey(),
        });
        options?.onError?.(...args);
      },
    }
  );
};
