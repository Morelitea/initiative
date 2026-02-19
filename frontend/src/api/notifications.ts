import {
  listNotificationsApiV1NotificationsGet,
  unreadNotificationsCountApiV1NotificationsUnreadCountGet,
  markNotificationReadApiV1NotificationsNotificationIdReadPost,
  markAllNotificationsReadApiV1NotificationsReadAllPost,
} from "@/api/generated/notifications/notifications";
import type {
  Notification,
  NotificationCountResponse,
  NotificationListResponse,
} from "@/types/api";

export const fetchNotifications = async () => {
  return listNotificationsApiV1NotificationsGet() as unknown as Promise<NotificationListResponse>;
};

export const fetchUnreadNotificationCount = async () => {
  return unreadNotificationsCountApiV1NotificationsUnreadCountGet() as unknown as Promise<NotificationCountResponse>;
};

export const markNotificationRead = async (notificationId: number) => {
  return markNotificationReadApiV1NotificationsNotificationIdReadPost(
    notificationId
  ) as unknown as Promise<Notification>;
};

export const markAllNotificationsRead = async () => {
  return markAllNotificationsReadApiV1NotificationsReadAllPost() as unknown as Promise<NotificationCountResponse>;
};
