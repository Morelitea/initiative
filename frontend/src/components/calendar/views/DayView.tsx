import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { UnreadDot } from "@/components/notifications/UnreadDot";
import { cn } from "@/lib/utils";

import {
  buildEntriesByDate,
  type CalendarGridViewProps,
  DayColumn,
  dateKey,
  HourGutter,
  kindLabelKey,
} from "./shared";

export function DayView({
  entries,
  focusDate,
  onEntryClick,
  onSlotClick,
  dndEnabled = false,
}: CalendarGridViewProps) {
  const { t } = useTranslation(["common"]);

  const entriesByDate = useMemo(() => buildEntriesByDate(entries), [entries]);
  const dayEntries = entriesByDate.get(dateKey(focusDate)) ?? [];
  const allDayEntries = dayEntries.filter((e) => e.allDay);

  return (
    <div className="space-y-3">
      {/* All-day section */}
      {allDayEntries.length > 0 ? (
        <div className="space-y-1 border-b pb-3">
          <p className="font-semibold text-muted-foreground text-xs uppercase">
            {t("common:calendar.allDay")}
          </p>
          {allDayEntries.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left font-medium text-[11px] text-white transition-colors",
                onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
              )}
              style={{
                backgroundColor: entry.color || "var(--primary)",
              }}
              onClick={() => onEntryClick?.(entry)}
            >
              {entry.kind && (
                <span className="shrink-0 rounded-sm bg-white/25 px-1 font-semibold text-[9px] uppercase">
                  {t(`common:${kindLabelKey(entry.kind)}`)}
                </span>
              )}
              <span className="truncate">{entry.title}</span>
              {entry.unread ? <UnreadDot className="ml-auto ring-1 ring-background" /> : null}
            </button>
          ))}
        </div>
      ) : null}

      {/* Hour grid with positioned timed blocks */}
      <div className="grid max-h-[600px] grid-cols-[60px_1fr] overflow-y-auto">
        <HourGutter className="pr-3" />
        <DayColumn
          day={focusDate}
          entries={dayEntries.filter((e) => !e.allDay)}
          onEntryClick={onEntryClick}
          onSlotClick={onSlotClick}
          dndEnabled={dndEnabled}
        />
      </div>
    </div>
  );
}
