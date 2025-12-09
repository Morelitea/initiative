const DAY_IN_MS = 24 * 60 * 60 * 1000;

type TaskDateStatusKey = "0_overdue" | "1_today" | "2_this_week" | "3_this_month" | "4_later";

const TASK_DATE_STATUS_LABELS: Record<TaskDateStatusKey, string> = {
  "0_overdue": "Overdue",
  "1_today": "Today",
  "2_this_week": "This Week",
  "3_this_month": "This Month",
  "4_later": "Later",
};

const parseDate = (value?: string | null) => {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const isBefore = (date: Date, compareTo: Date) => date.getTime() < compareTo.getTime();
const isOnOrBefore = (date: Date, compareTo: Date) => date.getTime() <= compareTo.getTime();

const createFutureDate = (base: Date, days: number) => new Date(base.getTime() + days * DAY_IN_MS);

const isSameCalendarDate = (date1: Date, date2: Date) => {
  return (
    date1.getFullYear() === date2.getFullYear() &&
    date1.getMonth() === date2.getMonth() &&
    date1.getDate() === date2.getDate()
  );
};

const getCalendarDate = (date: Date) => {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
};

export const getTaskDateStatus = (
  startDate?: string | null,
  dueDate?: string | null,
  referenceDate: Date = new Date()
): TaskDateStatusKey => {
  const start = parseDate(startDate);
  const due = parseDate(dueDate);
  const now = referenceDate;
  const todayCalendar = getCalendarDate(now);

  if (due && isBefore(due, now)) {
    return "0_overdue";
  }

  // Return "today" if:
  // - Start date has passed (before today's calendar date), OR
  // - Start or due date is on the same calendar date as today
  if (start) {
    const startCalendar = getCalendarDate(start);
    if (startCalendar < todayCalendar || isSameCalendarDate(start, now)) {
      return "1_today";
    }
  }
  if (due && isSameCalendarDate(due, now)) {
    return "1_today";
  }

  const thisWeek = createFutureDate(now, 7);
  if ((start && isOnOrBefore(start, thisWeek)) || (due && isOnOrBefore(due, thisWeek))) {
    return "2_this_week";
  }

  const thisMonth = createFutureDate(now, 30);
  if ((start && isOnOrBefore(start, thisMonth)) || (due && isOnOrBefore(due, thisMonth))) {
    return "3_this_month";
  }

  return "4_later";
};

export const getTaskDateStatusLabel = (value?: string | null) => {
  if (!value) {
    return TASK_DATE_STATUS_LABELS["4_later"];
  }
  const key = value as TaskDateStatusKey;
  if (TASK_DATE_STATUS_LABELS[key]) {
    return TASK_DATE_STATUS_LABELS[key];
  }
  const sanitized = value.replace(/^\d+_/, "").replace(/_/g, " ");
  if (!sanitized) {
    return TASK_DATE_STATUS_LABELS["4_later"];
  }
  return sanitized
    .split(" ")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};
