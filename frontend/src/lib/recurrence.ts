import type {
  TaskListReadRecurrenceStrategy,
  TaskRecurrenceOutput,
  TaskRecurrenceOutputFrequency,
  TaskRecurrenceOutputWeekdaysItem,
} from "@/api/generated/initiativeAPI.schemas";
import type { TaskWeekPosition } from "@/types/api";
import type { TranslateFn } from "@/types/i18n";

export type RecurrencePreset =
  | "none"
  | "daily"
  | "weekly"
  | "weekdays"
  | "monthly"
  | "yearly"
  | "custom";

type WeekdayConfig = {
  value: TaskRecurrenceOutputWeekdaysItem;
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

const WEEKDAY_ORDER: Record<TaskRecurrenceOutputWeekdaysItem, number> = WEEKDAYS.reduce(
  (acc, item, index) => ({ ...acc, [item.value]: index }),
  {} as Record<TaskRecurrenceOutputWeekdaysItem, number>
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

const FREQUENCY_LABELS: Record<
  TaskRecurrenceOutputFrequency,
  { singular: string; plural: string }
> = {
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

const getWeekdayFromDate = (date: Date): TaskRecurrenceOutputWeekdaysItem => {
  // Normalize to midnight local time to get the date's weekday regardless of time
  const normalized = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = normalized.getDay(); // 0 (Sun) - 6 (Sat)
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

const sortWeekdays = (weekdays: TaskRecurrenceOutputWeekdaysItem[]) =>
  [...new Set(weekdays)].sort((a, b) => WEEKDAY_ORDER[a] - WEEKDAY_ORDER[b]);

const baseRule = (): TaskRecurrenceOutput => ({
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
  referenceDate?: string | null
): TaskRecurrenceOutput | null => {
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

export const detectRecurrencePreset = (rule: TaskRecurrenceOutput | null): RecurrencePreset => {
  if (!rule) {
    return "none";
  }
  if (rule.frequency === "daily" && rule.interval === 1 && rule.ends === "never") {
    return "daily";
  }
  if (rule.frequency === "weekly" && rule.interval === 1) {
    const weekdays = sortWeekdays(rule.weekdays);
    const weekdayPreset = ["monday", "tuesday", "wednesday", "thursday", "friday"];
    if (
      weekdays.length === weekdayPreset.length &&
      weekdays.every((day, index) => day === weekdayPreset[index])
    ) {
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

const formatWeekdayList = (weekdays: TaskRecurrenceOutputWeekdaysItem[], t?: TranslateFn) => {
  if (!weekdays.length) {
    return "";
  }
  const labels = sortWeekdays(weekdays).map((day) =>
    t ? t(`dates:weekdays.${day}`) : (WEEKDAYS.find((config) => config.value === day)?.label ?? day)
  );
  if (labels.length === 1) {
    return labels[0] ?? "";
  }
  try {
    return new Intl.ListFormat(undefined, { style: "long", type: "conjunction" }).format(labels);
  } catch {
    if (labels.length === 2) {
      return `${labels[0]} and ${labels[1]}`;
    }
    return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
  }
};

const formatEnding = (rule: TaskRecurrenceOutput, t?: TranslateFn) => {
  if (rule.ends === "on_date" && rule.end_date) {
    // Parse date-only string as local date to avoid timezone issues
    const match = rule.end_date.match(/^(\d{4})-(\d{2})-(\d{2})/);
    const date = match
      ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
      : new Date(rule.end_date);
    if (!Number.isNaN(date.getTime())) {
      const formatted = date.toLocaleDateString();
      return t ? t("dates:recurrenceSummary.untilDate", { date: formatted }) : `until ${formatted}`;
    }
  }
  if (rule.ends === "after_occurrences" && typeof rule.end_after_occurrences === "number") {
    return t
      ? t("dates:recurrenceSummary.forOccurrences", { count: rule.end_after_occurrences })
      : `for ${rule.end_after_occurrences} occurrences`;
  }
  return "";
};

const describeMonthlyDetail = (rule: TaskRecurrenceOutput, t?: TranslateFn) => {
  if (rule.monthly_mode === "day_of_month" && typeof rule.day_of_month === "number") {
    return t
      ? t("dates:recurrenceSummary.onDay", { day: rule.day_of_month })
      : `on day ${rule.day_of_month}`;
  }
  if (rule.weekday_position && rule.weekday) {
    const weekdayLabel = t
      ? t(`dates:weekdays.${rule.weekday}`)
      : (WEEKDAYS.find((item) => item.value === rule.weekday)?.label ?? rule.weekday);
    const posLabel = t
      ? t(`dates:positions.${rule.weekday_position}`)
      : POSITION_LABELS[rule.weekday_position];
    return t
      ? t("dates:recurrenceSummary.onPositionWeekday", {
          position: posLabel,
          weekday: weekdayLabel,
        })
      : `on the ${posLabel} ${weekdayLabel}`;
  }
  return "";
};

export const summarizeRecurrence = (
  rule: TaskRecurrenceOutput | null,
  options?: { referenceDate?: string | null; strategy?: TaskListReadRecurrenceStrategy },
  t?: TranslateFn
): string => {
  if (!rule) {
    return t ? t("dates:recurrenceSummary.doesNotRepeat") : "Does not repeat";
  }

  const frequencyLabel = FREQUENCY_LABELS[rule.frequency];
  const unit = t
    ? rule.interval === 1
      ? t(`dates:recurrenceSummary.${frequencyLabel.singular}`)
      : t(`dates:recurrenceSummary.${frequencyLabel.plural}`)
    : rule.interval === 1
      ? frequencyLabel.singular
      : frequencyLabel.plural;
  const everyLabel = t
    ? rule.interval === 1
      ? t("dates:recurrenceSummary.everySingular", { unit })
      : t("dates:recurrenceSummary.everyPlural", { count: rule.interval, unit })
    : rule.interval === 1
      ? `every ${unit}`
      : `every ${rule.interval} ${unit}`;

  let detail = "";
  switch (rule.frequency) {
    case "weekly":
      if (rule.weekdays.length) {
        const weekdayList = formatWeekdayList(rule.weekdays, t);
        detail = t
          ? t("dates:recurrenceSummary.onWeekdays", { weekdays: weekdayList })
          : `on ${weekdayList}`;
      }
      break;
    case "monthly":
      detail = describeMonthlyDetail(rule, t);
      break;
    case "yearly": {
      const monthNum =
        typeof rule.month === "number"
          ? Math.max(1, Math.min(12, rule.month))
          : options?.referenceDate
            ? getReferenceDate(options.referenceDate).getMonth() + 1
            : null;
      const monthName =
        monthNum != null ? (t ? t(`dates:months.${monthNum}`) : MONTH_NAMES[monthNum - 1]) : "";
      const monthlyDetail = describeMonthlyDetail(rule, t);
      if (monthName && monthlyDetail) {
        detail = t
          ? t("dates:recurrenceSummary.detailOfMonth", { detail: monthlyDetail, month: monthName })
          : `${monthlyDetail} of ${monthName}`;
      } else if (monthName) {
        detail = t ? t("dates:recurrenceSummary.inMonth", { month: monthName }) : `in ${monthName}`;
      } else {
        detail = monthlyDetail;
      }
      break;
    }
    default:
      detail = "";
  }

  const schedule = everyLabel;
  const parts = [t ? t("dates:recurrenceSummary.repeats", { schedule }) : `Repeats ${schedule}`];
  if (options?.strategy === "rolling") {
    const label = t ? t("dates:recurrenceSummary.afterCompletion") : "after completion";
    parts.push(`(${label})`);
  }
  if (detail) {
    parts.push(detail);
  }
  const ending = formatEnding(rule, t);
  if (ending) {
    parts.push(ending);
  }

  return parts.join(" ");
};

export const withInterval = (
  rule: TaskRecurrenceOutput,
  interval: number
): TaskRecurrenceOutput => ({
  ...rule,
  interval: clampInterval(interval),
});

export const withEndDate = (
  rule: TaskRecurrenceOutput,
  endDate?: string | null
): TaskRecurrenceOutput => ({
  ...rule,
  ends: endDate ? "on_date" : "never",
  end_date: endDate ?? null,
  end_after_occurrences: null,
});

export const withOccurrenceCount = (
  rule: TaskRecurrenceOutput,
  count?: number
): TaskRecurrenceOutput => ({
  ...rule,
  ends: typeof count === "number" ? "after_occurrences" : "never",
  end_after_occurrences:
    typeof count === "number" ? Math.max(1, Math.min(1000, Math.floor(count))) : null,
  end_date: null,
});

export const updateWeeklyWeekdays = (
  rule: TaskRecurrenceOutput,
  weekdays: TaskRecurrenceOutputWeekdaysItem[]
): TaskRecurrenceOutput => ({
  ...rule,
  weekdays: sortWeekdays(weekdays),
});

export const updateMonthlyDay = (
  rule: TaskRecurrenceOutput,
  dayOfMonth: number
): TaskRecurrenceOutput => ({
  ...rule,
  monthly_mode: "day_of_month",
  day_of_month: Math.max(1, Math.min(31, Math.floor(dayOfMonth))),
  weekday: null,
  weekday_position: null,
});

export const updateMonthlyWeekday = (
  rule: TaskRecurrenceOutput,
  position: TaskWeekPosition,
  weekday: TaskRecurrenceOutputWeekdaysItem
): TaskRecurrenceOutput => ({
  ...rule,
  monthly_mode: "weekday",
  day_of_month: null,
  weekday_position: position,
  weekday,
});

export const updateYearlyMonth = (
  rule: TaskRecurrenceOutput,
  month: number
): TaskRecurrenceOutput => ({
  ...rule,
  month: Math.max(1, Math.min(12, Math.floor(month))),
});

export const ensureYearlyDefaults = (
  rule: TaskRecurrenceOutput,
  referenceDate?: string | null
): TaskRecurrenceOutput => {
  const anchor = getReferenceDate(referenceDate);
  return {
    ...rule,
    month: rule.month ?? anchor.getMonth() + 1,
    monthly_mode: rule.monthly_mode ?? "day_of_month",
    day_of_month:
      rule.monthly_mode === "day_of_month" ? (rule.day_of_month ?? anchor.getDate()) : null,
    weekday: rule.monthly_mode === "weekday" ? (rule.weekday ?? getWeekdayFromDate(anchor)) : null,
    weekday_position:
      rule.monthly_mode === "weekday" ? (rule.weekday_position ?? getWeekPosition(anchor)) : null,
  };
};

export const ensureMonthlyDefaults = (
  rule: TaskRecurrenceOutput,
  referenceDate?: string | null
): TaskRecurrenceOutput => {
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
