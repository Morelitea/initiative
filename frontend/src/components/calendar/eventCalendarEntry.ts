import type { CalendarEventSummary } from "@/api/generated/initiativeAPI.schemas";

import type { CalendarEntry } from "./CalendarView";

/** The UTC date of an instant, as `YYYY-MM-DD`: an all-day event's day. */
export const utcDateKey = (iso: string) => new Date(iso).toISOString().slice(0, 10);

/** The stored range for an all-day event dropped onto local days: those days as UTC dates. */
export const allDayRange = (startAt: string, endAt: string) => {
  const day = (iso: string) => {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  return { start_at: `${day(startAt)}T00:00:00Z`, end_at: `${day(endAt)}T23:59:59Z` };
};

/** A calendar's color when none is set — the server's own default. */
export const DEFAULT_CALENDAR_COLOR = "#6366f1";

/**
 * The calendar entry for one event, drawn in its calendar's color.
 *
 * The id carries the community because the cross-community calendar holds events whose
 * per-community ids collide, and a repeating event's occurrence because the series
 * is there once for each; `meta` carries everything either calendar navigates
 * or reschedules by: an occurrence names its start in the series, and one with
 * a row of its own names the series too.
 */
export const buildEventCalendarEntry = (
  event: CalendarEventSummary,
  calendarColor: string | undefined,
  unread: boolean
): CalendarEntry => ({
  id: `event-${event.community_id}-${event.id}${event.original_start ? `@${event.original_start}` : ""}`,
  title: event.title,
  description: event.description,
  // An all-day event's dates are UTC dates; drawn as the same dates here.
  startAt: event.all_day ? `${utcDateKey(event.start_at)}T00:00:00` : event.start_at,
  endAt: event.all_day ? `${utcDateKey(event.end_at)}T23:59:59` : event.end_at,
  allDay: event.all_day,
  color: calendarColor ?? DEFAULT_CALENDAR_COLOR,
  attendees: (event.attendee_previews ?? []).map((att) => ({
    name: att.name,
    avatarUrl: att.avatar_url,
    userId: att.user_id,
  })),
  properties: event.properties,
  tags: event.tags,
  draggable: event.can.edit,
  unread,
  meta: {
    type: "event",
    eventId: event.id,
    calendarId: event.calendar_id,
    communityId: event.community_id,
    occurrence: event.original_start ?? undefined,
    seriesId: event.series_id ?? undefined,
  },
});
