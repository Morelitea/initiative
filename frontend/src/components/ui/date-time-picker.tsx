import { format } from "date-fns";
import { Calendar as CalendarIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAuth } from "@/hooks/useAuth";

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

export const DateTimePicker = ({
  id,
  value,
  onChange,
  disabled = false,
  placeholder,
  clearLabel = "Clear",
  calendarProps,
  includeTime = true,
}: DateTimePickerProps) => {
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
  const defaultPlaceholder = includeTime ? "Pick a date and time" : "Pick a date";
  const resolvedWeekStartsOn = (calendarProps?.weekStartsOn ?? user?.week_starts_on ?? 0) as
    | 0
    | 1
    | 2
    | 3
    | 4
    | 5
    | 6;
  const mergedCalendarProps = {
    ...(calendarProps ?? {}),
    weekStartsOn: resolvedWeekStartsOn,
  };

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

  const handleClear = () => {
    onChange("");
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          data-empty={!selectedDate}
          className={cn(
            "data-[empty=true]:text-muted-foreground inline-flex w-full items-center justify-start gap-2 text-left font-normal",
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
        <Calendar
          {...mergedCalendarProps}
          mode="single"
          selected={selectedDate}
          onSelect={handleSelectDate}
          autoFocus
          className="w-75 p-3"
        />
        <div className="bg-muted/30 flex items-end gap-3 border-t p-3">
          {includeTime && (
            <div className="flex flex-1 flex-col gap-1">
              <label
                htmlFor={`${id ?? "datetime"}-time`}
                className="text-muted-foreground text-xs font-medium"
              >
                Time
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
            {clearLabel}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
