import { Link } from "@tanstack/react-router";
import { Pin } from "lucide-react";

import {
  type TaskListRead,
  type TaskStatusCategory,
  type TaskStatusRead,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskBlockersHoverCard } from "@/components/projects/TaskBlockersHoverCard";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { SortHeader } from "@/components/SortIcon";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { TaskPrioritySelector } from "@/components/tasks/TaskPrioritySelector";
import { TaskStatusSelector } from "@/components/tasks/TaskStatusSelector";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { summarizeStored } from "@/lib/recurrence";
import { dateSortingFn, firstTagName, prioritySortingFn, textSortingFn } from "@/lib/sorting";
import type { AppColumnDef } from "@/lib/table";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { entityRefRoute, initiativeRoute, toolDetailRoute } from "@/lib/tools";
import { type FieldColumnOptions, fieldColumn } from "@/lib/views/columns";
import type { FieldDef, ViewEnv } from "@/lib/views/fields";
import type { TranslateFn } from "@/types/i18n";

interface GlobalTaskColumnsOptions {
  activeCommunityId: number | null;
  /** Whether THIS row has a status change in flight — one row saving must not
   *  disable the rest of the table. */
  isUpdatingTask: (task: TaskListRead) => boolean;
  changeTaskStatus: (task: TaskListRead, category: TaskStatusCategory) => Promise<void>;
  changeTaskStatusById: (task: TaskListRead, statusId: number) => Promise<void>;
  fetchProjectStatuses: (
    projectId: number,
    communityId: number | null
  ) => Promise<TaskStatusRead[]>;
  projectStatusCache: React.MutableRefObject<
    Map<number, { statuses: TaskStatusRead[]; complete: boolean }>
  >;
  t: TranslateFn;
  /**
   * Focus-summary pinning. Both are omitted on views that have no focus
   * section, which drops the column entirely rather than showing a dead one.
   */
  isPinned?: (task: TaskListRead) => boolean;
  togglePin?: (task: TaskListRead) => void;
  /** The page's fields, from `taskFields`. */
  fields: ReadonlyMap<string, FieldDef>;
  env: ViewEnv;
}

interface SharedTaskColumnsOptions<T extends TaskListRead> {
  /** The table's fields, from `taskFields`. */
  fields: ReadonlyMap<string, FieldDef>;
  env: ViewEnv;
  isPriorityDisabled: (task: T) => boolean;
}

/**
 * The columns every task table renders alike, keyed so each table places them
 * in its own order. Each but the date window draws a field, as the board's
 * card does; the properties and the plug-ins' fields follow the tags.
 */
export function sharedTaskColumns<T extends TaskListRead>({
  fields,
  env,
  isPriorityDisabled,
}: SharedTaskColumnsOptions<T>) {
  // `taskFields` holds every built-in.
  const column = (id: string, options: FieldColumnOptions<T>) =>
    fieldColumn<T>(fields.get(id) as FieldDef, env, options);
  const dateGroup: AppColumnDef<T> = {
    id: "date group",
    accessorFn: (task) => getTaskDateStatus(task.start_date, task.due_date),
    header: ({ column }) => (
      <SortHeader column={column} label={env.t("tasks:columns.dateWindow")} />
    ),
    cell: ({ getValue }) => (
      <span className="font-medium text-base">
        {getTaskDateStatusLabel(getValue<string>(), env.t)}
      </span>
    ),
    sortFn: "alphanumeric",
  };
  return {
    dateGroup,
    title: column("title", { sortFn: "alphanumeric" }),
    startDate: column("startDate", { sortFn: dateSortingFn }),
    dueDate: column("dueDate", { sortFn: dateSortingFn }),
    // Picking a priority here is the table's own, until fields edit.
    priority: column("priority", {
      sortFn: prioritySortingFn,
      size: 140,
      cell: ({ row }) => (
        <TaskPrioritySelector task={row.original} disabled={isPriorityDisabled(row.original)} />
      ),
    }),
    tags: column("tags", {
      sortBy: (task) => firstTagName(task.tags),
      sortFn: textSortingFn,
      sortUndefined: "last",
    }),
    comments: column("comments", { size: 90 }),
    properties: [...fields.values()]
      .filter((field) => field.source !== "builtin")
      .map((field) => fieldColumn<T>(field, env, { size: 160 })),
  };
}

export function globalTaskColumns({
  activeCommunityId,
  isUpdatingTask,
  changeTaskStatus,
  changeTaskStatusById,
  fetchProjectStatuses,
  projectStatusCache,
  t,
  isPinned,
  togglePin,
  fields,
  env,
}: GlobalTaskColumnsOptions): AppColumnDef<TaskListRead>[] {
  const communityDefaultLabel = t("myTasks.noCommunity");
  const getCommunityGroupLabel = (task: TaskListRead) =>
    task.community_name ?? communityDefaultLabel;

  const shared = sharedTaskColumns<TaskListRead>({
    fields,
    env,
    isPriorityDisabled: isUpdatingTask,
  });

  return [
    shared.dateGroup,
    {
      // The id is kept in device-stored column and grouping state.
      id: "guild",
      accessorFn: (task) => getCommunityGroupLabel(task),
      header: ({ column }) => <SortHeader column={column} label={t("columns.community")} />,
      cell: ({ getValue }) => <span className="font-medium text-base">{getValue<string>()}</span>,
      sortFn: "alphanumeric",
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
              if (isUpdatingTask(task)) {
                return;
              }
              const targetCategory: TaskStatusCategory = value ? "done" : "in_progress";
              void changeTaskStatus(task, targetCategory);
            }}
            className="h-6 w-6"
            disabled={isUpdatingTask(task)}
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
    ...(isPinned && togglePin
      ? [
          {
            id: "focus",
            header: () => <span className="sr-only">{t("focus.title")}</span>,
            cell: ({ row }) => {
              const task = row.original;
              const pinned = isPinned(task);
              return (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0"
                  onClick={() => togglePin(task)}
                  aria-label={pinned ? t("focus.unpin") : t("focus.pin")}
                  title={pinned ? t("focus.unpin") : t("focus.pin")}
                >
                  {pinned ? (
                    <Pin className="h-3.5 w-3.5 fill-current text-primary" />
                  ) : (
                    <Pin className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                </Button>
              );
            },
            enableSorting: false,
            size: 48,
          } satisfies AppColumnDef<TaskListRead>,
        ]
      : []),
    {
      ...shared.title,
      // Its own cell: these rows come from every community, and are all yours.
      cell: ({ row }) => {
        const task = row.original;
        const recurrenceSummary = task.recurrence
          ? summarizeStored(
              task.recurrence,
              task.due_date || task.start_date,
              { strategy: task.recurrence_strategy, shift: task.recurrence_shift },
              t
            )
          : null;
        return (
          <div className="flex min-w-60 flex-col text-left">
            <div className="flex">
              <Link
                to={env.taskHref(task)}
                className="flex w-full items-center gap-2 font-medium text-foreground hover:underline"
              >
                {task.title}
              </Link>
              <TaskBlockersHoverCard task={task} />
              <TaskDescriptionHoverCard task={task} />
            </div>
            <div className="space-y-1 text-muted-foreground text-xs">
              {recurrenceSummary ? <p>{recurrenceSummary}</p> : null}
            </div>
            <TaskChecklistProgress
              progress={task.checklist_progress}
              className="mt-2 max-w-[200px]"
            />
          </div>
        );
      },
    },
    shared.startDate,
    shared.dueDate,
    {
      id: "path",
      header: () => <span className="font-medium">{t("columns.projectPath")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        const projectLabel = task.project_name ?? t("projectFallback", { id: task.project_id });
        const projectIdentifier = task.project_id;
        const communityName = task.community_name;
        const initiativeId = task.initiative_id;
        const initiativeName = task.initiative_name;
        const initiativeColor = task.initiative_color;
        return (
          <div className="min-w-30">
            <div className="flex flex-wrap items-center gap-2">
              {communityName ? (
                <>
                  <span className="text-muted-foreground text-xs sm:text-sm">{communityName}</span>
                  <span className="text-muted-foreground text-sm" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              {initiativeId && initiativeName ? (
                <>
                  <Link
                    to={env.communityPath(initiativeRoute(initiativeId), task)}
                    className="flex items-center gap-2 text-muted-foreground text-sm"
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
                to={env.communityPath(
                  initiativeId != null
                    ? toolDetailRoute(Tool.project, initiativeId, projectIdentifier)
                    : entityRefRoute(Tool.project, projectIdentifier),
                  task
                )}
                className="font-medium text-primary text-sm hover:underline"
              >
                {projectLabel}
              </Link>
            </div>
          </div>
        );
      },
    },
    shared.priority,
    shared.tags,
    ...shared.properties,
    {
      id: "status",
      // Board order: a status's position in its project.
      accessorFn: (task) => task.task_status?.position,
      header: ({ column }) => <SortHeader column={column} label={t("columns.status")} />,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <div className="space-y-1">
            <TaskStatusSelector
              task={task}
              activeCommunityId={activeCommunityId}
              isUpdatingTaskStatus={isUpdatingTask(task)}
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
