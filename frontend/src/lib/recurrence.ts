import type { TaskListReadRecurrenceStrategy } from "@/api/generated/initiativeAPI.schemas";
import type { TranslateFn } from "@/types/i18n";

export type TaskWeekPosition = "first" | "second" | "third" | "fourth" | "last";
export type RecurrenceFrequency = "daily" | "weekly" | "monthly" | "yearly";
export type RecurrenceWeekday =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";

/**
 * A repeat as the form edits it: its days as picked, in the viewer's zone.
 * The server stores RRULE lines in UTC terms, so a rule goes out through
 * {@link toRRule} with the browser's zone, and comes back through
 * {@link fromStored}.
 */
export type RecurrenceRule = {
  frequency: RecurrenceFrequency;
  interval: number;
  weekdays: RecurrenceWeekday[];
  monthly_mode: "day_of_month" | "weekday";
  day_of_month: number | null;
  month: number | null;
  weekday_position: TaskWeekPosition | null;
  weekday: RecurrenceWeekday | null;
  ends: "never" | "on_date" | "after_occurrences";
  end_after_occurrences: number | null;
  end_date: string | null;
};

export type RecurrencePreset =
  | "none"
  | "daily"
  | "weekly"
  | "weekdays"
  | "monthly"
  | "yearly"
  | "custom";

type WeekdayConfig = {
  value: RecurrenceWeekday;
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
) as Record<RecurrenceWeekday, number>;

/** The `dates:recurrenceSummary.*` unit keys for each frequency. */
const FREQUENCY_LABELS: Record<RecurrenceFrequency, { singular: string; plural: string }> = {
  daily: { singular: "day", plural: "days" },
  weekly: { singular: "week", plural: "weeks" },
  monthly: { singular: "month", plural: "months" },
  yearly: { singular: "year", plural: "years" },
};

export const getReferenceDate = (value?: string | null): Date => {
  if (!value) {
    return new Date();
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return new Date();
  }
  return parsed;
};

export const getWeekdayFromDate = (date: Date): RecurrenceWeekday => {
  // Normalize to midnight local time to get the date's weekday regardless of time
  const normalized = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = normalized.getDay(); // 0 (Sun) - 6 (Sat)
  const match = WEEKDAYS.find((weekday) => weekday.dateIndex === day);
  return match ? match.value : "monday";
};

export const getWeekPosition = (date: Date): TaskWeekPosition => {
  const day = date.getDate();
  const daysInMonth = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
  if (day + 7 > daysInMonth) {
    return "last";
  }
  const index = Math.ceil(day / 7);
  return (["first", "second", "third", "fourth"][index - 1] ?? "last") as TaskWeekPosition;
};

const sortWeekdays = (weekdays: RecurrenceWeekday[]) =>
  [...new Set(weekdays)].sort((a, b) => WEEKDAY_ORDER[a] - WEEKDAY_ORDER[b]);

const baseRule = (): RecurrenceRule => ({
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
): RecurrenceRule | null => {
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

export const detectRecurrencePreset = (rule: RecurrenceRule | null): RecurrencePreset => {
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

const formatWeekdayList = (weekdays: RecurrenceWeekday[], t: TranslateFn) => {
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

const formatEnding = (rule: RecurrenceRule, t: TranslateFn) => {
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

const describeMonthlyDetail = (rule: RecurrenceRule, t: TranslateFn) => {
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
  rule: RecurrenceRule | null,
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
  rule: RecurrenceRule,
  weekdays: RecurrenceWeekday[]
): RecurrenceRule => ({
  ...rule,
  weekdays: sortWeekdays(weekdays),
});

export const updateMonthlyDay = (rule: RecurrenceRule, dayOfMonth: number): RecurrenceRule => ({
  ...rule,
  monthly_mode: "day_of_month",
  day_of_month: Math.max(1, Math.min(31, Math.floor(dayOfMonth))),
  weekday: null,
  weekday_position: null,
});

export const updateMonthlyWeekday = (
  rule: RecurrenceRule,
  position: TaskWeekPosition,
  weekday: RecurrenceWeekday
): RecurrenceRule => ({
  ...rule,
  monthly_mode: "weekday",
  day_of_month: null,
  weekday_position: position,
  weekday,
});

export const updateYearlyMonth = (rule: RecurrenceRule, month: number): RecurrenceRule => ({
  ...rule,
  month: Math.max(1, Math.min(12, Math.floor(month))),
});

export const ensureYearlyDefaults = (
  rule: RecurrenceRule,
  referenceDate?: string | null
): RecurrenceRule => {
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
  rule: RecurrenceRule,
  referenceDate?: string | null
): RecurrenceRule => {
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

// ---------------------------------------------------------------------------
// RRULE lines
// ---------------------------------------------------------------------------

const CODES: Record<RecurrenceWeekday, string> = {
  monday: "MO",
  tuesday: "TU",
  wednesday: "WE",
  thursday: "TH",
  friday: "FR",
  saturday: "SA",
  sunday: "SU",
};
const CODE_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const WEEKDAY_OF = Object.fromEntries(
  Object.entries(CODES).map(([name, code]) => [code, name])
) as Record<string, RecurrenceWeekday>;
const POSITION_NUMBERS: Record<TaskWeekPosition, number> = {
  first: 1,
  second: 2,
  third: 3,
  fourth: 4,
  last: -1,
};
const POSITION_OF = Object.fromEntries(
  Object.entries(POSITION_NUMBERS).map(([name, n]) => [n, name])
) as Record<number, TaskWeekPosition>;

/** The browser's zone, sent beside a rule so the server can store it. */
export const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * The RRULE for a rule as picked. Send it with `tz: browserTimezone()`; the
 * server converts its days to UTC terms. An all-day event ends on a date.
 */
export const toRRule = (rule: RecurrenceRule, options?: { allDay?: boolean }): string => {
  const parts = [`FREQ=${rule.frequency.toUpperCase()}`];
  if (rule.interval > 1) parts.push(`INTERVAL=${rule.interval}`);
  if (rule.frequency === "weekly" && rule.weekdays.length) {
    parts.push(
      `BYDAY=${sortWeekdays(rule.weekdays)
        .map((day) => CODES[day])
        .join(",")}`
    );
  }
  if (rule.frequency === "monthly" || rule.frequency === "yearly") {
    if (rule.monthly_mode === "weekday" && rule.weekday && rule.weekday_position) {
      parts.push(`BYDAY=${POSITION_NUMBERS[rule.weekday_position]}${CODES[rule.weekday]}`);
    } else if (rule.day_of_month) {
      const day = rule.day_of_month;
      // A day a short month lacks falls on that month's last day.
      parts.push(
        day <= 28
          ? `BYMONTHDAY=${day}`
          : `BYMONTHDAY=${Array.from({ length: day - 27 }, (_, i) => 28 + i).join(",")};BYSETPOS=-1`
      );
    }
    if (rule.frequency === "yearly" && rule.month) parts.push(`BYMONTH=${rule.month}`);
  }
  if (rule.ends === "after_occurrences" && rule.end_after_occurrences) {
    parts.push(`COUNT=${rule.end_after_occurrences}`);
  } else if (rule.ends === "on_date" && rule.end_date) {
    const [y, m, d] = rule.end_date.slice(0, 10).split("-").map(Number);
    if (options?.allDay) {
      parts.push(`UNTIL=${y}${pad(m)}${pad(d)}`);
    } else {
      // The end of the picked day, where it is picked.
      const u = new Date(y, m - 1, d, 23, 59, 59);
      const day = `${u.getUTCFullYear()}${pad(u.getUTCMonth() + 1)}${pad(u.getUTCDate())}`;
      parts.push(
        `UNTIL=${day}T${pad(u.getUTCHours())}${pad(u.getUTCMinutes())}${pad(u.getUTCSeconds())}Z`
      );
    }
  }
  return `RRULE:${parts.join(";")}`;
};

type Parts = Map<string, string[]>;

const parseRule = (text: string): Parts | null => {
  const line = text
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.startsWith("RRULE:"));
  // A rule with skipped or extra dates is more than the form edits.
  if (!line || text.includes("EXDATE") || text.includes("RDATE")) return null;
  const parts: Parts = new Map();
  for (const part of line.slice("RRULE:".length).split(";")) {
    const [key, value] = part.split("=");
    if (key && value !== undefined) parts.set(key, value.split(","));
  }
  return parts;
};

const utcDayNumber = (date: Date) =>
  Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) / 86_400_000;
const localDayNumber = (date: Date) =>
  Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000;

// The nth weekday falls on one stretch of the month: 1–7 for the first, 29–31
// for the fifth, -7 to -1 for the last.
const stretch = (ordinal: number): number[] =>
  ordinal > 0
    ? Array.from(
        { length: Math.min(7 * ordinal, 31) - 7 * (ordinal - 1) },
        (_, i) => 7 * (ordinal - 1) + 1 + i
      )
    : Array.from({ length: 7 }, (_, i) => 7 * ordinal + i);

const moveMonthday = (day: number, days: number): number => {
  const moved = day + days;
  if (day > 0 && moved === 0) return -1;
  if (day < 0 && moved === 0) return 1;
  return moved > 31 ? 1 : moved;
};

/**
 * A stored rule's days read in the viewer's zone: the day parts move by the
 * day the start's local date is from its UTC date. Only the shapes the server
 * writes for the form's rules are read back; anything else stays as stored.
 */
const toLocalParts = (parts: Parts, start: Date): Parts => {
  const days = localDayNumber(start) - utcDayNumber(start);
  if (!days) return parts;
  const moved: Parts = new Map(parts);
  const byday = parts.get("BYDAY") ?? [];
  let monthdays = (parts.get("BYMONTHDAY") ?? []).map(Number);
  const shiftCode = (code: string) =>
    CODE_ORDER[(CODE_ORDER.indexOf(code.slice(-2)) + days + 7) % 7];
  if (byday.length === 1 && byday[0].length > 2 && !monthdays.length) {
    monthdays = stretch(Number(byday[0].slice(0, -2)));
  }
  if (byday.length)
    moved.set(
      "BYDAY",
      byday.map((code) => shiftCode(code))
    );
  if (monthdays.length) {
    const next = [...new Set(monthdays.map((day) => moveMonthday(day, days)))];
    const sorted = [
      ...next.filter((d) => d > 0).sort((a, b) => a - b),
      ...next.filter((d) => d < 0).sort((a, b) => a - b),
    ];
    const ordinal = [1, 2, 3, 4, 5, -1].find((n) => stretch(n).join() === sorted.join());
    if (byday.length === 1 && ordinal !== undefined) {
      moved.set("BYDAY", [`${ordinal}${shiftCode(byday[0])}`]);
      moved.delete("BYMONTHDAY");
    } else {
      moved.set("BYMONTHDAY", sorted.map(String));
    }
    const month = parts.get("BYMONTH");
    const crossing = monthdays.every(
      (day) => (day === 1 && days < 0) || ((day === -1 || day === 31) && days > 0)
    );
    if (month && crossing) {
      moved.set(
        "BYMONTH",
        month.map((m) => String(((Number(m) - 1 + days + 12) % 12) + 1))
      );
    }
  }
  return moved;
};

/**
 * The rule the form edits, from a stored rule and its series start (an event's
 * start, a task's due date): `null` for no repeat, `"custom"` for one the form
 * can't show, which is kept as it is until somebody picks another.
 */
export const fromStored = (
  stored: string | null | undefined,
  start: string | null | undefined
): RecurrenceRule | "custom" | null => {
  if (!stored) return null;
  const raw = parseRule(stored);
  if (!raw) return "custom";
  const parts = start ? toLocalParts(raw, new Date(start)) : raw;
  const freq = (parts.get("FREQ")?.[0] ?? "").toLowerCase() as RecurrenceFrequency;
  if (!(freq in FREQUENCY_LABELS)) return "custom";
  const known = new Set([
    "FREQ",
    "INTERVAL",
    "COUNT",
    "UNTIL",
    "BYDAY",
    "BYMONTHDAY",
    "BYMONTH",
    "BYSETPOS",
  ]);
  if ([...parts.keys()].some((key) => !known.has(key))) return "custom";

  const rule: RecurrenceRule = {
    ...baseRule(),
    frequency: freq,
    interval: Number(parts.get("INTERVAL")?.[0] ?? 1),
  };
  const byday = parts.get("BYDAY") ?? [];
  const monthdays = (parts.get("BYMONTHDAY") ?? []).map(Number);
  const setpos = parts.get("BYSETPOS");
  if (freq === "weekly") {
    if (monthdays.length || setpos || byday.some((code) => !WEEKDAY_OF[code])) return "custom";
    rule.weekdays = byday.map((code) => WEEKDAY_OF[code]);
  } else if (freq === "monthly" || freq === "yearly") {
    if (
      byday.length === 1 &&
      POSITION_OF[Number(byday[0].slice(0, -2))] &&
      !monthdays.length &&
      !setpos
    ) {
      rule.monthly_mode = "weekday";
      rule.weekday_position = POSITION_OF[Number(byday[0].slice(0, -2))];
      rule.weekday = WEEKDAY_OF[byday[0].slice(-2)] ?? null;
    } else if (
      !byday.length &&
      monthdays.length === 1 &&
      monthdays[0] >= 1 &&
      monthdays[0] <= 28 &&
      !setpos
    ) {
      rule.day_of_month = monthdays[0];
    } else if (
      !byday.length &&
      setpos?.join() === "-1" &&
      monthdays[0] === 28 &&
      monthdays.every((day, i) => day === 28 + i) &&
      monthdays.length <= 4
    ) {
      rule.day_of_month = 27 + monthdays.length;
    } else if (byday.length || monthdays.length || setpos) {
      return "custom";
    }
    const months = parts.get("BYMONTH");
    if (months && (freq === "monthly" || months.length > 1)) return "custom";
    rule.month = months ? Number(months[0]) : null;
  } else if (byday.length || monthdays.length || setpos || parts.has("BYMONTH")) {
    return "custom";
  }
  if (parts.has("COUNT")) {
    rule.ends = "after_occurrences";
    rule.end_after_occurrences = Number(parts.get("COUNT")?.[0]);
  } else if (parts.has("UNTIL")) {
    const value = parts.get("UNTIL")?.[0] ?? "";
    const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
    rule.ends = "on_date";
    // An instant's last day is the viewer's; a date is itself.
    rule.end_date =
      value.length > 8
        ? toLocalDateKey(
            new Date(`${iso}T${value.slice(9, 11)}:${value.slice(11, 13)}:${value.slice(13, 15)}Z`)
          )
        : iso;
  }
  return rule;
};

const toLocalDateKey = (date: Date) =>
  `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

/** A stored rule's summary for a list: the form's words, or a custom repeat. */
export const summarizeStored = (
  stored: string | null | undefined,
  start: string | null | undefined,
  options: { strategy?: TaskListReadRecurrenceStrategy } | undefined,
  t: TranslateFn
): string => {
  const rule = fromStored(stored, start);
  if (rule === "custom") return t("dates:recurrenceSummary.custom");
  return summarizeRecurrence(rule, { referenceDate: start, strategy: options?.strategy }, t);
};

/**
 * The write fields for a repeat from the form: a picked rule with the zone its
 * days are in, `null` to stop repeating, or nothing for a custom rule, which
 * keeps what is stored.
 */
export const rulePayload = (
  rule: RecurrenceRule | "custom" | null,
  options?: { allDay?: boolean }
): { recurrence?: string | null; tz?: string } => {
  if (rule === "custom") return {};
  if (rule === null) return { recurrence: null };
  return { recurrence: toRRule(rule, options), tz: browserTimezone() };
};

/**
 * A task or event update with the browser's zone beside it, so a stored
 * repeat moves with a start that moved, its days kept where they were picked.
 */
export const withZone = <T extends object>(data: T): T & { tz?: string } => ({
  tz: browserTimezone(),
  ...data,
});
