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
  Notification,
  NotificationCountResponse,
  NotificationListResponse,
} from "@/types/api";

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

export const useMarkNotificationRead = () => {
  return useMutation({
    mutationFn: async (notificationId: number) => {
      return markNotificationReadApiV1NotificationsNotificationIdReadPost(
        notificationId
      ) as unknown as Promise<Notification>;
    },
    onSuccess: () => {
      void invalidateNotifications();
    },
  });
};

export const useMarkAllNotificationsRead = () => {
  return useMutation({
    mutationFn: async () => {
      return markAllNotificationsReadApiV1NotificationsReadAllPost() as unknown as Promise<NotificationCountResponse>;
    },
    onSuccess: () => {
      void invalidateNotifications();
    },
  });
};
