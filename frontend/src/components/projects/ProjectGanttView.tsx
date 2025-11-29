import { useMemo, useState } from "react";
import { addDays, differenceInCalendarDays, format, parseISO, startOfWeek } from "date-fns";
import { ArrowLeft, ArrowRight } from "lucide-react";

import type { Task } from "@/types/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type ProjectGanttViewProps = {
  tasks: Task[];
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
};

type NormalizedRange = {
  task: Task;
  start: Date;
  end: Date;
};

const WINDOW_OPTIONS = [7, 14, 21, 28];
const DAY_COLUMN_WIDTH = 90;
const NAME_COLUMN_WIDTH = 180;

const parseDate = (value?: string | null): Date | null => {
  if (!value) {
    return null;
  }
  const parsed = parseISO(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed;
};

const normalizeRanges = (tasks: Task[]): NormalizedRange[] =>
  tasks
    .map((task) => {
      const start =
        parseDate(task.start_date) ?? parseDate(task.due_date) ?? parseISO(task.created_at);
      const end = parseDate(task.due_date) ?? start;
      const safeStart = start ?? new Date();
      const safeEnd = end ?? safeStart;
      if (safeEnd < safeStart) {
        return { task, start: safeEnd, end: safeStart };
      }
      return { task, start: safeStart, end: safeEnd };
    })
    .sort((a, b) => a.start.getTime() - b.start.getTime());

export const ProjectGanttView = ({ tasks, canOpenTask, onTaskClick }: ProjectGanttViewProps) => {
  const [visibleStart, setVisibleStart] = useState(() =>
    startOfWeek(new Date(), { weekStartsOn: 0 })
  );
  const [daysVisible, setDaysVisible] = useState(14);
  const rows = useMemo(() => normalizeRanges(tasks), [tasks]);
  const days = useMemo(
    () => Array.from({ length: daysVisible }, (_, index) => addDays(visibleStart, index)),
    [visibleStart, daysVisible]
  );
  const timelineWidth = daysVisible * DAY_COLUMN_WIDTH;

  const handleShift = (direction: "back" | "forward") => {
    setVisibleStart((current) =>
      addDays(current, direction === "back" ? -daysVisible : daysVisible)
    );
  };

  return (
    <div className="space-y-4 rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div>
          <h3 className="text-lg font-semibold">Timeline</h3>
          <p className="text-sm text-muted-foreground">
            Plan start and due dates over the next few weeks.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={String(daysVisible)}
            onValueChange={(value) => setDaysVisible(Number(value))}
          >
            <SelectTrigger className="w-28 text-xs">
              <SelectValue placeholder="Window">{daysVisible} days</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {WINDOW_OPTIONS.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {option} days
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={() => handleShift("back")}
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="sr-only">Show previous weeks</span>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={() => handleShift("forward")}
          >
            <ArrowRight className="h-4 w-4" />
            <span className="sr-only">Show next weeks</span>
          </Button>
        </div>
      </div>
      <div className="space-y-2 overflow-x-auto overflow-visible">
        <div
          className="min-w-[720px] sm:min-w-0"
          style={{ minWidth: NAME_COLUMN_WIDTH + timelineWidth }}
        >
          <div
            className="grid text-[11px] font-semibold uppercase text-muted-foreground sm:text-xs"
            style={{
              gridTemplateColumns: `${NAME_COLUMN_WIDTH}px minmax(${timelineWidth}px, 1fr)`,
            }}
          >
            <div className="border-r border-border bg-card px-3 py-2">Task</div>
            <div
              className="grid bg-background/80"
              style={{
                gridTemplateColumns: `repeat(${daysVisible}, minmax(${DAY_COLUMN_WIDTH}px, 1fr))`,
              }}
            >
              {days.map((day) => (
                <div
                  key={day.toISOString()}
                  className="border-l border-border px-2 py-2 text-center"
                >
                  <div>{format(day, "MMM d")}</div>
                  <div className="text-[10px] text-muted-foreground">{format(day, "EEE")}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="divide-y border-t text-xs sm:text-sm">
            {rows.length === 0 ? (
              <p className="px-3 py-6 text-sm text-muted-foreground">No tasks to display.</p>
            ) : (
              rows.map(({ task, start, end }) => {
                const startOffset = differenceInCalendarDays(start, visibleStart);
                const endOffset = differenceInCalendarDays(end, visibleStart) + 1;
                const clampedStart = Math.max(0, startOffset);
                const clampedEnd = Math.min(daysVisible, endOffset);
                const isOutOfRange = clampedEnd <= 0 || clampedStart >= daysVisible;
                const barWidth = Math.max(clampedEnd - clampedStart, 0);
                const category = task.task_status.category;
                const isDone = category === "done";
                const isInProgress = category === "in_progress";
                return (
                  <div
                    key={task.id}
                    className="grid min-h-16"
                    style={{
                      gridTemplateColumns: `${NAME_COLUMN_WIDTH}px minmax(${timelineWidth}px, 1fr)`,
                    }}
                  >
                    <div className="border-r border-border bg-card px-3 py-3 flex flex-col justify-center">
                      <p className="font-medium">{task.title}</p>
                      <p className="text-[11px] text-muted-foreground sm:text-xs">
                        {start.toLocaleDateString()} → {end.toLocaleDateString()}
                      </p>
                    </div>
                    <div
                      className="grid border-l"
                      style={{
                        gridTemplateColumns: `repeat(${daysVisible}, minmax(${DAY_COLUMN_WIDTH}px, 1fr))`,
                      }}
                    >
                      {!isOutOfRange && barWidth > 0 ? (
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <button
                                type="button"
                                className={cn(
                                  "my-2 flex h-12 items-center gap-2 rounded-full px-3 text-xs font-medium text-white shadow-sm",
                                  isDone
                                    ? "bg-muted text-muted-foreground"
                                    : isInProgress
                                      ? canOpenTask
                                        ? "bg-emerald-600 hover:bg-emerald-500"
                                        : "bg-emerald-600/70 text-emerald-50"
                                      : canOpenTask
                                        ? "bg-primary hover:bg-primary/90"
                                        : "bg-muted opacity-70"
                                )}
                                style={{
                                  gridColumn: `${clampedStart + 1} / ${clampedEnd + 1}`,
                                }}
                                onClick={() => {
                                  if (!canOpenTask) {
                                    return;
                                  }
                                  onTaskClick(task.id);
                                }}
                                disabled={!canOpenTask}
                              >
                                <span className="truncate">{task.title}</span>
                              </button>
                            </TooltipTrigger>
                            <TooltipContent side="top">{task.title}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : (
                        <p
                          className="px-3 py-3 text-xs text-muted-foreground"
                          style={{ gridColumn: `1 / ${daysVisible + 1}` }}
                        >
                          Outside current range
                        </p>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
