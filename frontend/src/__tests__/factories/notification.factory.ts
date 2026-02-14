import type { Notification, NotificationType } from "@/types/api";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildNotification(
  overrides: Partial<Notification> = {},
): Notification {
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
