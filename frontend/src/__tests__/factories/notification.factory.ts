import type {
  NotificationPlace,
  NotificationRead,
  NotificationType,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildNotification(overrides: Partial<NotificationRead> = {}): NotificationRead {
  counter++;
  return {
    id: counter,
    type: "task_assignment" as NotificationType,
    data: {},
    created_at: "2026-01-15T00:00:00.000Z",
    read_at: null,
    guild_id: null,
    initiative_id: null,
    tool: null,
    ...overrides,
  };
}

/** One place `GET /notifications/unread` reports, in the default test guild. */
export function buildNotificationPlace(
  overrides: Partial<NotificationPlace> = {}
): NotificationPlace {
  return {
    guild_id: 1,
    initiative_id: null,
    tool: null,
    resource_id: null,
    subject_type: null,
    subject_id: null,
    ...overrides,
  };
}
