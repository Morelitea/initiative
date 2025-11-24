import type {
  TaskRecurrence,
  TaskRecurrenceFrequency,
  TaskWeekPosition,
  TaskWeekday,
} from "../types/api";

export type RecurrencePreset = "none" | "daily" | "weekly" | "weekdays" | "monthly" | "yearly" | "custom";

type WeekdayConfig = {
  value: TaskWeekday;
  label: string;
  short: string;
  dateIndex: number;
};

export const WEEKDAYS: WeekdayConfig[] = [
  { value: "monday", label: "Monday", short: "Mon", dateIndex: 1 },
  { value: "tuesday", label: "Tuesday", short: "Tue", dateIndex: 2 },
  { value: "wednesday", label: "Wednesday", short: "Wed", dateIndex: 3 },
  { value: "thursday", label: "Thursday", short: "Thu", dateIndex: 4 },
  { value: "friday", label: "Friday", short: "Fri", dateIndex: 5 },
  { value: "saturday", label: "Saturday", short: "Sat", dateIndex: 6 },
  { value: "sunday", label: "Sunday", short: "Sun", dateIndex: 0 },
];

const WEEKDAY_ORDER: Record<TaskWeekday, number> = WEEKDAYS.reduce(
  (acc, item, index) => ({ ...acc, [item.value]: index }),
  {} as Record<TaskWeekday, number>,
);

const POSITION_LABELS: Record<TaskWeekPosition, string> = {
  first: "first",
  second: "second",
  third: "third",
  fourth: "fourth",
  last: "last",
};

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const FREQUENCY_LABELS: Record<TaskRecurrenceFrequency, { singular: string; plural: string }> = {
  daily: { singular: "day", plural: "days" },
  weekly: { singular: "week", plural: "weeks" },
  monthly: { singular: "month", plural: "months" },
  yearly: { singular: "year", plural: "years" },
};

const clampInterval = (value: number) => Math.max(1, Math.min(365, Math.floor(value)));

const getReferenceDate = (value?: string | null): Date => {
  if (!value) {
    return new Date();
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return new Date();
  }
  return parsed;
};

const getWeekdayFromDate = (date: Date): TaskWeekday => {
  const day = date.getDay(); // 0 (Sun) - 6 (Sat)
  const match = WEEKDAYS.find((weekday) => weekday.dateIndex === day);
  return match ? match.value : "monday";
};

const getWeekPosition = (date: Date): TaskWeekPosition => {
  const day = date.getDate();
  const daysInMonth = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
  if (day + 7 > daysInMonth) {
    return "last";
  }
  const index = Math.ceil(day / 7);
  return (["first", "second", "third", "fourth"][index - 1] ?? "last") as TaskWeekPosition;
};

const sortWeekdays = (weekdays: TaskWeekday[]) =>
  [...new Set(weekdays)].sort((a, b) => WEEKDAY_ORDER[a] - WEEKDAY_ORDER[b]);

const baseRule = (): TaskRecurrence => ({
  frequency: "daily",
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
});

export const createRecurrenceFromPreset = (
  preset: RecurrencePreset,
  referenceDate?: string | null,
): TaskRecurrence | null => {
  const anchor = getReferenceDate(referenceDate);
  switch (preset) {
    case "none":
      return null;
    case "daily":
      return baseRule();
    case "weekly":
      return {
        ...baseRule(),
        frequency: "weekly",
        weekdays: [getWeekdayFromDate(anchor)],
      };
    case "weekdays":
      return {
        ...baseRule(),
        frequency: "weekly",
        weekdays: ["monday", "tuesday", "wednesday", "thursday", "friday"],
      };
    case "monthly":
      return {
        ...baseRule(),
        frequency: "monthly",
        monthly_mode: "day_of_month",
        day_of_month: anchor.getDate(),
      };
    case "yearly":
      return {
        ...baseRule(),
        frequency: "yearly",
        monthly_mode: "day_of_month",
        day_of_month: anchor.getDate(),
        month: anchor.getMonth() + 1,
      };
    case "custom":
      return baseRule();
    default:
      return null;
  }
};

export const detectRecurrencePreset = (rule: TaskRecurrence | null): RecurrencePreset => {
  if (!rule) {
    return "none";
  }
  if (rule.frequency === "daily" && rule.interval === 1 && rule.ends === "never") {
    return "daily";
  }
  if (rule.frequency === "weekly" && rule.interval === 1) {
    const weekdays = sortWeekdays(rule.weekdays);
    const weekdayPreset = ["monday", "tuesday", "wednesday", "thursday", "friday"];
    if (weekdays.length === weekdayPreset.length && weekdays.every((day, index) => day === weekdayPreset[index])) {
      return "weekdays";
    }
    if (weekdays.length === 1) {
      return "weekly";
    }
  }
  if (
    rule.frequency === "monthly" &&
    rule.interval === 1 &&
    rule.monthly_mode === "day_of_month" &&
    typeof rule.day_of_month === "number" &&
    rule.ends === "never"
  ) {
    return "monthly";
  }
  if (
    rule.frequency === "yearly" &&
    rule.interval === 1 &&
    rule.monthly_mode === "day_of_month" &&
    typeof rule.day_of_month === "number" &&
    typeof rule.month === "number" &&
    rule.ends === "never"
  ) {
    return "yearly";
  }
  return "custom";
};

const formatWeekdayList = (weekdays: TaskWeekday[]) => {
  if (!weekdays.length) {
    return "";
  }
  const labels = sortWeekdays(weekdays).map((day) => WEEKDAYS.find((config) => config.value === day)?.label ?? day);
  if (labels.length === 1) {
    return labels[0] ?? "";
  }
  if (labels.length === 2) {
    return `${labels[0]} and ${labels[1]}`;
  }
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
};

const formatEnding = (rule: TaskRecurrence) => {
  if (rule.ends === "on_date" && rule.end_date) {
    const date = new Date(rule.end_date);
    if (!Number.isNaN(date.getTime())) {
      return `until ${date.toLocaleDateString()}`;
    }
  }
  if (rule.ends === "after_occurrences" && typeof rule.end_after_occurrences === "number") {
    return `for ${rule.end_after_occurrences} occurrences`;
  }
  return "";
};

const describeMonthlyDetail = (rule: TaskRecurrence) => {
  if (rule.monthly_mode === "day_of_month" && typeof rule.day_of_month === "number") {
    return `on day ${rule.day_of_month}`;
  }
  if (rule.weekday_position && rule.weekday) {
    const weekdayLabel = WEEKDAYS.find((item) => item.value === rule.weekday)?.label ?? rule.weekday;
    return `on the ${POSITION_LABELS[rule.weekday_position]} ${weekdayLabel}`;
  }
  return "";
};

export const summarizeRecurrence = (
  rule: TaskRecurrence | null,
  options?: { referenceDate?: string | null },
): string => {
  if (!rule) {
    return "Does not repeat";
  }

  const frequencyLabel = FREQUENCY_LABELS[rule.frequency];
  const everyLabel =
    rule.interval === 1
      ? `every ${frequencyLabel.singular}`
      : `every ${rule.interval} ${frequencyLabel.plural}`;

  let detail = "";
  switch (rule.frequency) {
    case "weekly":
      detail = rule.weekdays.length ? `on ${formatWeekdayList(rule.weekdays)}` : "";
      break;
    case "monthly":
      detail = describeMonthlyDetail(rule);
      break;
    case "yearly": {
      const monthName =
        typeof rule.month === "number"
          ? MONTH_NAMES[Math.max(1, Math.min(12, rule.month)) - 1]
          : options?.referenceDate
            ? MONTH_NAMES[getReferenceDate(options.referenceDate).getMonth()]
            : "";
      const monthlyDetail = describeMonthlyDetail(rule);
      if (monthName && monthlyDetail) {
        detail = `${monthlyDetail} of ${monthName}`;
      } else if (monthName) {
        detail = `in ${monthName}`;
      } else {
        detail = monthlyDetail;
      }
      break;
    }
    default:
      detail = "";
  }

  const parts = [`Repeats ${everyLabel}`];
  if (detail) {
    parts.push(detail);
  }
  const ending = formatEnding(rule);
  if (ending) {
    parts.push(ending);
  }

  return parts.join(" ");
};

export const withInterval = (rule: TaskRecurrence, interval: number): TaskRecurrence => ({
  ...rule,
  interval: clampInterval(interval),
});

export const withEndDate = (rule: TaskRecurrence, endDate?: string | null): TaskRecurrence => ({
  ...rule,
  ends: endDate ? "on_date" : "never",
  end_date: endDate ?? null,
  end_after_occurrences: null,
});

export const withOccurrenceCount = (rule: TaskRecurrence, count?: number): TaskRecurrence => ({
  ...rule,
  ends: typeof count === "number" ? "after_occurrences" : "never",
  end_after_occurrences: typeof count === "number" ? Math.max(1, Math.min(1000, Math.floor(count))) : null,
  end_date: null,
});

export const updateWeeklyWeekdays = (rule: TaskRecurrence, weekdays: TaskWeekday[]): TaskRecurrence => ({
  ...rule,
  weekdays: sortWeekdays(weekdays),
});

export const updateMonthlyDay = (rule: TaskRecurrence, dayOfMonth: number): TaskRecurrence => ({
  ...rule,
  monthly_mode: "day_of_month",
  day_of_month: Math.max(1, Math.min(31, Math.floor(dayOfMonth))),
  weekday: null,
  weekday_position: null,
});

export const updateMonthlyWeekday = (
  rule: TaskRecurrence,
  position: TaskWeekPosition,
  weekday: TaskWeekday,
): TaskRecurrence => ({
  ...rule,
  monthly_mode: "weekday",
  day_of_month: null,
  weekday_position: position,
  weekday,
});

export const updateYearlyMonth = (rule: TaskRecurrence, month: number): TaskRecurrence => ({
  ...rule,
  month: Math.max(1, Math.min(12, Math.floor(month))),
});

export const ensureYearlyDefaults = (rule: TaskRecurrence, referenceDate?: string | null): TaskRecurrence => {
  const anchor = getReferenceDate(referenceDate);
  return {
    ...rule,
    month: rule.month ?? anchor.getMonth() + 1,
    monthly_mode: rule.monthly_mode ?? "day_of_month",
    day_of_month: rule.monthly_mode === "day_of_month" ? rule.day_of_month ?? anchor.getDate() : null,
    weekday: rule.monthly_mode === "weekday" ? rule.weekday ?? getWeekdayFromDate(anchor) : null,
    weekday_position: rule.monthly_mode === "weekday" ? rule.weekday_position ?? getWeekPosition(anchor) : null,
  };
};

export const ensureMonthlyDefaults = (rule: TaskRecurrence, referenceDate?: string | null): TaskRecurrence => {
  const anchor = getReferenceDate(referenceDate);
  if (rule.monthly_mode === "weekday") {
    return {
      ...rule,
      weekday: rule.weekday ?? getWeekdayFromDate(anchor),
      weekday_position: rule.weekday_position ?? getWeekPosition(anchor),
      day_of_month: null,
    };
  }
  return {
    ...rule,
    monthly_mode: "day_of_month",
    day_of_month: rule.day_of_month ?? anchor.getDate(),
    weekday: null,
    weekday_position: null,
  };
};
