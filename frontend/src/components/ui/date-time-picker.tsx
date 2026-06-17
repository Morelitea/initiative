import { format, isValid, parse } from "date-fns";
import { Calendar as CalendarIcon } from "lucide-react";
import * as React from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

interface DateTimePickerProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  clearLabel?: string;
  calendarProps?: React.ComponentProps<typeof Calendar>;
  includeTime?: boolean;
}

const formatForStorage = (date: Date, includeTime: boolean) =>
  includeTime ? format(date, "yyyy-MM-dd'T'HH:mm") : format(date, "yyyy-MM-dd");

const applyTimeToDate = (date: Date, time: string) => {
  const [hours, minutes] = time.split(":").map((segment) => Number.parseInt(segment, 10));
  const next = new Date(date);
  next.setHours(Number.isFinite(hours) ? hours : 0);
  next.setMinutes(Number.isFinite(minutes) ? minutes : 0);
  next.setSeconds(0);
  next.setMilliseconds(0);
  return next;
};

// Candidate formats tried (in order) when parsing a manually typed date.
const DATE_FORMATS = [
  "yyyy-MM-dd",
  "MM/dd/yyyy",
  "M/d/yyyy",
  "MM-dd-yyyy",
  "yyyy/MM/dd",
  "MMMM d, yyyy",
  "MMM d, yyyy",
  "MMMM d yyyy",
  "MMM d yyyy",
  "d MMMM yyyy",
  "d MMM yyyy",
];

const DATE_TIME_FORMATS = [
  "yyyy-MM-dd HH:mm",
  "yyyy-MM-dd'T'HH:mm",
  "MM/dd/yyyy HH:mm",
  "M/d/yyyy HH:mm",
  "MM/dd/yyyy h:mm a",
  "M/d/yyyy h:mm a",
  "MMMM d, yyyy h:mm a",
  "MMM d, yyyy h:mm a",
  "MMMM d, yyyy HH:mm",
  "MMM d, yyyy HH:mm",
];

// Parse a free-form typed string into a Date, trying known formats first and
// falling back to native parsing. Fields absent from a matched format (e.g. the
// time when only a date is typed) inherit from `reference`.
const parseManualDate = (input: string, includeTime: boolean, reference: Date): Date | null => {
  const trimmed = input.trim();
  if (!trimmed) {
    return null;
  }
  const formats = includeTime ? [...DATE_TIME_FORMATS, ...DATE_FORMATS] : DATE_FORMATS;
  for (const fmt of formats) {
    const parsed = parse(trimmed, fmt, reference);
    if (isValid(parsed)) {
      return parsed;
    }
  }
  const native = new Date(trimmed);
  return isValid(native) ? native : null;
};

export const DateTimePicker = ({
  id,
  value,
  onChange,
  disabled = false,
  placeholder,
  clearLabel,
  calendarProps,
  includeTime = true,
}: DateTimePickerProps) => {
  const { t } = useTranslation(["dates", "common"]);
  const { user } = useAuth();
  const selectedDate = value
    ? includeTime
      ? new Date(value)
      : (() => {
          // Parse date-only string as local date to avoid timezone issues
          const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
          if (match) {
            return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
          }
          return new Date(value);
        })()
    : undefined;
  const timeValue = selectedDate ? format(selectedDate, "HH:mm") : "";
  const defaultPlaceholder = includeTime ? t("picker.pickDateTime") : t("picker.pickDate");

  // Human-friendly representation of the current value for the manual-entry field.
  const displayValue = selectedDate
    ? format(selectedDate, includeTime ? "MMM d, yyyy h:mm a" : "MMM d, yyyy")
    : "";
  const [inputValue, setInputValue] = React.useState(displayValue);
  // Keep the text field in sync whenever the committed value changes.
  React.useEffect(() => {
    setInputValue(displayValue);
  }, [displayValue]);

  const [open, setOpen] = React.useState(false);

  // The month the calendar is displaying. Controlled so it follows both the
  // month/year dropdowns and the selected date (e.g. when typed manually).
  const [visibleMonth, setVisibleMonth] = React.useState(() => selectedDate ?? new Date());
  const selectedMonthKey = selectedDate
    ? `${selectedDate.getFullYear()}-${selectedDate.getMonth()}`
    : null;
  // biome-ignore lint/correctness/useExhaustiveDependencies: keyed on selectedMonthKey so we only jump when the selected month changes, not on every render (selectedDate is a fresh object each render).
  React.useEffect(() => {
    if (selectedDate) {
      setVisibleMonth(selectedDate);
    }
  }, [selectedMonthKey]);

  const resolvedWeekStartsOn = (calendarProps?.weekStartsOn ?? user?.week_starts_on ?? 0) as
    | 0
    | 1
    | 2
    | 3
    | 4
    | 5
    | 6;
  const mergedCalendarProps = React.useMemo(() => {
    const currentYear = new Date().getFullYear();
    return {
      captionLayout: "dropdown" as const,
      startMonth: new Date(currentYear - 120, 0),
      endMonth: new Date(currentYear + 10, 11),
      ...(calendarProps ?? {}),
      weekStartsOn: resolvedWeekStartsOn,
    };
  }, [calendarProps, resolvedWeekStartsOn]);

  const handleSelectDate = (date: Date | undefined) => {
    if (!date) {
      onChange("");
      return;
    }
    if (includeTime) {
      const baseTime = selectedDate ? format(selectedDate, "HH:mm") : format(new Date(), "HH:mm");
      const next = applyTimeToDate(date, baseTime);
      onChange(formatForStorage(next, includeTime));
    } else {
      onChange(formatForStorage(date, includeTime));
    }
  };

  const handleTimeChange = (nextTime: string) => {
    if (!selectedDate) {
      return;
    }
    const next = applyTimeToDate(selectedDate, nextTime);
    onChange(formatForStorage(next, includeTime));
  };

  // `allowClear` distinguishes an explicit commit (Enter) from an incidental
  // blur. On blur we must NOT emit onChange("") for an empty field: the browser
  // fires blur (mousedown) before a calendar day's click (mouseup), so clearing
  // here would send a spurious "clear" mutation right before the real "set".
  // Clearing is intentional only via Enter or the Clear button.
  const commitInput = (allowClear: boolean) => {
    const trimmed = inputValue.trim();
    if (!trimmed) {
      if (allowClear) {
        if (value) {
          onChange("");
        }
      } else {
        setInputValue(displayValue);
      }
      return;
    }
    const parsed = parseManualDate(trimmed, includeTime, selectedDate ?? new Date());
    if (!parsed) {
      // Couldn't parse — revert to the last valid value.
      setInputValue(displayValue);
      return;
    }
    const next = formatForStorage(parsed, includeTime);
    if (next === value) {
      // No change — just normalize the text to the canonical display.
      setInputValue(displayValue);
    } else {
      onChange(next);
    }
  };

  const handleClear = () => {
    onChange("");
  };

  const handleOpenChange = (next: boolean) => {
    if (next) {
      // On open, jump the calendar back to the selected date and reset the text
      // field — closing via Escape unmounts the input without firing onBlur, so
      // any uncommitted text would otherwise linger until the value changes.
      setVisibleMonth(selectedDate ?? new Date());
      setInputValue(displayValue);
    }
    setOpen(next);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          data-empty={!selectedDate}
          className={cn(
            "inline-flex w-full items-center justify-start gap-2 text-left font-normal data-[empty=true]:text-muted-foreground",
            "min-h-10"
          )}
        >
          <CalendarIcon className="h-4 w-4" />
          {selectedDate ? (
            format(selectedDate, includeTime ? "PP p" : "PP")
          ) : (
            <span>{placeholder ?? defaultPlaceholder}</span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <div className="border-b p-3">
          <Input
            id={id ? `${id}-input` : undefined}
            type="text"
            value={inputValue}
            placeholder={t("picker.typeDate")}
            aria-label={t("picker.typeDate")}
            disabled={disabled}
            onChange={(event) => setInputValue(event.target.value)}
            onBlur={() => commitInput(false)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitInput(true);
              }
            }}
          />
        </div>
        <Calendar
          {...mergedCalendarProps}
          mode="single"
          selected={selectedDate}
          month={visibleMonth}
          onMonthChange={setVisibleMonth}
          onSelect={handleSelectDate}
          className="w-75 p-3"
        />
        <div className="flex items-end gap-3 border-t bg-muted/30 p-3">
          {includeTime && (
            <div className="flex flex-1 flex-col gap-1">
              <label
                htmlFor={`${id ?? "datetime"}-time`}
                className="font-medium text-muted-foreground text-xs"
              >
                {t("picker.time")}
              </label>
              <Input
                id={`${id ?? "datetime"}-time`}
                type="time"
                step={300}
                value={timeValue}
                onChange={(event) => handleTimeChange(event.target.value)}
                disabled={!selectedDate || disabled}
              />
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-muted-foreground text-xs"
            onClick={handleClear}
            disabled={!selectedDate || disabled}
          >
            {clearLabel ?? t("common:clear")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
