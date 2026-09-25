import type {
  TaskListReadRecurrenceStrategy,
  TaskRecurrenceOutput,
  TaskRecurrenceOutputFrequency,
  TaskRecurrenceOutputWeekdaysItem,
} from "@/api/generated/initiativeAPI.schemas";

export type TaskWeekPosition = "first" | "second" | "third" | "fourth" | "last";

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
  dateIndex: number;
};

export const WEEKDAYS: WeekdayConfig[] = [
  { value: "monday", dateIndex: 1 },
  { value: "tuesday", dateIndex: 2 },
  { value: "wednesday", dateIndex: 3 },
  { value: "thursday", dateIndex: 4 },
  { value: "friday", dateIndex: 5 },
  { value: "saturday", dateIndex: 6 },
  { value: "sunday", dateIndex: 0 },
];

const WEEKDAY_ORDER = Object.fromEntries(
  WEEKDAYS.map((item, index) => [item.value, index])
) as Record<TaskRecurrenceOutputWeekdaysItem, number>;

/** The `dates:recurrenceSummary.*` unit keys for each frequency. */
const FREQUENCY_LABELS: Record<
  TaskRecurrenceOutputFrequency,
  { singular: string; plural: string }
> = {
  daily: { singular: "day", plural: "days" },
  weekly: { singular: "week", plural: "weeks" },
  monthly: { singular: "month", plural: "months" },
  yearly: { singular: "year", plural: "years" },
};

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

const formatWeekdayList = (weekdays: TaskRecurrenceOutputWeekdaysItem[], t: TranslateFn) => {
  if (!weekdays.length) {
    return "";
  }
  const labels = sortWeekdays(weekdays).map((day) => t(`dates:weekdays.${day}`));
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

const formatEnding = (rule: TaskRecurrenceOutput, t: TranslateFn) => {
  if (rule.ends === "on_date" && rule.end_date) {
    // Parse date-only string as local date to avoid timezone issues
    const match = rule.end_date.match(/^(\d{4})-(\d{2})-(\d{2})/);
    const date = match
      ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
      : new Date(rule.end_date);
    if (!Number.isNaN(date.getTime())) {
      return t("dates:recurrenceSummary.untilDate", { date: date.toLocaleDateString() });
    }
  }
  if (rule.ends === "after_occurrences" && typeof rule.end_after_occurrences === "number") {
    return t("dates:recurrenceSummary.forOccurrences", { count: rule.end_after_occurrences });
  }
  return "";
};

const describeMonthlyDetail = (rule: TaskRecurrenceOutput, t: TranslateFn) => {
  if (rule.monthly_mode === "day_of_month" && typeof rule.day_of_month === "number") {
    return t("dates:recurrenceSummary.onDay", { day: rule.day_of_month });
  }
  if (rule.weekday_position && rule.weekday) {
    return t("dates:recurrenceSummary.onPositionWeekday", {
      position: t(`dates:positions.${rule.weekday_position}`),
      weekday: t(`dates:weekdays.${rule.weekday}`),
    });
  }
  return "";
};

export const summarizeRecurrence = (
  rule: TaskRecurrenceOutput | null,
  options: { referenceDate?: string | null; strategy?: TaskListReadRecurrenceStrategy } | undefined,
  t: TranslateFn
): string => {
  if (!rule) {
    return t("dates:recurrenceSummary.doesNotRepeat");
  }

  const frequencyLabel = FREQUENCY_LABELS[rule.frequency];
  const unit =
    rule.interval === 1
      ? t(`dates:recurrenceSummary.${frequencyLabel.singular}`)
      : t(`dates:recurrenceSummary.${frequencyLabel.plural}`);
  const schedule =
    rule.interval === 1
      ? t("dates:recurrenceSummary.everySingular", { unit })
      : t("dates:recurrenceSummary.everyPlural", { count: rule.interval, unit });

  let detail = "";
  switch (rule.frequency) {
    case "weekly":
      if (rule.weekdays.length) {
        detail = t("dates:recurrenceSummary.onWeekdays", {
          weekdays: formatWeekdayList(rule.weekdays, t),
        });
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
      const monthName = monthNum != null ? t(`dates:months.${monthNum}`) : "";
      const monthlyDetail = describeMonthlyDetail(rule, t);
      if (monthName && monthlyDetail) {
        detail = t("dates:recurrenceSummary.detailOfMonth", {
          detail: monthlyDetail,
          month: monthName,
        });
      } else if (monthName) {
        detail = t("dates:recurrenceSummary.inMonth", { month: monthName });
      } else {
        detail = monthlyDetail;
      }
      break;
    }
    default:
      detail = "";
  }

  const parts = [t("dates:recurrenceSummary.repeats", { schedule })];
  if (options?.strategy === "rolling") {
    parts.push(`(${t("dates:recurrenceSummary.afterCompletion")})`);
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
