import type { CalendarEventSummary } from "@/api/generated/initiativeAPI.schemas";
import { hasWriteAccess } from "@/lib/permissions";

import type { CalendarEntry } from "./CalendarView";

/** A calendar's color when none is set — the server's own default. */
export const DEFAULT_CALENDAR_COLOR = "#6366f1";

/**
 * The calendar entry for one event, drawn in its calendar's color.
 *
 * The id carries the guild because the cross-guild calendar holds events whose
 * per-guild ids collide; `meta` carries everything either calendar navigates by.
 */
export const buildEventCalendarEntry = (
  event: CalendarEventSummary,
  calendarColor: string | undefined,
  unread: boolean
): CalendarEntry => ({
  id: `event-${event.guild_id}-${event.id}`,
  title: event.title,
  description: event.description,
  startAt: event.start_at,
  endAt: event.end_at,
  allDay: event.all_day,
  color: calendarColor ?? DEFAULT_CALENDAR_COLOR,
  attendees: (event.attendee_previews ?? []).map((att) => ({
    name: att.name,
    avatarUrl: att.avatar_url,
    userId: att.user_id,
  })),
  properties: event.property_values,
  tags: event.tags,
  draggable: hasWriteAccess(event.my_permission_level),
  unread,
  meta: {
    type: "event",
    eventId: event.id,
    calendarId: event.calendar_id,
    guildId: event.guild_id,
  },
});
