import { Link } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";

import { summarizeRecurrence } from "@/lib/recurrence";
import type { TranslateFn } from "@/types/i18n";
import { guildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { SortIcon } from "@/components/SortIcon";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { TaskPrioritySelector } from "@/components/tasks/TaskPrioritySelector";
import { TaskStatusSelector } from "@/components/tasks/TaskStatusSelector";
import { TagBadge } from "@/components/tags/TagBadge";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import type { Project, ProjectTaskStatus, Task, TaskStatusCategory } from "@/types/api";

interface GlobalTaskColumnsOptions {
  activeGuildId: number | null;
  isUpdatingTaskStatus: boolean;
  changeTaskStatus: (task: Task, category: TaskStatusCategory) => Promise<void>;
  changeTaskStatusById: (task: Task, statusId: number) => Promise<void>;
  fetchProjectStatuses: (projectId: number, guildId: number | null) => Promise<ProjectTaskStatus[]>;
  projectStatusCache: React.MutableRefObject<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >;
  projectsById: Record<number, Project>;
  t: TranslateFn;
  showAssignees?: boolean;
}

export function globalTaskColumns({
  activeGuildId,
  isUpdatingTaskStatus,
  changeTaskStatus,
  changeTaskStatusById,
  fetchProjectStatuses,
  projectStatusCache,
  projectsById,
  t,
  showAssignees = false,
}: GlobalTaskColumnsOptions): ColumnDef<Task>[] {
  const guildDefaultLabel = t("myTasks.noGuild");
  const getGuildGroupLabel = (task: Task) => task.guild_name ?? guildDefaultLabel;

  const taskGuildPath = (task: Task, path: string) => {
    const guildId = task.guild_id ?? activeGuildId;
    return guildId ? guildPath(guildId, path) : path;
  };

  return [
    {
      id: "date group",
      accessorFn: (task) => getTaskDateStatus(task.start_date, task.due_date),
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.dateWindow")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ getValue }) => (
        <span className="text-base font-medium">
          {getTaskDateStatusLabel(getValue<string>(), t)}
        </span>
      ),
      enableHiding: true,
      enableSorting: true,
      sortingFn: "alphanumeric",
    },
    {
      id: "guild",
      accessorFn: (task) => getGuildGroupLabel(task),
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.guild")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ getValue }) => <span className="text-base font-medium">{getValue<string>()}</span>,
      enableHiding: true,
      enableSorting: true,
      sortingFn: "alphanumeric",
    },
    {
      id: "completed",
      header: () => <span className="font-medium">{t("columns.done")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <Checkbox
            checked={task.task_status.category === "done"}
            onCheckedChange={(value) => {
              if (isUpdatingTaskStatus) {
                return;
              }
              const targetCategory: TaskStatusCategory = value ? "done" : "in_progress";
              void changeTaskStatus(task, targetCategory);
            }}
            className="h-6 w-6"
            disabled={isUpdatingTaskStatus}
            aria-label={
              task.task_status.category === "done"
                ? t("checkbox.markInProgress")
                : t("checkbox.markDone")
            }
          />
        );
      },
      enableSorting: false,
      size: 64,
      enableHiding: false,
    },
    {
      accessorKey: "title",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.task")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        const recurrenceSummary = task.recurrence
          ? summarizeRecurrence(
              task.recurrence,
              {
                referenceDate: task.start_date || task.due_date,
                strategy: task.recurrence_strategy,
              },
              t
            )
          : null;
        return (
          <div className="flex min-w-60 flex-col text-left">
            <div className="flex">
              <Link
                to={taskGuildPath(task, `/tasks/${task.id}`)}
                className="text-foreground flex w-full items-center gap-2 font-medium hover:underline"
              >
                {task.title}
              </Link>
              <TaskDescriptionHoverCard task={task} />
            </div>
            <div className="text-muted-foreground space-y-1 text-xs">
              {showAssignees && task.assignees?.length > 0 ? (
                <TaskAssigneeList assignees={task.assignees} className="text-xs" />
              ) : null}
              {recurrenceSummary ? <p>{recurrenceSummary}</p> : null}
            </div>
            <TaskChecklistProgress
              progress={task.subtask_progress}
              className="mt-2 max-w-[200px]"
            />
          </div>
        );
      },
      sortingFn: "alphanumeric",
      enableHiding: false,
    },
    {
      id: "start date",
      accessorKey: "start_date",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex min-w-30 items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.startDate")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => <DateCell date={row.original.start_date} isPastVariant="primary" />,
      sortingFn: dateSortingFn,
    },
    {
      id: "due date",
      accessorKey: "due_date",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex min-w-30 items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.dueDate")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => (
        <DateCell
          date={row.original.due_date}
          isPastVariant="destructive"
          isDone={row.original.task_status?.category === "done"}
        />
      ),
      sortingFn: dateSortingFn,
    },
    {
      id: "path",
      header: () => <span className="font-medium">{t("columns.projectPath")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        const project = projectsById[task.project_id];
        const projectLabel =
          task.project_name ?? project?.name ?? t("projectFallback", { id: task.project_id });
        const projectIdentifier = project?.id ?? task.project_id;
        const guildName = task.guild_name;
        const initiativeId = task.initiative_id ?? project?.initiative_id;
        const initiativeName = task.initiative_name ?? project?.initiative?.name;
        const initiativeColor = task.initiative_color ?? project?.initiative?.color;
        return (
          <div className="min-w-30">
            <div className="flex flex-wrap items-center gap-2">
              {guildName ? (
                <>
                  <span className="text-muted-foreground text-xs sm:text-sm">{guildName}</span>
                  <span className="text-muted-foreground text-sm" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              {initiativeId && initiativeName ? (
                <>
                  <Link
                    to={taskGuildPath(task, `/initiatives/${initiativeId}`)}
                    className="text-muted-foreground flex items-center gap-2 text-sm"
                  >
                    <InitiativeColorDot color={initiativeColor ?? undefined} />
                    {initiativeName}
                  </Link>

                  <span className="text-muted-foreground text-sm" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              <Link
                to={taskGuildPath(task, `/projects/${projectIdentifier}`)}
                className="text-primary text-sm font-medium hover:underline"
              >
                {projectLabel}
              </Link>
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: "priority",
      id: "priority",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.priority")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        return (
          <TaskPrioritySelector
            task={task}
            guildId={task.guild_id ?? activeGuildId}
            disabled={isUpdatingTaskStatus}
          />
        );
      },
      sortingFn: prioritySortingFn,
    },
    {
      id: "tags",
      header: () => <span className="font-medium">{t("columns.tags")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        const taskTags = task.tags ?? [];
        if (taskTags.length === 0) {
          return <span className="text-muted-foreground text-sm">&mdash;</span>;
        }
        return (
          <div className="flex flex-wrap gap-1">
            {taskTags.slice(0, 3).map((tag) => (
              <TagBadge
                key={tag.id}
                tag={tag}
                size="sm"
                to={taskGuildPath(task, `/tags/${tag.id}`)}
              />
            ))}
            {taskTags.length > 3 && (
              <span className="text-muted-foreground text-xs">+{taskTags.length - 3}</span>
            )}
          </div>
        );
      },
      size: 150,
    },
    {
      id: "status",
      header: () => <span className="font-medium">{t("columns.status")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <div className="space-y-1">
            <TaskStatusSelector
              task={task}
              activeGuildId={activeGuildId}
              isUpdatingTaskStatus={isUpdatingTaskStatus}
              changeTaskStatusById={changeTaskStatusById}
              fetchProjectStatuses={fetchProjectStatuses}
              projectStatusCache={projectStatusCache}
            />
          </div>
        );
      },
    },
  ];
}
