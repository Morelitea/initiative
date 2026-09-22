/**
 * Whether clock times read as "1:30 PM" or "13:30".
 *
 * The formatters that need this are mostly plain functions — `formatDateTime`,
 * a calendar's hour gutter, the clock beside a message — called from deep
 * inside render trees that have no business threading a preference down. So
 * the answer lives here as one module-level value, written once from the
 * signed-in account (see `useTimeFormatSync`) and read wherever a time is
 * rendered.
 *
 * React components that must re-render when it changes subscribe through
 * `useTimeFormat`; everything else just reads it at format time.
 */

import { getItem, setItem } from "@/lib/storage";

export type TimeFormatPreference = "system" | "12" | "24";

export const TIME_FORMAT_PREFERENCES: readonly TimeFormatPreference[] = ["system", "12", "24"];

export const DEFAULT_TIME_FORMAT: TimeFormatPreference = "system";

/** Narrow an API value (or anything else) to a preference we know. */
export const parseTimeFormat = (value: unknown): TimeFormatPreference =>
  TIME_FORMAT_PREFERENCES.includes(value as TimeFormatPreference)
    ? (value as TimeFormatPreference)
    : DEFAULT_TIME_FORMAT;

/**
 * The last answer this browser saw, so the first paint of a returning reader
 * is already on the right clock. The account is the authority and overwrites
 * it as soon as `/users/me` lands; this only covers the gap before that.
 */
const STORAGE_KEY = "initiative.timeFormat";

// `null` until something asks, because this module is imported before
// `initStorage()` has hydrated the cache on native.
let preference: TimeFormatPreference | null = null;
const listeners = new Set<() => void>();

const current = (): TimeFormatPreference => {
  if (preference === null) {
    preference = parseTimeFormat(getItem(STORAGE_KEY));
  }
  return preference;
};

export const getTimeFormat = (): TimeFormatPreference => current();

/**
 * Record the answer without telling anybody. `useTimeFormatSync` calls this
 * while the root renders, so every timestamp below it is formatted on the new
 * clock in that same pass — a formatter that reads this module but does not
 * subscribe to it would otherwise keep the old one until something unrelated
 * re-rendered it.
 */
export const writeTimeFormat = (next: TimeFormatPreference): boolean => {
  if (next === current()) return false;
  preference = next;
  try {
    setItem(STORAGE_KEY, next);
  } catch {
    // A browser that refuses storage still gets the right clock this session.
  }
  return true;
};

/** Tell every subscriber to look again. Safe to call when nothing changed. */
export const notifyTimeFormat = (): void => {
  for (const listener of listeners) listener();
};

export const setTimeFormat = (next: TimeFormatPreference): void => {
  if (writeTimeFormat(next)) notifyTimeFormat();
};

export const subscribeTimeFormat = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** Test helper: forget the account's answer and go back to the default. */
export const resetTimeFormat = (): void => setTimeFormat(DEFAULT_TIME_FORMAT);

/**
 * The `hour12` to hand `Intl.DateTimeFormat`. `undefined` on `system` is the
 * point: it leaves the locale's own convention alone rather than overriding it
 * with a guess at what the locale would have said.
 */
export const hour12Option = (): boolean | undefined => {
  const answer = current();
  return answer === "system" ? undefined : answer === "12";
};

/**
 * The same answer resolved to a definite yes or no, for code that has to pick
 * a pattern rather than pass an option — a date-fns format string, a hand-built
 * "9am" label. On `system` the browser is asked what its locale does.
 */
export const isHour12 = (): boolean => {
  const answer = current();
  if (answer !== "system") return answer === "12";
  return systemPrefersHour12();
};

const systemPrefersHour12 = (): boolean => {
  try {
    const resolved = new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
    }).resolvedOptions();
    // `hour12` is the direct answer where a runtime reports it; `hourCycle`
    // is the one every modern engine gives, and h11/h12 are the 12-hour ones.
    if (typeof resolved.hour12 === "boolean") return resolved.hour12;
    return resolved.hourCycle === "h11" || resolved.hourCycle === "h12";
  } catch {
    return true;
  }
};

/** A date-fns pattern for a time of day: "1:30 PM" or "13:30". */
export const timePattern = (options?: { seconds?: boolean }): string => {
  const minutes = options?.seconds ? "mm:ss" : "mm";
  return isHour12() ? `h:${minutes} a` : `HH:${minutes}`;
};

/** A date-fns pattern for a date and a time of day together. */
export const dateTimePattern = (datePattern: string, options?: { seconds?: boolean }): string =>
  `${datePattern} ${timePattern(options)}`;

/**
 * A wall-clock time as this account reads it. `HH:mm` and `HH:mm:ss` inputs
 * both work, which is what the half-hour slot lists and the `<input
 * type="time">` values around the event dialogs speak.
 */
export const formatClockSlot = (slot: string): string => {
  const [rawHour, rawMinute] = slot.split(":");
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) return slot;
  const paddedMinute = String(minute).padStart(2, "0");
  if (!isHour12()) return `${String(hour).padStart(2, "0")}:${paddedMinute}`;
  return `${hour % 12 || 12}:${paddedMinute} ${hour < 12 ? "AM" : "PM"}`;
};

/**
 * A whole hour as a gutter label — deliberately terse ("9am", "09"), because
 * these sit in the narrow column down the left of a day or week grid.
 */
export const formatHourLabel = (hour: number): string => {
  if (!isHour12()) return String(hour).padStart(2, "0");
  if (hour === 0) return "12am";
  if (hour < 12) return `${hour}am`;
  if (hour === 12) return "12pm";
  return `${hour - 12}pm`;
};

/**
 * A `Date`'s time of day, minutes dropped when they are zero ("9am", "9:30am",
 * "09:00"). The compact form an event block in a calendar cell wears.
 */
export const formatCompactTime = (date: Date): string => {
  const hour = date.getHours();
  const minute = date.getMinutes();
  const paddedMinute = String(minute).padStart(2, "0");
  if (!isHour12()) return `${String(hour).padStart(2, "0")}:${paddedMinute}`;
  const suffix = hour >= 12 ? "pm" : "am";
  const displayHour = hour % 12 || 12;
  return minute === 0 ? `${displayHour}${suffix}` : `${displayHour}:${paddedMinute}${suffix}`;
};
