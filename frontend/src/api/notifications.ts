import { apiClient } from "./client";
import type {
  Notification,
  NotificationCountResponse,
  NotificationListResponse,
} from "@/types/api";

export const fetchNotifications = async () => {
  const response = await apiClient.get<NotificationListResponse>("/notifications/");
  return response.data;
};

export const fetchUnreadNotificationCount = async () => {
  const response = await apiClient.get<NotificationCountResponse>("/notifications/unread-count");
  return response.data;
};

export const markNotificationRead = async (notificationId: number) => {
  const response = await apiClient.post<Notification>(`/notifications/${notificationId}/read`);
  return response.data;
};

export const markAllNotificationsRead = async () => {
  const response = await apiClient.post<NotificationCountResponse>("/notifications/read-all");
  return response.data;
};
