import { describe, expect, it } from "vitest";

import { calendarVisibleRange } from "./visibleRange";

// Local-time construction throughout: the range feeds a query window that the
// user reads in their own timezone.
const FOCUS = new Date(2026, 1, 11, 13, 30); // Wed 11 Feb 2026, mid-afternoon

const iso = (d: Date) => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;

describe("calendarVisibleRange", () => {
  it("day view covers the focus day only", () => {
    const { start, end } = calendarVisibleRange(FOCUS, "day");
    expect(iso(start)).toBe("2026-2-11");
    expect(iso(end)).toBe("2026-2-11");
    expect(start.getHours()).toBe(0);
    expect(end.getHours()).toBe(23);
  });

  it("week view covers the surrounding week", () => {
    const { start, end } = calendarVisibleRange(FOCUS, "week");
    expect(iso(start)).toBe("2026-2-8"); // Sunday
    expect(iso(end)).toBe("2026-2-14"); // Saturday
  });

  it("week view honors weekStartsOn", () => {
    const { start, end } = calendarVisibleRange(FOCUS, "week", 1);
    expect(iso(start)).toBe("2026-2-9"); // Monday
    expect(iso(end)).toBe("2026-2-15"); // Sunday
  });

  it("month view covers whole weeks only, when the month aligns to them", () => {
    // Feb 2026 happens to run Sun 1 → Sat 28: a grid with no padding at all.
    const { start, end } = calendarVisibleRange(FOCUS, "month");
    expect(iso(start)).toBe("2026-2-1");
    expect(iso(end)).toBe("2026-2-28");
  });

  it("month view pads to whole weeks, so adjacent-month days are covered", () => {
    // Jan 2026 runs Thu 1 → Sat 31, so its grid opens on Sun 28 Dec 2025 and
    // closes on Sat 31 Jan. Those December days are on screen and their tasks
    // have to be fetched.
    const { start, end } = calendarVisibleRange(new Date(2026, 0, 15), "month");
    expect(iso(start)).toBe("2025-12-28");
    expect(iso(end)).toBe("2026-1-31");
  });

  it("year view covers the focus year", () => {
    const { start, end } = calendarVisibleRange(FOCUS, "year");
    expect(iso(start)).toBe("2026-1-1");
    expect(iso(end)).toBe("2026-12-31");
  });

  it("list view covers the focus month exactly, without week padding", () => {
    const { start, end } = calendarVisibleRange(FOCUS, "list");
    expect(iso(start)).toBe("2026-2-1");
    expect(iso(end)).toBe("2026-2-28");
  });

  it("end is inclusive of the final day", () => {
    const { end } = calendarVisibleRange(FOCUS, "month");
    expect(end.getHours()).toBe(23);
    expect(end.getMinutes()).toBe(59);
  });
});
