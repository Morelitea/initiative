import { memo, useMemo } from "react";
import { formatDistance, isPast } from "date-fns";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDateLocale } from "@/hooks/useDateLocale";

type DateCellProps = {
  date: string | null | undefined;
  isPastVariant?: "primary" | "destructive";
  isDone?: boolean;
};

/**
 * Memoized date cell to avoid re-computing formatDistance on every render
 */
export const DateCell = memo(({ date, isPastVariant, isDone }: DateCellProps) => {
  const dateLocale = useDateLocale();
  const dateObj = useMemo(() => (date ? new Date(date) : null), [date]);
  const isPastDate = useMemo(() => (dateObj ? isPast(dateObj) : false), [dateObj]);
  const relativeDate = useMemo(
    () =>
      dateObj ? formatDistance(dateObj, new Date(), { addSuffix: true, locale: dateLocale }) : null,
    [dateObj, dateLocale]
  );
  const formattedDate = useMemo(
    () =>
      dateObj
        ? dateObj.toLocaleString(dateLocale.code, {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
          })
        : null,
    [dateObj, dateLocale]
  );

  if (!relativeDate) {
    return <span className="text-muted-foreground">—</span>;
  }

  const className = (() => {
    if (!isPastDate || !isPastVariant) {
      return "min-w-30 text-muted-foreground";
    }
    // Past due and done = green (success)
    if (isPastVariant === "destructive" && isDone) {
      return "min-w-30 text-green-600 dark:text-green-400";
    }
    // Past due and not done = red (destructive)
    if (isPastVariant === "destructive") {
      return "min-w-30 text-destructive";
    }
    // Past start date = primary
    return "min-w-30 text-primary";
  })();

  return (
    <div className={className}>
      <Tooltip>
        <TooltipTrigger>{relativeDate}</TooltipTrigger>
        <TooltipContent>{formattedDate}</TooltipContent>
      </Tooltip>
    </div>
  );
});

DateCell.displayName = "DateCell";
