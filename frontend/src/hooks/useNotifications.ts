import {
  type QueryClient,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import type {
  NotificationCountResponse,
  NotificationListResponse,
  NotificationRead,
  UnreadPlacesResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  dismissNotificationApiV1NotificationsNotificationIdDelete,
  getListNotificationsApiV1NotificationsGetQueryKey,
  getUnreadNotificationPlacesApiV1NotificationsUnreadGetQueryKey,
  listNotificationsApiV1NotificationsGet,
  markAllNotificationsReadApiV1NotificationsReadAllPost,
  markNotificationReadApiV1NotificationsNotificationIdReadPost,
  markNotificationUnreadApiV1NotificationsNotificationIdUnreadPost,
  unreadNotificationPlacesApiV1NotificationsUnreadGet,
} from "@/api/generated/notifications/notifications";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

// How many rows one request carries. The popover takes every page until the
// cursor runs out, so this is a transport size, not a cap on what it shows.
export const NOTIFICATION_PAGE_SIZE = 50;

// ── Queries ─────────────────────────────────────────────────────────────────

// `refetchInterval: false` turns polling off — what a caller passes once the
// notification push channel is carrying the updates instead.
export const useNotifications = (options?: {
  enabled?: boolean;
  refetchInterval?: number | false;
  unreadOnly?: boolean;
  guildId?: number;
  personalOnly?: boolean;
}) => {
  return useQuery<NotificationListResponse>({
    queryKey: getListNotificationsApiV1NotificationsGetQueryKey({
      limit: NOTIFICATION_PAGE_SIZE,
      unread_only: options?.unreadOnly,
      guild_id: options?.guildId,
      personal_only: options?.personalOnly,
    }),
    queryFn: () =>
      listNotificationsApiV1NotificationsGet({
        limit: NOTIFICATION_PAGE_SIZE,
        unread_only: options?.unreadOnly,
        guild_id: options?.guildId,
        personal_only: options?.personalOnly,
      }),
    enabled: options?.enabled,
    refetchInterval: options?.refetchInterval,
  });
};

/**
 * The inbox page's list: every notification, read and unread, a page at a time.
 *
 * The popover holds what is still unread; this is the record, so it is not
 * filtered by default and it goes back as far as somebody scrolls.
 */
export const useNotificationHistory = (options?: {
  enabled?: boolean;
  unreadOnly?: boolean;
  guildId?: number;
  personalOnly?: boolean;
}) => {
  const params = {
    limit: NOTIFICATION_PAGE_SIZE,
    unread_only: options?.unreadOnly,
    guild_id: options?.guildId,
    personal_only: options?.personalOnly,
  };
  return useInfiniteQuery({
    queryKey: [...getListNotificationsApiV1NotificationsGetQueryKey(params), "history"],
    queryFn: ({ pageParam }) =>
      listNotificationsApiV1NotificationsGet({
        ...params,
        cursor: (pageParam as string | undefined) ?? undefined,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: NotificationListResponse) => last.next_cursor ?? undefined,
    enabled: options?.enabled,
  });
};

/**
 * Where there is unread activity, as a set of places rather than a count.
 *
 * A place is (community, initiative, tool) with every level optional, so a node
 * in the navigation shows a dot when any place names it as an ancestor. A
 * direct message names none of them, which is why "is anything unread at all"
 * is just this list being non-empty.
 */
export const useUnreadPlaces = (options?: {
  enabled?: boolean;
  refetchInterval?: number | false;
}) => {
  return useQuery<UnreadPlacesResponse>({
    queryKey: getUnreadNotificationPlacesApiV1NotificationsUnreadGetQueryKey(),
    queryFn: () => unreadNotificationPlacesApiV1NotificationsUnreadGet(),
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
  // Every cached list, not one: the popover asks with `unread_only` and the
  // inbox page with its own filters, so they are separate cache entries and a
  // read has to reach all of them.
  client.setQueriesData<NotificationListResponse>(
    { queryKey: getListNotificationsApiV1NotificationsGetQueryKey() },
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
      invalidate: () => invalidate(q.notifications()),
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

export const useMarkNotificationUnread = (options?: MutationOpts<NotificationRead, number>) => {
  const client = useQueryClient();
  return useApiMutation<NotificationRead, number>(
    {
      mutationFn: (notificationId) =>
        markNotificationUnreadApiV1NotificationsNotificationIdUnreadPost(notificationId),
      invalidate: () => invalidate(q.notifications()),
    },
    {
      ...options,
      onSettled: (...args) => {
        void client.invalidateQueries({
          queryKey: getListNotificationsApiV1NotificationsGetQueryKey(),
        });
        void client.invalidateQueries({
          queryKey: getUnreadNotificationPlacesApiV1NotificationsUnreadGetQueryKey(),
        });
        options?.onSettled?.(...args);
      },
    }
  );
};

export const useDismissNotification = (options?: MutationOpts<void, number>) => {
  const client = useQueryClient();
  return useApiMutation<void, number>(
    {
      mutationFn: (notificationId) =>
        dismissNotificationApiV1NotificationsNotificationIdDelete(notificationId),
      invalidate: () => invalidate(q.notifications()),
    },
    {
      ...options,
      onSettled: (...args) => {
        void client.invalidateQueries({
          queryKey: getListNotificationsApiV1NotificationsGetQueryKey(),
        });
        void client.invalidateQueries({
          queryKey: getUnreadNotificationPlacesApiV1NotificationsUnreadGetQueryKey(),
        });
        options?.onSettled?.(...args);
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
      invalidate: () => invalidate(q.notifications()),
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
