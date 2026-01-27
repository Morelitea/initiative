import { memo, useMemo } from "react";
import { formatDistance, formatDate, isPast } from "date-fns";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type DateCellProps = {
  date: string | null | undefined;
  isPastVariant?: "primary" | "destructive";
  isDone?: boolean;
};

/**
 * Memoized date cell to avoid re-computing formatDistance on every render
 */
export const DateCell = memo(({ date, isPastVariant, isDone }: DateCellProps) => {
  const dateObj = useMemo(() => (date ? new Date(date) : null), [date]);
  const isPastDate = useMemo(() => (dateObj ? isPast(dateObj) : false), [dateObj]);
  const relativeDate = useMemo(
    () => (dateObj ? formatDistance(dateObj, new Date(), { addSuffix: true }) : null),
    [dateObj]
  );
  const formattedDate = useMemo(
    () => (dateObj ? formatDate(dateObj, "PPPP 'at' pp") : null),
    [dateObj]
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
