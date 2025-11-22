import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
} from "lucide-react";
import {
  DayFlag,
  DayPicker,
  SelectionState,
  UI,
  type CustomComponents,
} from "react-day-picker";

import { cn } from "../../lib/utils";
import { buttonVariants } from "./button";

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

type ChevronProps = Parameters<CustomComponents["Chevron"]>[0];

const CalendarChevron = ({
  orientation = "right",
  className,
  size,
  disabled,
}: ChevronProps) => {
  const Icon =
    orientation === "left"
      ? ChevronLeft
      : orientation === "right"
      ? ChevronRight
      : orientation === "up"
      ? ChevronUp
      : ChevronDown;
  return (
    <Icon
      className={cn(disabled && "opacity-40", className)}
      size={size}
      aria-hidden
      focusable="false"
    />
  );
};

export const Calendar = ({
  className,
  classNames,
  showOutsideDays = true,
  components,
  ...props
}: CalendarProps) => {
  const navButtonBase = cn(
    buttonVariants({ variant: "outline" }),
    "h-7 w-7 bg-transparent p-0 opacity-50 hover:opacity-100"
  );

  const defaultClassNames = {
    [UI.Nav]:
      "absolute inset-x-3 top-3 z-10 flex sm:p-2 items-center justify-between gap-2",
    [UI.Months]: "flex flex-col sm:flex-row space-y-4 sm:p-2 sm:space-y-0",
    [UI.Month]: "space-y-4",
    [UI.MonthCaption]: "text-center text-sm font-medium",
    [UI.CaptionLabel]: "text-sm font-medium",
    [UI.PreviousMonthButton]: navButtonBase,
    [UI.NextMonthButton]: navButtonBase,
    [UI.MonthGrid]: "w-full border-collapse space-y-1",
    [UI.Weekdays]: "flex",
    [UI.Weekday]:
      "text-muted-foreground rounded-md w-9 font-normal text-[0.8rem]",
    [UI.Week]: "flex w-full mt-2",
    [UI.Day]:
      "h-9 w-9 text-center text-sm p-0 relative [&:has([aria-selected].day-outside)]:bg-accent/50 [&:has([aria-selected])]:bg-accent first:[&:has([aria-selected])]:rounded-l-md last:[&:has([aria-selected])]:rounded-r-md focus-within:relative focus-within:z-20",
    [UI.DayButton]: cn(
      buttonVariants({ variant: "ghost" }),
      "h-9 w-9 p-0 font-normal aria-selected:opacity-100"
    ),
    [SelectionState.range_start]: "day-range-start",
    [SelectionState.range_end]: "day-range-end",
    [SelectionState.selected]:
      "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground focus:bg-primary focus:text-primary-foreground",
    [SelectionState.range_middle]:
      "aria-selected:bg-accent aria-selected:text-accent-foreground",
    [DayFlag.today]: "bg-accent text-accent-foreground",
    [DayFlag.outside]: "text-muted-foreground opacity-50",
    [DayFlag.disabled]: "text-muted-foreground opacity-50",
    [DayFlag.hidden]: "invisible",
  } satisfies Partial<Record<UI | SelectionState | DayFlag, string>>;

  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("relative p-3", className)}
      classNames={{
        ...defaultClassNames,
        ...classNames,
      }}
      components={{
        Chevron: CalendarChevron,
        ...components,
      }}
      {...props}
    />
  );
};

Calendar.displayName = "Calendar";
