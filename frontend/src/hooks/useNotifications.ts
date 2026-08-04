import { useQuery } from "@tanstack/react-query";

import type {
  NotificationCountResponse,
  NotificationListResponse,
  NotificationRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListNotificationsApiV1NotificationsGetQueryKey,
  getUnreadNotificationsCountApiV1NotificationsUnreadCountGetQueryKey,
  listNotificationsApiV1NotificationsGet,
  markAllNotificationsReadApiV1NotificationsReadAllPost,
  markNotificationReadApiV1NotificationsNotificationIdReadPost,
  unreadNotificationsCountApiV1NotificationsUnreadCountGet,
} from "@/api/generated/notifications/notifications";
import { invalidateNotifications } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useNotifications = (options?: { enabled?: boolean; refetchInterval?: number }) => {
  return useQuery<NotificationListResponse>({
    queryKey: getListNotificationsApiV1NotificationsGetQueryKey(),
    queryFn: () => listNotificationsApiV1NotificationsGet(),
    enabled: options?.enabled,
    refetchInterval: options?.refetchInterval,
  });
};

export const useUnreadNotificationCount = (options?: { enabled?: boolean }) => {
  return useQuery<NotificationCountResponse>({
    queryKey: getUnreadNotificationsCountApiV1NotificationsUnreadCountGetQueryKey(),
    queryFn: () => unreadNotificationsCountApiV1NotificationsUnreadCountGet(),
    enabled: options?.enabled,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useMarkNotificationRead = (options?: MutationOpts<NotificationRead, number>) =>
  useApiMutation<NotificationRead, number>(
    {
      mutationFn: (notificationId) =>
        markNotificationReadApiV1NotificationsNotificationIdReadPost(notificationId),
      invalidate: () => invalidateNotifications(),
    },
    options
  );

export const useMarkAllNotificationsRead = (
  options?: MutationOpts<NotificationCountResponse, void>
) =>
  useApiMutation<NotificationCountResponse, void>(
    {
      mutationFn: () => markAllNotificationsReadApiV1NotificationsReadAllPost(),
      invalidate: () => invalidateNotifications(),
    },
    options
  );
