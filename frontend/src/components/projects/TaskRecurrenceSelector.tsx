import { useEffect, useState } from "react";

import type {
  TaskRecurrence,
  TaskRecurrenceFrequency,
  TaskWeekPosition,
  TaskWeekday,
} from "../../types/api";
import { Label } from "../ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { cn } from "../../lib/utils";
import {
  WEEKDAYS,
  RecurrencePreset,
  createRecurrenceFromPreset,
  detectRecurrencePreset,
  ensureMonthlyDefaults,
  ensureYearlyDefaults,
  summarizeRecurrence,
  updateMonthlyDay,
  updateMonthlyWeekday,
  updateWeeklyWeekdays,
  updateYearlyMonth,
} from "../../lib/recurrence";

const MONTH_OPTIONS = [
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

const WEEK_POSITION_OPTIONS: TaskWeekPosition[] = ["first", "second", "third", "fourth", "last"];

const frequencyOptions: { value: TaskRecurrenceFrequency; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "yearly", label: "Yearly" },
];

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
  disabled?: boolean;
  referenceDate?: string | null;
};

export const TaskRecurrenceSelector = ({
  recurrence,
  onChange,
  disabled = false,
  referenceDate,
}: TaskRecurrenceSelectorProps) => {
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
  const summary = summarizeRecurrence(recurrence, { referenceDate });
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

  const quickOptions: { value: RecurrencePreset; label: string }[] = [
    { value: "none", label: "Does not repeat" },
    { value: "daily", label: "Daily" },
    { value: "weekdays", label: "Every weekday (Mon–Fri)" },
    {
      value: "weekly",
      label: `Weekly on ${anchorDate.toLocaleDateString(undefined, { weekday: "long" })}`,
    },
    { value: "monthly", label: `Monthly on day ${anchorDate.getDate()}` },
    {
      value: "yearly",
      label: `Annually on ${anchorDate.toLocaleDateString(undefined, {
        month: "long",
        day: "numeric",
      })}`,
    },
    { value: "custom", label: "Custom…" },
  ];

  return (
    <div className="space-y-4 rounded-md border border-dashed border-border/70 p-4">
      <div className="space-y-2">
        <Label>Repeat</Label>
        <Select
          value={preset}
          onValueChange={(value) => handlePresetChange(value as RecurrencePreset)}
          disabled={disabled}
        >
          <SelectTrigger>
            <SelectValue placeholder="Does not repeat" />
          </SelectTrigger>
          <SelectContent>
            {quickOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-sm text-muted-foreground">{summary}</p>
      </div>

      {showCustomFields && recurrence ? (
        <div className="space-y-4 rounded-md border border-border/70 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Frequency</Label>
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
              <Label htmlFor="recurrence-interval">Repeat every</Label>
              <Input
                id="recurrence-interval"
                type="number"
                min={1}
                max={365}
                value={recurrence.interval}
                onChange={(event) => handleIntervalChange(event.target.value)}
                disabled={disabled}
              />
              <p className="text-xs text-muted-foreground capitalize">
                {recurrence.frequency ? `${recurrence.frequency.replace("_", " ")}` : ""}
              </p>
            </div>
          </div>

          {recurrence.frequency === "weekly" ? (
            <div className="space-y-2">
              <Label>Repeat on</Label>
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
                  <Label>Month</Label>
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
                      {MONTH_OPTIONS.map((label, index) => (
                        <SelectItem key={label} value={(index + 1).toString()}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
              <div className="space-y-2">
                <Label>On</Label>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant={recurrence.monthly_mode === "day_of_month" ? "default" : "outline"}
                    size="sm"
                    onClick={() => handleMonthlyModeChange("day_of_month")}
                    disabled={disabled}
                  >
                    Day
                  </Button>
                  <Button
                    type="button"
                    variant={recurrence.monthly_mode === "weekday" ? "default" : "outline"}
                    size="sm"
                    onClick={() => handleMonthlyModeChange("weekday")}
                    disabled={disabled}
                  >
                    Weekday
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
                        <SelectValue placeholder="Position" />
                      </SelectTrigger>
                      <SelectContent>
                        {WEEK_POSITION_OPTIONS.map((option) => (
                          <SelectItem key={option} value={option}>
                            {option.charAt(0).toUpperCase() + option.slice(1)}
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
                        <SelectValue placeholder="Weekday" />
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
            <Label>Ends</Label>
            <Select
              value={recurrence.ends ?? "never"}
              onValueChange={(value) => handleEndsChange(value as TaskRecurrence["ends"])}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="never">Never</SelectItem>
                <SelectItem value="on_date">On date</SelectItem>
                <SelectItem value="after_occurrences">After number of occurrences</SelectItem>
              </SelectContent>
            </Select>
            {recurrence.ends === "on_date" ? (
              <Input
                type="date"
                value={recurrence.end_date ? recurrence.end_date.slice(0, 10) : ""}
                onChange={(event) =>
                  onChange({
                    ...recurrence,
                    end_date: event.target.value
                      ? new Date(event.target.value).toISOString()
                      : null,
                  })
                }
                disabled={disabled}
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
        </div>
      ) : null}
    </div>
  );
};

const anchorDateToWeekday = (date: Date): TaskWeekday => {
  const weekday = date.getDay();
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
