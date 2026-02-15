import { createContext, useContext, useMemo, memo } from "react";
import { Trans, useTranslation } from "react-i18next";
import { type ColumnDef } from "@tanstack/react-table";
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
  type DragStartEvent,
  type DndContextProps,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
} from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, MessageSquare } from "lucide-react";

import type { ProjectTaskStatus, Task } from "@/types/api";
import { DataTable, type DataTableRowWrapperProps } from "@/components/ui/data-table";
import { TableRow } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { TaskPrioritySelector } from "@/components/tasks/TaskPrioritySelector";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SortIcon } from "@/components/SortIcon";
import { summarizeRecurrence } from "@/lib/recurrence";
import type { TranslateFn } from "@/types/i18n";
import { truncateText } from "@/lib/text";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { cn } from "@/lib/utils";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { TagBadge } from "@/components/tags/TagBadge";
import { useGuildPath } from "@/lib/guildUrl";

type ProjectTasksListViewProps = {
  tasks: Task[];
  taskStatuses: ProjectTaskStatus[];
  sensors: DndContextProps["sensors"];
  canReorderTasks: boolean;
  canEditTaskDetails: boolean;
  canOpenTask: boolean;
  taskActionsDisabled: boolean;
  onDragStart: (event: DragStartEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onStatusChange: (taskId: number, taskStatusId: number) => void;
  onTaskClick: (taskId: number) => void;
  onTaskSelectionChange?: (selectedTasks: Task[]) => void;
  onExitSelection?: () => void;
};

type SortableRowContextValue = {
  attributes?: DraggableAttributes;
  listeners?: DraggableSyntheticListeners;
  setActivatorNodeRef?: (element: HTMLElement | null) => void;
  dragDisabled: boolean;
};

const SortableRowContext = createContext<SortableRowContextValue | null>(null);

const useSortableRowContext = () => useContext(SortableRowContext);

const SortableRowWrapper = ({
  row,
  children,
  dragDisabled,
}: DataTableRowWrapperProps<Task> & { dragDisabled: boolean }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: row.original.id.toString(),
    data: { type: "list-task" },
    disabled: dragDisabled,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const contextValue = useMemo(
    () => ({
      attributes,
      listeners,
      setActivatorNodeRef,
      dragDisabled,
    }),
    [attributes, listeners, setActivatorNodeRef, dragDisabled]
  );

  return (
    <SortableRowContext.Provider value={contextValue}>
      <TableRow
        ref={setNodeRef}
        style={style}
        className={cn(isDragging && "bg-muted/60", row.original.is_archived && "opacity-50")}
        data-state={row.getIsSelected() && "selected"}
      >
        {children}
      </TableRow>
    </SortableRowContext.Provider>
  );
};

const ProjectTasksTableViewComponent = ({
  tasks,
  taskStatuses,
  sensors,
  canReorderTasks,
  canEditTaskDetails,
  canOpenTask,
  taskActionsDisabled,
  onDragStart,
  onDragEnd,
  onDragCancel,
  onStatusChange,
  onTaskClick,
  onTaskSelectionChange,
  onExitSelection,
}: ProjectTasksListViewProps) => {
  const { t } = useTranslation("projects");
  const statusDisabled = !canEditTaskDetails || taskActionsDisabled;
  const gp = useGuildPath();

  // Memoize status lookups to avoid repeated array searches
  const statusLookup = useMemo(() => {
    const doneStatus = taskStatuses.find((status) => status.category === "done");
    const inProgressStatus =
      taskStatuses.find((status) => status.category === "in_progress") ??
      taskStatuses.find((status) => status.category === "todo") ??
      taskStatuses.find((status) => status.category === "backlog");
    return { doneStatus, inProgressStatus };
  }, [taskStatuses]);

  const columns = useMemo<ColumnDef<Task>[]>(
    () => [
      {
        id: "drag",
        header: () => <span className="sr-only">{t("table.reorder")}</span>,
        cell: ({ table }) => {
          const sorting = table.getState().sorting;
          const grouping = table.getState().grouping;
          const disableDnd = sorting.length > 0 || grouping.length > 0;
          return !disableDnd ? <DragHandleCell /> : null;
        },
        enableSorting: false,
        size: 40,
        enableHiding: false,
      },
      {
        id: "date group",
        accessorFn: (task) => getTaskDateStatus(task.start_date, task.due_date),
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("table.dateWindow")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ getValue }) => (
          <span className="text-base font-medium">
            {getTaskDateStatusLabel(getValue<string>(), t as TranslateFn)}
          </span>
        ),
        enableHiding: true,
        enableSorting: true,
        sortingFn: "alphanumeric",
      },
      {
        id: "completed",
        header: () => <span className="font-medium">{t("table.doneColumn")}</span>,
        cell: ({ row }) => {
          const task = row.original;
          const isDone = task.task_status.category === "done";
          return (
            <Checkbox
              checked={isDone}
              onCheckedChange={(value) => {
                if (statusDisabled) {
                  return;
                }
                const targetStatusId = value
                  ? (statusLookup.doneStatus?.id ?? task.task_status_id)
                  : (statusLookup.inProgressStatus?.id ?? task.task_status_id);
                if (targetStatusId && targetStatusId !== task.task_status_id) {
                  onStatusChange(task.id, targetStatusId);
                }
              }}
              className="h-6 w-6"
              disabled={statusDisabled}
              aria-label={isDone ? t("table.markInProgress") : t("table.markDone")}
            />
          );
        },
        enableSorting: false,
        size: 64,
        enableHiding: false,
      },
      {
        id: "title",
        accessorKey: "title",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("table.taskColumn")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => (
          <MemoizedTaskCell
            task={row.original}
            canOpenTask={canOpenTask}
            onTaskClick={onTaskClick}
          />
        ),
        enableSorting: true,
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
                {t("table.startDateColumn")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => <DateCell date={row.original.start_date} isPastVariant="primary" />,
        enableSorting: true,
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
                {t("table.dueDateColumn")}
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
        enableSorting: true,
        sortingFn: dateSortingFn,
      },
      {
        accessorKey: "priority",
        id: "priority",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("table.priorityColumn")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => {
          const task = row.original;
          return <TaskPrioritySelector task={task} disabled={statusDisabled} />;
        },
        sortingFn: prioritySortingFn,
      },
      {
        id: "tags",
        header: () => <span className="font-medium">{t("table.tagsColumn")}</span>,
        cell: ({ row }) => {
          const taskTags = row.original.tags ?? [];
          if (taskTags.length === 0) {
            return <span className="text-muted-foreground text-sm">&mdash;</span>;
          }
          return (
            <div className="flex flex-wrap gap-1">
              {taskTags.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
              ))}
              {taskTags.length > 3 && (
                <span className="text-muted-foreground text-xs">
                  {t("table.moreTagsCount", { count: taskTags.length - 3 })}
                </span>
              )}
            </div>
          );
        },
        size: 150,
      },
      {
        id: "comments",
        header: () => <span className="font-medium">{t("table.commentsColumn")}</span>,
        cell: ({ row }) => {
          const count = row.original.comment_count ?? 0;
          return count > 0 ? (
            <span className="inline-flex items-center gap-1 text-sm">
              <MessageSquare className="text-muted-foreground h-3.5 w-3.5" aria-hidden="true" />
              {count}
            </span>
          ) : (
            <span className="text-muted-foreground text-sm">0</span>
          );
        },
        size: 90,
      },
      {
        id: "status",
        header: () => <span className="font-medium">{t("table.statusColumn")}</span>,
        cell: ({ row }) => {
          const task = row.original;
          return (
            <Select
              value={String(task.task_status_id)}
              onValueChange={(value) => {
                if (statusDisabled) {
                  return;
                }
                const nextId = Number(value);
                if (Number.isFinite(nextId) && nextId !== task.task_status_id) {
                  onStatusChange(task.id, nextId);
                }
              }}
              disabled={statusDisabled}
            >
              <SelectTrigger className="w-40" disabled={statusDisabled}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {taskStatuses.map((status) => (
                  <SelectItem key={status.id} value={String(status.id)}>
                    {status.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          );
        },
        enableHiding: false,
      },
    ],
    [canOpenTask, gp, onStatusChange, onTaskClick, statusDisabled, taskStatuses, statusLookup, t]
  );
  const groupingOptions = useMemo(() => [{ id: "date group", label: t("table.dateWindow") }], [t]);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={onDragCancel}
    >
      <SortableContext
        items={tasks.map((task) => task.id.toString())}
        strategy={verticalListSortingStrategy}
      >
        <DataTable
          columns={columns}
          data={tasks}
          groupingOptions={groupingOptions}
          helpText={(table) => {
            const sorting = table.getState().sorting;
            const grouping = table.getState().grouping;
            const disableDnd = sorting.length > 0 || grouping.length > 0;
            return disableDnd ? (
              <div className="text-muted-foreground">
                <Trans
                  i18nKey="table.manualSortDisabled"
                  ns="projects"
                  components={{
                    1: (
                      <Button
                        variant="link"
                        className="text-foreground px-0 text-base"
                        onClick={() => {
                          table.resetSorting();
                          table.resetGrouping();
                        }}
                      />
                    ),
                  }}
                />
              </div>
            ) : null;
          }}
          initialState={{
            // grouping: ["date group"],
            expanded: true,
            columnVisibility: { "date group": false },
          }}
          rowWrapper={({ row, children }) => (
            <SortableRowWrapper row={row} dragDisabled={!canReorderTasks}>
              {children}
            </SortableRowWrapper>
          )}
          enableFilterInput
          filterInputColumnKey="title"
          filterInputPlaceholder={t("table.filterPlaceholder")}
          enableColumnVisibilityDropdown
          enableResetSorting
          enableRowSelection
          onRowSelectionChange={onTaskSelectionChange}
          getRowId={(row) => String(row.id)}
          onExitSelection={onExitSelection}
        />
      </SortableContext>
    </DndContext>
  );
};

// Memoize the entire table view to prevent re-renders when parent state changes (like composer input)
// Custom comparison focuses on data, not callback references
export const ProjectTasksTableView = memo(
  ProjectTasksTableViewComponent,
  (prevProps, nextProps) => {
    // Only re-render if the data or key flags actually change
    return (
      prevProps.tasks === nextProps.tasks &&
      prevProps.taskStatuses === nextProps.taskStatuses &&
      prevProps.sensors === nextProps.sensors &&
      prevProps.canReorderTasks === nextProps.canReorderTasks &&
      prevProps.canEditTaskDetails === nextProps.canEditTaskDetails &&
      prevProps.canOpenTask === nextProps.canOpenTask &&
      prevProps.taskActionsDisabled === nextProps.taskActionsDisabled
      // Note: Intentionally ignoring callback prop changes as they're functionally the same
    );
  }
);

const DragHandleCell = () => {
  const { t } = useTranslation("projects");
  const sortable = useSortableRowContext();
  if (!sortable) {
    return null;
  }
  const { dragDisabled, attributes, listeners, setActivatorNodeRef } = sortable;
  return (
    <button
      type="button"
      className="text-muted-foreground"
      ref={setActivatorNodeRef}
      {...(attributes ?? {})}
      {...(listeners ?? {})}
      disabled={dragDisabled}
      aria-label={t("table.reorderTask")}
    >
      <GripVertical className="h-4 w-4 cursor-grab" />
    </button>
  );
};

type TaskCellProps = {
  task: Task;
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
};

const TaskCell = ({ task, canOpenTask, onTaskClick }: TaskCellProps) => {
  const { t } = useTranslation("projects");
  // Memoize expensive recurrence computation
  const recurrenceText = useMemo(() => {
    if (!task.recurrence) return null;
    const summary = summarizeRecurrence(
      task.recurrence,
      {
        referenceDate: task.start_date || task.due_date,
        strategy: task.recurrence_strategy,
      },
      t as TranslateFn
    );
    return summary ? truncateText(summary, 100) : null;
  }, [task.recurrence, task.start_date, task.due_date, task.recurrence_strategy, t]);

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className="flex w-full min-w-60 flex-col items-start text-left"
        onClick={() => {
          if (!canOpenTask) {
            return;
          }
          onTaskClick(task.id);
        }}
        disabled={!canOpenTask}
      >
        <p className="flex items-center gap-2 font-medium">{task.title}</p>
        <div className="text-muted-foreground space-y-1 text-xs">
          {task.assignees.length > 0 ? (
            <TaskAssigneeList assignees={task.assignees} className="text-xs" />
          ) : null}
          {recurrenceText ? <p>{recurrenceText}</p> : null}
        </div>
        <TaskChecklistProgress progress={task.subtask_progress} className="mt-2 max-w-[200px]" />
      </button>
      <TaskDescriptionHoverCard task={task} />
    </div>
  );
};

// Memoize the entire TaskCell to prevent unnecessary re-renders
const MemoizedTaskCell = memo(TaskCell, (prevProps, nextProps) => {
  return (
    prevProps.task.id === nextProps.task.id &&
    prevProps.task.title === nextProps.task.title &&
    prevProps.task.recurrence === nextProps.task.recurrence &&
    prevProps.task.recurrence_strategy === nextProps.task.recurrence_strategy &&
    prevProps.task.start_date === nextProps.task.start_date &&
    prevProps.task.due_date === nextProps.task.due_date &&
    prevProps.task.assignees.length === nextProps.task.assignees.length &&
    prevProps.canOpenTask === nextProps.canOpenTask &&
    prevProps.onTaskClick === nextProps.onTaskClick
  );
});

MemoizedTaskCell.displayName = "MemoizedTaskCell";
