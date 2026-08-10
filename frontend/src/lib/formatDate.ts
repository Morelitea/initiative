// A bare calendar date (no time, no zone) — how the API sends DATE columns.
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

// `new Date("2026-08-10")` is UTC midnight, which renders as the previous day
// west of Greenwich. A date-only value names a calendar day, so build it in
// local time and it formats as the day it says.
const toDate = (value: string): Date => {
  const match = DATE_ONLY.exec(value);
  return match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(value);
};

const format = (value: unknown, withTime: boolean): string => {
  if (typeof value !== "string" || !value) return "";
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  }).format(date);
};

/**
 * Parse an API date value into a `Date`, or `null` when it is missing or
 * unparsable. Date-only values resolve to the local calendar day, matching
 * what {@link formatDate} renders.
 */
export const parseDateValue = (value: string | null | undefined): Date | null => {
  if (!value) return null;
  const date = toDate(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

/**
 * Medium browser-locale date (e.g. "Aug 3, 2026"). Returns "" for missing or
 * unparsable input — callers supply their own placeholder
 * (`formatDate(v) || "—"`).
 */
export const formatDate = (value: unknown): string => format(value, false);

/** {@link formatDate} plus a short time (e.g. "Aug 3, 2026, 9:15 PM"). */
export const formatDateTime = (value: unknown): string => format(value, true);
