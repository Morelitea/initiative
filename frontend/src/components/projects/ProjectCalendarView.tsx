import { useMemo, useState } from "react";
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

type ProjectCalendarViewProps = {
  tasks: Task[];
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
};

type CalendarEntry = {
  task: Task;
  type: "start" | "due";
};

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
  const [visibleMonth, setVisibleMonth] = useState(() => startOfMonth(new Date()));

  const calendarDays = useMemo(() => {
    const start = startOfWeek(startOfMonth(visibleMonth), { weekStartsOn: 0 });
    const end = endOfWeek(endOfMonth(visibleMonth), { weekStartsOn: 0 });
    return eachDayOfInterval({ start, end });
  }, [visibleMonth]);

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
    <div className="space-y-4 rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex items-center gap-2">
          <Calendar className="h-5 w-5 text-muted-foreground" />
          <div>
            <p className="text-lg font-semibold">{format(visibleMonth, "MMMM yyyy")}</p>
            <p className="text-sm text-muted-foreground">
              See task start and due dates at a glance.
            </p>
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
            <span className="sr-only">Previous month</span>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={() => handleMonthChange("next")}
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">Next month</span>
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-7 text-center text-xs font-semibold uppercase text-muted-foreground">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
          <div key={day} className="py-2">
            {day}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-px rounded-lg border bg-border">
        {calendarDays.map((day) => {
          const key = format(day, "yyyy-MM-dd");
          const entries = entriesByDate.get(key) ?? [];
          return (
            <div
              key={key}
              className={cn(
                "flex min-h-[120px] flex-col gap-1 bg-card p-2 text-left text-xs",
                !isSameMonth(day, visibleMonth) && "bg-muted/40 text-muted-foreground",
                isToday(day) && "ring-2 ring-primary/80"
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{format(day, "d")}</span>
                {isToday(day) ? (
                  <span className="text-[10px] font-semibold uppercase text-primary">Today</span>
                ) : null}
              </div>
              <div className="space-y-1">
                {entries.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">No tasks</p>
                ) : (
                  entries.slice(0, 3).map((entry) => (
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
                      <span className="shrink-0 text-[10px] uppercase">
                        {entry.type === "start" ? "Start" : "Due"}
                      </span>
                    </button>
                  ))
                )}
                {entries.length > 3 ? (
                  <p className="text-[10px] text-muted-foreground">+{entries.length - 3} more</p>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
