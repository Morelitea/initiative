/**
 * A repeat goes out as the RRULE its days were picked in, and comes back from
 * the server in UTC terms: read in the viewer's zone, it is the rule the form
 * built. Berlin, so a Monday 00:30 start is a Sunday in UTC.
 */
process.env.TZ = "Europe/Berlin";

import { describe, expect, it } from "vitest";

import { fromStored, type RecurrenceRule, summarizeStored, toRRule } from "@/lib/recurrence";

const rule = (overrides: Partial<RecurrenceRule>): RecurrenceRule => ({
  frequency: "weekly",
  interval: 1,
  weekdays: [],
  monthly_mode: "day_of_month",
  day_of_month: null,
  month: null,
  weekday_position: null,
  weekday: null,
  ends: "never",
  end_after_occurrences: null,
  end_date: null,
  ...overrides,
});

// Monday 5 October 2026, 00:30 in Berlin.
const START = "2026-10-04T22:30:00Z";

describe("toRRule", () => {
  it("writes the picked days, and the end of the picked day in UTC", () => {
    expect(toRRule(rule({ weekdays: ["wednesday", "monday"] }))).toBe(
      "RRULE:FREQ=WEEKLY;BYDAY=MO,WE"
    );
    expect(
      toRRule(
        rule({
          frequency: "monthly",
          monthly_mode: "weekday",
          weekday_position: "second",
          weekday: "monday",
          ends: "on_date",
          end_date: "2026-12-14",
        })
      )
    ).toBe("RRULE:FREQ=MONTHLY;BYDAY=2MO;UNTIL=20261214T225959Z");
    // The 31st falls on a short month's last day, as it always has.
    expect(toRRule(rule({ frequency: "monthly", day_of_month: 31 }))).toBe(
      "RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
    );
    expect(
      toRRule(rule({ frequency: "daily", ends: "on_date", end_date: "2026-12-14" }), {
        allDay: true,
      })
    ).toBe("RRULE:FREQ=DAILY;UNTIL=20261214");
  });
});

describe("fromStored", () => {
  it("reads a rule stored in UTC terms back as it was picked", () => {
    expect(fromStored("RRULE:FREQ=WEEKLY;BYDAY=SU,TU", START)).toMatchObject({
      frequency: "weekly",
      weekdays: ["monday", "wednesday"],
    });
    expect(
      fromStored(
        "RRULE:FREQ=MONTHLY;UNTIL=20261214T225959Z;BYDAY=SU;BYMONTHDAY=7,8,9,10,11,12,13",
        START
      )
    ).toMatchObject({
      monthly_mode: "weekday",
      weekday_position: "second",
      weekday: "monday",
      ends: "on_date",
      end_date: "2026-12-14",
    });
    expect(fromStored("RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1", null)).toMatchObject(
      { day_of_month: 31 }
    );
    expect(fromStored(null, START)).toBeNull();
  });

  it("keeps a rule the form can't show as custom", () => {
    expect(fromStored("RRULE:FREQ=HOURLY;BYHOUR=9,17", START)).toBe("custom");
    expect(fromStored("RRULE:FREQ=WEEKLY\nEXDATE:20261012T223000Z", START)).toBe("custom");
    const t = ((key: string) => key) as Parameters<typeof summarizeStored>[3];
    expect(summarizeStored("RRULE:FREQ=HOURLY", START, undefined, t)).toBe(
      "dates:recurrenceSummary.custom"
    );
  });
});
