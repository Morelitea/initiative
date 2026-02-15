import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  parseISO,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { Calendar, ChevronLeft, ChevronRight, Clock } from "lucide-react";

import type { Task } from "@/types/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

type ProjectCalendarViewProps = {
  tasks: Task[];
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
};

type CalendarEntry = {
  task: Task;
  type: "start" | "due";
};

const WEEKDAY_KEYS = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
] as const;

const formatDateKey = (value: string) => {
  const date = parseISO(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return format(date, "yyyy-MM-dd");
};

export const ProjectCalendarView = ({
  tasks,
  canOpenTask,
  onTaskClick,
}: ProjectCalendarViewProps) => {
  const { t, i18n } = useTranslation(["projects", "dates"]);
  const { user } = useAuth();
  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;
  const [visibleMonth, setVisibleMonth] = useState(() => startOfMonth(new Date()));

  const calendarDays = useMemo(() => {
    const start = startOfWeek(startOfMonth(visibleMonth), { weekStartsOn });
    const end = endOfWeek(endOfMonth(visibleMonth), { weekStartsOn });
    return eachDayOfInterval({ start, end });
  }, [visibleMonth, weekStartsOn]);

  const weekdayLabels = useMemo(() => {
    const labels = WEEKDAY_KEYS.map((key) => t(`dates:weekdaysShort.${key}`));
    return labels.slice(weekStartsOn).concat(labels.slice(0, weekStartsOn));
  }, [weekStartsOn, t]);

  const entriesByDate = useMemo(() => {
    const map = new Map<string, CalendarEntry[]>();
    tasks.forEach((task) => {
      if (task.start_date) {
        const key = formatDateKey(task.start_date);
        if (key) {
          const next = map.get(key) ?? [];
          next.push({ task, type: "start" });
          map.set(key, next);
        }
      }
      if (task.due_date) {
        const key = formatDateKey(task.due_date);
        if (key) {
          const next = map.get(key) ?? [];
          next.push({ task, type: "due" });
          map.set(key, next);
        }
      }
    });
    return map;
  }, [tasks]);

  const handleMonthChange = (direction: "prev" | "next") => {
    setVisibleMonth((current) => addMonths(current, direction === "prev" ? -1 : 1));
  };

  return (
    <div className="bg-card space-y-4 rounded-xl border p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex items-center gap-2">
          <Calendar className="text-muted-foreground h-5 w-5" />
          <div>
            <p className="text-lg font-semibold capitalize">
              {visibleMonth.toLocaleDateString(i18n.language, { month: "long", year: "numeric" })}
            </p>
            <p className="text-muted-foreground text-sm">{t("calendarView.subtitle")}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={() => handleMonthChange("prev")}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">{t("calendarView.previousMonth")}</span>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={() => handleMonthChange("next")}
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">{t("calendarView.nextMonth")}</span>
          </Button>
        </div>
      </div>
      <div className="space-y-2 overflow-x-auto sm:overflow-visible">
        <div className="min-w-[700px] sm:min-w-0">
          <div className="text-muted-foreground grid grid-cols-7 text-center text-[11px] font-semibold uppercase sm:text-xs">
            {weekdayLabels.map((day) => (
              <div key={day} className="py-2">
                {day}
              </div>
            ))}
          </div>
          <div className="bg-border grid grid-cols-7 gap-px rounded-lg border">
            {calendarDays.map((day) => {
              const key = format(day, "yyyy-MM-dd");
              const entries = entriesByDate.get(key) ?? [];
              return (
                <div
                  key={key}
                  className={cn(
                    "bg-card flex min-h-[110px] flex-col gap-1 p-2 text-left text-xs sm:min-h-[130px]",
                    !isSameMonth(day, visibleMonth) && "bg-muted/40 text-muted-foreground",
                    isToday(day) && "ring-primary/80 ring-2"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium sm:text-base">{format(day, "d")}</span>
                    {isToday(day) ? (
                      <span className="text-primary text-[10px] font-semibold uppercase">
                        {t("calendarView.today")}
                      </span>
                    ) : null}
                  </div>
                  <div className="space-y-1">
                    {entries.slice(0, 3).map((entry) => (
                      <button
                        type="button"
                        key={`${entry.task.id}-${entry.type}`}
                        className={cn(
                          "flex w-full items-center gap-1 rounded-md border px-2 py-1 text-left text-[11px]",
                          entry.type === "start"
                            ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-900/20"
                            : "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/40 dark:bg-amber-900/20",
                          canOpenTask ? "hover:bg-accent" : "cursor-not-allowed opacity-60"
                        )}
                        onClick={() => {
                          if (!canOpenTask) {
                            return;
                          }
                          onTaskClick(entry.task.id);
                        }}
                        disabled={!canOpenTask}
                      >
                        <Clock className="h-3 w-3 shrink-0" aria-hidden="true" />
                        <span className="truncate">{entry.task.title}</span>
                        <span className="hidden shrink-0 text-[10px] uppercase lg:inline">
                          {entry.type === "start" ? t("calendarView.start") : t("calendarView.due")}
                        </span>
                      </button>
                    ))}
                    {entries.length > 3 ? (
                      <p className="text-muted-foreground text-[10px]">
                        {t("calendarView.more", { count: entries.length - 3 })}
                      </p>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
