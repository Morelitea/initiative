// Shared date/time helpers for the event create dialog and edit page so both
// use the identical pickers, half-hour slots, and duration-preserving logic.

export const DEFAULT_DURATION_MINUTES = 60;
const DAY_END_MINUTES = 23 * 60 + 30; // last selectable slot (23:30)

// Half-hour time slots: { value: "HH:MM", label: "h:MM AM/PM" }.
export const TIME_OPTIONS = Array.from({ length: 48 }, (_, i) => {
  const hour = Math.floor(i / 2);
  const minute = i % 2 === 0 ? "00" : "30";
  const hh = String(hour).padStart(2, "0");
  const label = `${hour === 0 ? 12 : hour > 12 ? hour - 12 : hour}:${minute} ${hour < 12 ? "AM" : "PM"}`;
  return { value: `${hh}:${minute}`, label };
});

export const toMinutes = (slot: string): number => {
  const [h, m] = slot.split(":").map(Number);
  return h * 60 + m;
};

export const toSlot = (minutes: number): string => {
  const clamped = Math.max(0, Math.min(minutes, DAY_END_MINUTES));
  return `${String(Math.floor(clamped / 60)).padStart(2, "0")}:${String(clamped % 60).padStart(2, "0")}`;
};

// Slot one hour after `start`, used to seed the end time on first open.
export const offsetEndTime = (start: string): string =>
  toSlot(toMinutes(start) + DEFAULT_DURATION_MINUTES);

// Parse a "yyyy-MM-dd" string as a local date to avoid the UTC-midnight shift
// that `new Date("yyyy-MM-dd")` introduces in negative-offset timezones.
export const parseLocalDate = (value: string): Date | undefined => {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : undefined;
};

// Combine a "yyyy-MM-dd" date and "HH:MM" slot into a local Date (null if no date).
export const composeDateTime = (date: string, time: string): Date | null => {
  if (!date) return null;
  const d = new Date(`${date}T${time || "00:00"}:00`);
  return Number.isNaN(d.getTime()) ? null : d;
};

export const toDateKey = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const toTimeSlot = (d: Date): string =>
  `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

// Local "HH:MM" snapped to the nearest half-hour slot, so a Select bound to
// TIME_OPTIONS can display the time of an existing (possibly off-grid) event.
export const toTimeSlotRounded = (d: Date): string =>
  toSlot(Math.round((d.getHours() * 60 + d.getMinutes()) / 30) * 30);

/**
 * Given the current start/end (each a date + time slot) and a new start,
 * return the end that keeps the event's current length. A 90-minute event
 * stays 90 minutes; a multi-day event keeps its span (the end may land on a
 * later day). Returns null when the next start can't be parsed.
 */
export const shiftEndPreservingDuration = (
  prevStartDate: string,
  prevStartTime: string,
  prevEndDate: string,
  prevEndTime: string,
  nextDate: string,
  nextTime: string
): { endDate: string; endTime: string } | null => {
  const nextStart = composeDateTime(nextDate, nextTime);
  if (!nextStart) return null;
  const prevStart = composeDateTime(prevStartDate, prevStartTime);
  const prevEnd = composeDateTime(prevEndDate || prevStartDate, prevEndTime);
  const durationMs = prevStart && prevEnd ? prevEnd.getTime() - prevStart.getTime() : 0;
  const keepMs = durationMs > 0 ? durationMs : DEFAULT_DURATION_MINUTES * 60_000;
  const nextEnd = new Date(nextStart.getTime() + keepMs);
  return { endDate: toDateKey(nextEnd), endTime: toTimeSlot(nextEnd) };
};

// When the end date moves onto the start day and the current end time is no
// longer after the start, snap it forward so the end-time Select never shows a
// value that its filtered options exclude. Across days (or when still valid)
// the end time is left untouched.
export const reconcileEndTime = (
  startDate: string,
  startTime: string,
  nextEndDate: string,
  endTime: string
): string => {
  if (nextEndDate === startDate && toMinutes(endTime) <= toMinutes(startTime)) {
    return offsetEndTime(startTime);
  }
  return endTime;
};

// End-time slots offered for the given range. On the same day the end must be
// after the start, so earlier slots are hidden; across days every time is valid.
export const endTimeOptionsFor = (startDate: string, endDate: string, startTime: string) => {
  if (startDate && endDate && endDate !== startDate) return TIME_OPTIONS;
  const startMinutes = toMinutes(startTime);
  return TIME_OPTIONS.filter((opt) => toMinutes(opt.value) > startMinutes);
};

// Whether the start/end pair is a valid (non-negative-length) range.
export const datesAreValid = (
  allDay: boolean,
  startDate: string,
  startTime: string,
  endDate: string,
  endTime: string
): boolean => {
  if (!startDate) return false;
  if (allDay) {
    const s = parseLocalDate(startDate);
    const e = parseLocalDate(endDate || startDate);
    return !!s && !!e && e >= s;
  }
  const s = composeDateTime(startDate, startTime);
  const e = composeDateTime(endDate || startDate, endTime);
  return !!s && !!e && e > s;
};
