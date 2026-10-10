/**
 * What a calendar's event entry carries for rescheduling, which must name a
 * change's dates as the event's own page does.
 */
import { describe, expect, it } from "vitest";

import { buildCalendarEvent } from "@/__tests__/factories";

import {
  buildEventCalendarEntry,
  type EventEntryMeta,
  occurrenceTarget,
} from "./eventCalendarEntry";

/** The entry's meta for an event as the calendar lists it. */
const metaOf = (overrides: Parameters<typeof buildCalendarEvent>[0]) =>
  buildEventCalendarEntry(
    { ...buildCalendarEvent(overrides), attendee_previews: [] },
    undefined,
    false
  ).meta as EventEntryMeta;

describe("an event's calendar entry", () => {
  it("names the date of a repeating event, so a drag asks which dates it moves", () => {
    const date = metaOf({
      id: 9,
      recurrence: "RRULE:FREQ=WEEKLY",
      original_start: "2026-10-27T15:00:00.000Z",
    });
    const own = metaOf({ id: 42, series_id: 9, original_start: "2026-10-27T15:00:00.000Z" });
    // A series whose rule could not be read is drawn once, and still repeats.
    const unread = metaOf({
      id: 9,
      recurrence: "RRULE:garbled",
      start_at: "2026-10-20T15:00:00.000Z",
    });
    const once = metaOf({ id: 7 });

    expect(date).toMatchObject({ occurrence: "2026-10-27T15:00:00.000Z", seriesId: null });
    expect(own).toMatchObject({ occurrence: "2026-10-27T15:00:00.000Z", seriesId: 9 });
    expect(unread.occurrence).toBe("2026-10-20T15:00:00.000Z");
    expect(once.occurrence).toBeUndefined();
  });

  it("names a series' date with the change, and a date made its own by itself", () => {
    expect(occurrenceTarget({ series_id: null }, "all", "2026-10-27T15:00:00.000Z")).toEqual({
      scope: "all",
      occurrence: "2026-10-27T15:00:00.000Z",
    });
    expect(occurrenceTarget({ series_id: 9 }, "following", "2026-10-27T15:00:00.000Z")).toEqual({
      scope: "following",
    });
  });
});
