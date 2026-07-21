import { Link } from "@tanstack/react-router";
import { format, isBefore, isToday, parseISO, startOfDay } from "date-fns";
import { CalendarClock } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuildPath } from "@/lib/guildUrl";
import { priorityRank } from "@/lib/sorting";

interface UpcomingTasksListProps {
  tasks: TaskListRead[];
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

export function UpcomingTasksList({ tasks, isLoading }: UpcomingTasksListProps) {
  const { t } = useTranslation("dashboard");
  const gp = useGuildPath();

  const sorted = [...tasks].sort((a, b) => {
    // Overdue first, then by due date, then by priority
    const aDate = a.due_date ? parseISO(a.due_date).getTime() : Infinity;
    const bDate = b.due_date ? parseISO(b.due_date).getTime() : Infinity;
    if (aDate !== bDate) return aDate - bDate;
    // Higher priority first (urgent → low) as the due-date tiebreaker.
    return (priorityRank[b.priority] ?? -1) - (priorityRank[a.priority] ?? -1);
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
              // biome-ignore lint/suspicious/noArrayIndexKey: This is a static skeleton list, so using index as key is fine.
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-5 w-16" />
              </div>
            ))}
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex h-50 items-center justify-center text-muted-foreground text-sm">
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
                  className="flex items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-accent"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-sm">{task.title}</p>
                    {task.project_name && (
                      <p className="truncate text-muted-foreground text-xs">{task.project_name}</p>
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
