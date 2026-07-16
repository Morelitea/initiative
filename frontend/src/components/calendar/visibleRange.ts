import {
  endOfDay,
  endOfMonth,
  endOfWeek,
  endOfYear,
  startOfDay,
  startOfMonth,
  startOfWeek,
  startOfYear,
} from "date-fns";

import type { CalendarViewMode } from "./CalendarView";

export interface CalendarVisibleRange {
  start: Date;
  end: Date;
}

/**
 * The span of dates a calendar view actually renders for a given focus date.
 *
 * Mirrors what each view builds internally: the month grid pads out to whole
 * weeks (so late-January days show in the February grid), the list view shows
 * the focus month exactly, and week/day track the focus date. Callers use this
 * to fetch only the entries a view can display — keep it in step with
 * ``CalendarView`` if a view's span ever changes, or entries will be fetched
 * that the grid never shows (or worse, shown days will come up empty).
 */
export function calendarVisibleRange(
  focusDate: Date,
  viewMode: CalendarViewMode,
  weekStartsOn: 0 | 1 | 2 | 3 | 4 | 5 | 6 = 0
): CalendarVisibleRange {
  switch (viewMode) {
    case "day":
      return { start: startOfDay(focusDate), end: endOfDay(focusDate) };
    case "week":
      return {
        start: startOfWeek(focusDate, { weekStartsOn }),
        end: endOfWeek(focusDate, { weekStartsOn }),
      };
    case "month":
      return {
        start: startOfWeek(startOfMonth(focusDate), { weekStartsOn }),
        end: endOfWeek(endOfMonth(focusDate), { weekStartsOn }),
      };
    case "year":
      return { start: startOfYear(focusDate), end: endOfYear(focusDate) };
    case "list":
      return { start: startOfMonth(focusDate), end: endOfMonth(focusDate) };
  }
}
