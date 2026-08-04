const format = (value: unknown, withTime: boolean): string => {
  if (typeof value !== "string" || !value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  }).format(date);
};

/**
 * Medium browser-locale date (e.g. "Aug 3, 2026"). Returns "" for missing or
 * unparsable input — callers supply their own placeholder
 * (`formatDate(v) || "—"`).
 */
export const formatDate = (value: unknown): string => format(value, false);

/** {@link formatDate} plus a short time (e.g. "Aug 3, 2026, 9:15 PM"). */
export const formatDateTime = (value: unknown): string => format(value, true);
