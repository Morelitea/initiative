import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { format, parseISO, isToday, isBefore, startOfDay } from "date-fns";
import { CalendarClock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuildPath } from "@/lib/guildUrl";
import type { Task } from "@/types/api";

interface UpcomingTasksListProps {
  tasks: Task[];
  isLoading?: boolean;
}

function getDueBadgeVariant(
  dueDate: string | null | undefined
): "destructive" | "default" | "secondary" | null {
  if (!dueDate) return null;
  const due = parseISO(dueDate);
  const now = new Date();
  if (isBefore(due, startOfDay(now))) return "destructive";
  if (isToday(due)) return "default";
  return "secondary";
}

function getDueBadgeLabelKey(dueDate: string | null | undefined): string | null {
  if (!dueDate) return null;
  const due = parseISO(dueDate);
  const now = new Date();
  if (isBefore(due, startOfDay(now))) return "upcomingTasks.overdue";
  if (isToday(due)) return "upcomingTasks.today";
  return "upcomingTasks.upcoming";
}

const priorityOrder: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  none: 4,
};

export function UpcomingTasksList({ tasks, isLoading }: UpcomingTasksListProps) {
  const { t } = useTranslation("dashboard");
  const gp = useGuildPath();

  const sorted = [...tasks].sort((a, b) => {
    // Overdue first, then by due date, then by priority
    const aDate = a.due_date ? parseISO(a.due_date).getTime() : Infinity;
    const bDate = b.due_date ? parseISO(b.due_date).getTime() : Infinity;
    if (aDate !== bDate) return aDate - bDate;
    return (priorityOrder[a.priority] ?? 4) - (priorityOrder[b.priority] ?? 4);
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("upcomingTasks.title")}</CardTitle>
        <CardDescription>{t("upcomingTasks.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-5 w-16" />
              </div>
            ))}
          </div>
        ) : sorted.length === 0 ? (
          <div className="text-muted-foreground flex h-[200px] items-center justify-center text-sm">
            <div className="flex flex-col items-center gap-2">
              <CalendarClock className="h-8 w-8 opacity-50" />
              <span>{t("upcomingTasks.noTasks")}</span>
            </div>
          </div>
        ) : (
          <div className="space-y-1">
            {sorted.map((task) => {
              const badgeVariant = getDueBadgeVariant(task.due_date);
              const badgeLabelKey = getDueBadgeLabelKey(task.due_date);
              return (
                <Link
                  key={task.id}
                  to={gp(`/tasks/${task.id}`)}
                  className="hover:bg-accent flex items-center gap-3 rounded-md px-2 py-2 transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{task.title}</p>
                    {task.project_name && (
                      <p className="text-muted-foreground truncate text-xs">{task.project_name}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {task.due_date && (
                      <span className="text-muted-foreground text-xs">
                        {format(parseISO(task.due_date), "MMM d")}
                      </span>
                    )}
                    {badgeVariant && badgeLabelKey && (
                      <Badge variant={badgeVariant} className="text-xs">
                        {t(
                          badgeLabelKey as
                            | "upcomingTasks.overdue"
                            | "upcomingTasks.today"
                            | "upcomingTasks.upcoming"
                        )}
                      </Badge>
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
