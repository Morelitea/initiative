import { useMutation, useQuery } from "@tanstack/react-query";

import {
  listNotificationsApiV1NotificationsGet,
  getListNotificationsApiV1NotificationsGetQueryKey,
  unreadNotificationsCountApiV1NotificationsUnreadCountGet,
  getUnreadNotificationsCountApiV1NotificationsUnreadCountGetQueryKey,
  markNotificationReadApiV1NotificationsNotificationIdReadPost,
  markAllNotificationsReadApiV1NotificationsReadAllPost,
} from "@/api/generated/notifications/notifications";
import { invalidateNotifications } from "@/api/query-keys";
import type {
  NotificationCountResponse,
  NotificationListResponse,
  NotificationRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useNotifications = (options?: { enabled?: boolean; refetchInterval?: number }) => {
  return useQuery<NotificationListResponse>({
    queryKey: getListNotificationsApiV1NotificationsGetQueryKey(),
    queryFn: () =>
      listNotificationsApiV1NotificationsGet() as unknown as Promise<NotificationListResponse>,
    enabled: options?.enabled,
    refetchInterval: options?.refetchInterval,
  });
};

export const useUnreadNotificationCount = (options?: { enabled?: boolean }) => {
  return useQuery<NotificationCountResponse>({
    queryKey: getUnreadNotificationsCountApiV1NotificationsUnreadCountGetQueryKey(),
    queryFn: () =>
      unreadNotificationsCountApiV1NotificationsUnreadCountGet() as unknown as Promise<NotificationCountResponse>,
    enabled: options?.enabled,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useMarkNotificationRead = (options?: MutationOpts<NotificationRead, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (notificationId: number) => {
      return markNotificationReadApiV1NotificationsNotificationIdReadPost(
        notificationId
      ) as unknown as Promise<NotificationRead>;
    },
    onSuccess: (...args) => {
      void invalidateNotifications();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useMarkAllNotificationsRead = (
  options?: MutationOpts<NotificationCountResponse, void>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async () => {
      return markAllNotificationsReadApiV1NotificationsReadAllPost() as unknown as Promise<NotificationCountResponse>;
    },
    onSuccess: (...args) => {
      void invalidateNotifications();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};
