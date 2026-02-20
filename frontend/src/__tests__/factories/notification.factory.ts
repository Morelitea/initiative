import type { NotificationRead, NotificationType } from "@/api/generated/initiativeAPI.schemas";

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
    ...overrides,
  };
}
