import { HttpResponse, http } from "msw";

import type {
  Channel,
  NotificationCategoryRead,
  NotificationPreferencesRead,
} from "@/api/generated/initiativeAPI.schemas";

const ALL_ON: Record<Channel, boolean> = { in_app: true, email: true, push: true };
const EVERY_CHANNEL: Channel[] = ["in_app", "email", "push"];
// Being told your account was acted on, or that a queue waits on you, is not
// an opt-in — the bell stays.
const KEEPS_THE_BELL: Channel[] = ["email", "push"];

const category = (
  name: string,
  group: NotificationCategoryRead["group"],
  extras: Partial<NotificationCategoryRead> = {}
): NotificationCategoryRead => ({
  category: name as NotificationCategoryRead["category"],
  group,
  personal: false,
  guild_scoped: true,
  mutable_channels: EVERY_CHANNEL,
  defaults: ALL_ON,
  ...extras,
});

/** The registry as the backend serves it — the settings grid renders from this. */
export const buildNotificationPreferences = (
  overrides: Partial<NotificationPreferencesRead> = {}
): NotificationPreferencesRead => ({
  categories: [
    category("mentions", "addressed_to_me", { personal: true }),
    category("replies", "addressed_to_me", { personal: true }),
    category("assignments", "addressed_to_me", { personal: true }),
    category("events", "addressed_to_me", { personal: true }),
    category("direct_messages", "addressed_to_me", {
      personal: true,
      guild_scoped: false,
    }),
    category("comments", "activity"),
    category("reactions", "activity"),
    category("due_dates", "activity"),
    category("event_reminders", "activity"),
    category("membership", "community"),
    category("approvals", "community", {
      personal: true,
      mutable_channels: KEEPS_THE_BELL,
    }),
    category("posts", "community"),
    category("jobs", "account", { personal: true }),
    category("account", "account", {
      personal: true,
      guild_scoped: false,
      mutable_channels: KEEPS_THE_BELL,
    }),
  ],
  settings: {},
  quiet_hours: null,
  guilds: [],
  ...overrides,
});

export const notificationHandlers = [
  http.get("/api/v1/me/notification-preferences", () =>
    HttpResponse.json(buildNotificationPreferences())
  ),
  http.put("/api/v1/me/notification-preferences", () =>
    HttpResponse.json(buildNotificationPreferences())
  ),
  http.get("/api/v1/notifications/unread", () => HttpResponse.json({ places: [] })),
  http.get("/api/v1/notifications/", () =>
    HttpResponse.json({ notifications: [], unread_count: 0, next_cursor: null })
  ),
];
