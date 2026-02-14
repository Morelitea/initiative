import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskRecurrence,
  TaskRecurrenceFrequency,
  TaskRecurrenceStrategy,
  TaskWeekPosition,
  TaskWeekday,
} from "@/types/api";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { cn } from "@/lib/utils";
import {
  WEEKDAYS,
  RecurrencePreset,
  createRecurrenceFromPreset,
  detectRecurrencePreset,
  ensureMonthlyDefaults,
  ensureYearlyDefaults,
  updateMonthlyDay,
  updateMonthlyWeekday,
  updateWeeklyWeekdays,
  updateYearlyMonth,
} from "@/lib/recurrence";

const MONTH_KEYS = [
  "recurrence.monthJanuary",
  "recurrence.monthFebruary",
  "recurrence.monthMarch",
  "recurrence.monthApril",
  "recurrence.monthMay",
  "recurrence.monthJune",
  "recurrence.monthJuly",
  "recurrence.monthAugust",
  "recurrence.monthSeptember",
  "recurrence.monthOctober",
  "recurrence.monthNovember",
  "recurrence.monthDecember",
] as const;

const WEEK_POSITION_OPTIONS: TaskWeekPosition[] = ["first", "second", "third", "fourth", "last"];

const POSITION_KEYS: Record<TaskWeekPosition, string> = {
  first: "recurrence.positionFirst",
  second: "recurrence.positionSecond",
  third: "recurrence.positionThird",
  fourth: "recurrence.positionFourth",
  last: "recurrence.positionLast",
};

const FREQUENCY_UNIT_KEYS: Record<TaskRecurrenceFrequency, string> = {
  daily: "recurrence.repeatEveryDays",
  weekly: "recurrence.repeatEveryWeeks",
  monthly: "recurrence.repeatEveryMonths",
  yearly: "recurrence.repeatEveryYears",
};

const getAnchorDate = (referenceDate?: string | null) => {
  if (!referenceDate) {
    return new Date();
  }
  const parsed = new Date(referenceDate);
  if (Number.isNaN(parsed.getTime())) {
    return new Date();
  }
  return parsed;
};

type TaskRecurrenceSelectorProps = {
  recurrence: TaskRecurrence | null;
  onChange: (rule: TaskRecurrence | null) => void;
  strategy: TaskRecurrenceStrategy;
  onStrategyChange: (value: TaskRecurrenceStrategy) => void;
  disabled?: boolean;
  referenceDate?: string | null;
};

export const TaskRecurrenceSelector = ({
  recurrence,
  onChange,
  strategy,
  onStrategyChange,
  disabled = false,
  referenceDate,
}: TaskRecurrenceSelectorProps) => {
  const { t, i18n } = useTranslation("projects");

  const detectedPreset = detectRecurrencePreset(recurrence);
  const [forceCustomMode, setForceCustomMode] = useState(detectedPreset === "custom");
  useEffect(() => {
    if (recurrence === null && forceCustomMode) {
      setForceCustomMode(false);
      return;
    }
    if (detectedPreset === "custom" && recurrence && !forceCustomMode) {
      setForceCustomMode(true);
    }
  }, [detectedPreset, forceCustomMode, recurrence]);

  const preset = forceCustomMode ? "custom" : detectedPreset;
  const anchorDate = getAnchorDate(referenceDate);
  const showCustomFields = forceCustomMode && recurrence !== null;

  const ensureRule = (): TaskRecurrence => {
    if (recurrence) {
      return recurrence;
    }
    const created = createRecurrenceFromPreset("daily", referenceDate);
    if (!created) {
      throw new Error("Unable to initialize recurrence rule");
    }
    return created;
  };

  const handlePresetChange = (value: RecurrencePreset) => {
    if (value === "custom") {
      setForceCustomMode(true);
      onChange(ensureRule());
      return;
    }
    setForceCustomMode(false);
    const next = createRecurrenceFromPreset(value, referenceDate);
    onChange(next);
  };

  const handleFrequencyChange = (value: TaskRecurrenceFrequency) => {
    const rule = ensureRule();
    let next: TaskRecurrence = {
      ...rule,
      frequency: value,
      interval: 1,
      weekdays: value === "weekly" ? rule.weekdays : [],
      ends: rule.ends,
      end_after_occurrences: rule.end_after_occurrences,
      end_date: rule.end_date,
    };
    if (value === "weekly") {
      const existing = rule.weekdays.length ? rule.weekdays : [anchorDateToWeekday(anchorDate)];
      next = { ...next, weekdays: existing };
    } else if (value === "monthly") {
      next = ensureMonthlyDefaults({ ...next, weekdays: [] }, referenceDate);
    } else if (value === "yearly") {
      next = ensureYearlyDefaults({ ...next, weekdays: [] }, referenceDate);
    } else {
      next = {
        ...next,
        weekdays: [],
        monthly_mode: "day_of_month",
        day_of_month: null,
        weekday: null,
        weekday_position: null,
        month: null,
      };
    }
    onChange(next);
  };

  const handleIntervalChange = (value: string) => {
    const rule = ensureRule();
    const parsed = Number.parseInt(value, 10);
    const interval = Number.isNaN(parsed) ? 1 : Math.max(1, Math.min(365, parsed));
    onChange({ ...rule, interval });
  };

  const handleWeekdayToggle = (weekday: TaskWeekday) => {
    const rule = ensureRule();
    const set = new Set(rule.weekdays);
    if (set.has(weekday)) {
      set.delete(weekday);
    } else {
      set.add(weekday);
    }
    const nextWeekdays = [...set];
    if (nextWeekdays.length === 0) {
      return;
    }
    onChange(updateWeeklyWeekdays(rule, nextWeekdays));
  };

  const handleMonthlyModeChange = (mode: "day_of_month" | "weekday") => {
    const rule = ensureRule();
    if (mode === "day_of_month") {
      const day = rule.day_of_month ?? anchorDate.getDate();
      onChange(updateMonthlyDay(rule, day));
    } else {
      const weekday = (rule.weekday ?? anchorDateToWeekday(anchorDate)) as TaskWeekday;
      const position = (rule.weekday_position ?? getWeekPosition(anchorDate)) as TaskWeekPosition;
      onChange(updateMonthlyWeekday(rule, position, weekday));
    }
  };

  const handleEndsChange = (value: "never" | "on_date" | "after_occurrences") => {
    const rule = ensureRule();
    if (value === "never") {
      onChange({
        ...rule,
        ends: "never",
        end_date: null,
        end_after_occurrences: null,
      });
    } else if (value === "on_date") {
      const fallback = rule.end_date ?? anchorDate.toISOString();
      onChange({
        ...rule,
        ends: "on_date",
        end_date: fallback,
        end_after_occurrences: null,
      });
    } else {
      onChange({
        ...rule,
        ends: "after_occurrences",
        end_after_occurrences: rule.end_after_occurrences ?? 5,
        end_date: null,
      });
    }
  };

  const frequencyOptions = useMemo(
    (): { value: TaskRecurrenceFrequency; label: string }[] => [
      { value: "daily", label: t("recurrence.frequencyDaily") },
      { value: "weekly", label: t("recurrence.frequencyWeekly") },
      { value: "monthly", label: t("recurrence.frequencyMonthly") },
      { value: "yearly", label: t("recurrence.frequencyYearly") },
    ],
    [t]
  );

  const quickOptions = useMemo(
    (): { value: RecurrencePreset; label: string }[] => [
      { value: "none", label: t("recurrence.doesNotRepeat") },
      { value: "daily", label: t("recurrence.daily") },
      { value: "weekdays", label: t("recurrence.everyWeekday") },
      {
        value: "weekly",
        label: t("recurrence.weeklyOn", {
          day: anchorDate.toLocaleDateString(undefined, { weekday: "long" }),
        }),
      },
      {
        value: "monthly",
        label: t("recurrence.monthlyOnDay", { day: anchorDate.getDate() }),
      },
      {
        value: "yearly",
        label: t("recurrence.annuallyOn", {
          month: anchorDate.toLocaleDateString(undefined, { month: "long" }),
          day: anchorDate.getDate(),
        }),
      },
      { value: "custom", label: t("recurrence.custom") },
    ],
    [anchorDate, t]
  );

  const monthOptions = useMemo(
    () => MONTH_KEYS.map((key, index) => ({ label: t(key), value: index + 1 })),
    [t]
  );

  const formatWeekdayList = useCallback(
    (weekdays: TaskWeekday[]) => {
      if (!weekdays.length) {
        return "";
      }
      const sorted = [...new Set(weekdays)].sort((a, b) => {
        const orderA = WEEKDAYS.findIndex((w) => w.value === a);
        const orderB = WEEKDAYS.findIndex((w) => w.value === b);
        return orderA - orderB;
      });
      const labels = sorted.map(
        (day) => WEEKDAYS.find((config) => config.value === day)?.label ?? day
      );
      const formatter = new Intl.ListFormat(i18n.language, {
        style: "long",
        type: "conjunction",
      });
      return formatter.format(labels);
    },
    [i18n.language]
  );

  const summary = useMemo(() => {
    if (!recurrence) {
      return t("recurrence.doesNotRepeat");
    }
    const rule = recurrence;
    const interval = rule.interval;

    let base = "";
    switch (rule.frequency) {
      case "daily":
        base =
          interval === 1
            ? t("recurrence.summary.everyDay")
            : t("recurrence.summary.everyNDays", { count: interval });
        break;
      case "weekly": {
        const days = formatWeekdayList(rule.weekdays);
        base =
          interval === 1
            ? t("recurrence.summary.everyWeek", { days })
            : t("recurrence.summary.everyNWeeks", { count: interval, days });
        break;
      }
      case "monthly": {
        if (rule.monthly_mode === "day_of_month" && typeof rule.day_of_month === "number") {
          base =
            interval === 1
              ? t("recurrence.summary.everyMonthDay", { day: rule.day_of_month })
              : t("recurrence.summary.everyNMonthsDay", {
                  count: interval,
                  day: rule.day_of_month,
                });
        } else if (rule.weekday_position && rule.weekday) {
          const weekdayLabel =
            WEEKDAYS.find((item) => item.value === rule.weekday)?.label ?? rule.weekday;
          const positionLabel = rule.weekday_position;
          base =
            interval === 1
              ? t("recurrence.summary.everyMonthWeekday", {
                  position: positionLabel,
                  weekday: weekdayLabel,
                })
              : t("recurrence.summary.everyNMonthsWeekday", {
                  count: interval,
                  position: positionLabel,
                  weekday: weekdayLabel,
                });
        }
        break;
      }
      case "yearly": {
        const monthIndex =
          typeof rule.month === "number"
            ? Math.max(1, Math.min(12, rule.month)) - 1
            : referenceDate
              ? getAnchorDate(referenceDate).getMonth()
              : new Date().getMonth();
        const monthName = t(MONTH_KEYS[monthIndex]);
        const day =
          rule.monthly_mode === "day_of_month" && typeof rule.day_of_month === "number"
            ? rule.day_of_month
            : getAnchorDate(referenceDate).getDate();
        base =
          interval === 1
            ? t("recurrence.summary.everyYear", { month: monthName, day })
            : t("recurrence.summary.everyNYears", { count: interval, month: monthName, day });
        break;
      }
    }

    return base || t("recurrence.doesNotRepeat");
  }, [recurrence, referenceDate, t, formatWeekdayList]);

  return (
    <div className="border-border/70 space-y-4 rounded-md border border-dashed p-4">
      <div className="space-y-2">
        <Label>{t("recurrence.repeat")}</Label>
        <Select
          value={preset}
          onValueChange={(value) => handlePresetChange(value as RecurrencePreset)}
          disabled={disabled}
        >
          <SelectTrigger>
            <SelectValue placeholder={t("recurrence.doesNotRepeat")} />
          </SelectTrigger>
          <SelectContent>
            {quickOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-sm">{summary}</p>
      </div>

      {showCustomFields && recurrence ? (
        <div className="border-border/70 space-y-4 rounded-md border p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("recurrence.frequency")}</Label>
              <Select
                value={recurrence.frequency}
                onValueChange={(value) => handleFrequencyChange(value as TaskRecurrenceFrequency)}
                disabled={disabled}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {frequencyOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="recurrence-interval">{t("recurrence.repeatEvery")}</Label>
              <Input
                id="recurrence-interval"
                type="number"
                min={1}
                max={365}
                value={recurrence.interval}
                onChange={(event) => handleIntervalChange(event.target.value)}
                disabled={disabled}
              />
              <p className="text-muted-foreground text-xs">
                {recurrence.frequency ? t(FREQUENCY_UNIT_KEYS[recurrence.frequency]) : ""}
              </p>
            </div>
          </div>

          {recurrence.frequency === "weekly" ? (
            <div className="space-y-2">
              <Label>{t("recurrence.repeatOn")}</Label>
              <div className="flex flex-wrap gap-2">
                {WEEKDAYS.map((weekday) => {
                  const checked = recurrence.weekdays.includes(weekday.value);
                  return (
                    <button
                      key={weekday.value}
                      type="button"
                      onClick={() => handleWeekdayToggle(weekday.value)}
                      disabled={disabled}
                      className={cn(
                        "rounded-md border px-3 py-1 text-sm",
                        checked
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border text-foreground",
                        disabled ? "opacity-70" : ""
                      )}
                    >
                      {weekday.short}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {recurrence.frequency === "monthly" || recurrence.frequency === "yearly" ? (
            <div className="space-y-4">
              {recurrence.frequency === "yearly" ? (
                <div className="space-y-2">
                  <Label>{t("recurrence.month")}</Label>
                  <Select
                    value={(recurrence.month ?? anchorDate.getMonth() + 1).toString()}
                    onValueChange={(value) =>
                      onChange(updateYearlyMonth(ensureRule(), Number(value)))
                    }
                    disabled={disabled}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {monthOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value.toString()}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
              <div className="space-y-2">
                <Label>{t("recurrence.on")}</Label>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant={recurrence.monthly_mode === "day_of_month" ? "default" : "outline"}
                    size="sm"
                    onClick={() => handleMonthlyModeChange("day_of_month")}
                    disabled={disabled}
                  >
                    {t("recurrence.dayMode")}
                  </Button>
                  <Button
                    type="button"
                    variant={recurrence.monthly_mode === "weekday" ? "default" : "outline"}
                    size="sm"
                    onClick={() => handleMonthlyModeChange("weekday")}
                    disabled={disabled}
                  >
                    {t("recurrence.weekdayMode")}
                  </Button>
                </div>
                {recurrence.monthly_mode === "day_of_month" ? (
                  <Input
                    type="number"
                    min={1}
                    max={31}
                    value={recurrence.day_of_month ?? anchorDate.getDate()}
                    onChange={(event) =>
                      onChange(updateMonthlyDay(ensureRule(), Number(event.target.value)))
                    }
                    disabled={disabled}
                  />
                ) : (
                  <div className="grid gap-3 md:grid-cols-2">
                    <Select
                      value={recurrence.weekday_position ?? "first"}
                      onValueChange={(value) =>
                        onChange(
                          updateMonthlyWeekday(
                            ensureRule(),
                            value as TaskWeekPosition,
                            (recurrence.weekday ?? "monday") as TaskWeekday
                          )
                        )
                      }
                      disabled={disabled}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder={t("recurrence.position")} />
                      </SelectTrigger>
                      <SelectContent>
                        {WEEK_POSITION_OPTIONS.map((option) => (
                          <SelectItem key={option} value={option}>
                            {t(POSITION_KEYS[option])}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select
                      value={recurrence.weekday ?? "monday"}
                      onValueChange={(value) =>
                        onChange(
                          updateMonthlyWeekday(
                            ensureRule(),
                            (recurrence.weekday_position ?? "first") as TaskWeekPosition,
                            value as TaskWeekday
                          )
                        )
                      }
                      disabled={disabled}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder={t("recurrence.weekday")} />
                      </SelectTrigger>
                      <SelectContent>
                        {WEEKDAYS.map((weekday) => (
                          <SelectItem key={weekday.value} value={weekday.value}>
                            {weekday.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>
            </div>
          ) : null}

          <div className="space-y-2">
            <Label>{t("recurrence.ends")}</Label>
            <Select
              value={recurrence.ends ?? "never"}
              onValueChange={(value) => handleEndsChange(value as TaskRecurrence["ends"])}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="never">{t("recurrence.endsNever")}</SelectItem>
                <SelectItem value="on_date">{t("recurrence.endsOnDate")}</SelectItem>
                <SelectItem value="after_occurrences">{t("recurrence.endsAfterCount")}</SelectItem>
              </SelectContent>
            </Select>
            {recurrence.ends === "on_date" ? (
              <DateTimePicker
                value={recurrence.end_date ? recurrence.end_date.slice(0, 10) : ""}
                onChange={(value) =>
                  onChange({
                    ...recurrence,
                    end_date: value || null,
                  })
                }
                disabled={disabled}
                includeTime={false}
              />
            ) : null}
            {recurrence.ends === "after_occurrences" ? (
              <Input
                type="number"
                min={1}
                max={1000}
                value={recurrence.end_after_occurrences ?? 5}
                onChange={(event) =>
                  onChange({
                    ...recurrence,
                    end_after_occurrences: Math.max(1, Math.min(1000, Number(event.target.value))),
                  })
                }
                disabled={disabled}
              />
            ) : null}
          </div>

          <div className="space-y-2">
            <Label>{t("recurrence.repeatStrategy")}</Label>
            <Select
              value={strategy}
              onValueChange={(value) => onStrategyChange(value as TaskRecurrenceStrategy)}
              disabled={disabled || !recurrence}
            >
              <SelectTrigger>
                <SelectValue placeholder={t("recurrence.selectStrategy")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fixed">{t("recurrence.strategyOnSchedule")}</SelectItem>
                <SelectItem value="rolling">{t("recurrence.strategyAfterCompletion")}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              {strategy === "rolling"
                ? t("recurrence.strategyAfterCompletionDescription")
                : t("recurrence.strategyOnScheduleDescription")}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const anchorDateToWeekday = (date: Date): TaskWeekday => {
  // Normalize to midnight local time to get the date's weekday regardless of time
  const normalized = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const weekday = normalized.getDay();
  const match = WEEKDAYS.find((item) => item.dateIndex === weekday);
  return match?.value ?? "monday";
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
