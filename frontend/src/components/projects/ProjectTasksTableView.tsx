import { createContext, useContext, useMemo } from "react";
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
import { formatDistance } from "date-fns";

import type { ProjectTaskStatus, Task, TaskPriority } from "@/types/api";
import { DataTable, type DataTableRowWrapperProps } from "@/components/ui/data-table";
import { TableRow } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Markdown } from "@/components/Markdown";
import { SortIcon } from "@/components/SortIcon";
import { summarizeRecurrence } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { cn } from "@/lib/utils";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";

type ProjectTasksListViewProps = {
  tasks: Task[];
  taskStatuses: ProjectTaskStatus[];
  sensors: DndContextProps["sensors"];
  canReorderTasks: boolean;
  canEditTaskDetails: boolean;
  canOpenTask: boolean;
  taskActionsDisabled: boolean;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  onDragStart: (event: DragStartEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onStatusChange: (taskId: number, taskStatusId: number) => void;
  onTaskClick: (taskId: number) => void;
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
        className={cn(isDragging && "bg-muted/60")}
        data-state={row.getIsSelected() && "selected"}
      >
        {children}
      </TableRow>
    </SortableRowContext.Provider>
  );
};

export const ProjectTasksTableView = ({
  tasks,
  taskStatuses,
  sensors,
  canReorderTasks,
  canEditTaskDetails,
  canOpenTask,
  taskActionsDisabled,
  priorityVariant,
  onDragStart,
  onDragEnd,
  onDragCancel,
  onStatusChange,
  onTaskClick,
}: ProjectTasksListViewProps) => {
  const statusDisabled = !canEditTaskDetails || taskActionsDisabled;
  const columns = useMemo<ColumnDef<Task>[]>(
    () => [
      {
        id: "drag",
        header: () => <span className="sr-only">Reorder</span>,
        cell: () => <DragHandleCell />,
        enableSorting: false,
        size: 40,
        enableHiding: false,
      },
      {
        id: "completed",
        header: () => <span className="font-medium">Done</span>,
        cell: ({ row }) => {
          const task = row.original;
          const isDone = task.task_status.category === "done";
          const doneStatus = taskStatuses.find((status) => status.category === "done");
          const inProgressStatus =
            taskStatuses.find((status) => status.category === "in_progress") ??
            taskStatuses.find((status) => status.category === "todo") ??
            taskStatuses.find((status) => status.category === "backlog");
          return (
            <Checkbox
              checked={isDone}
              onCheckedChange={(value) => {
                if (statusDisabled) {
                  return;
                }
                const targetStatusId = value
                  ? (doneStatus?.id ?? task.task_status_id)
                  : (inProgressStatus?.id ?? task.task_status_id);
                if (targetStatusId && targetStatusId !== task.task_status_id) {
                  onStatusChange(task.id, targetStatusId);
                }
              }}
              className="h-6 w-6"
              disabled={statusDisabled}
              aria-label={isDone ? "Mark task as in progress" : "Mark task as done"}
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
              Task
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => column.toggleSorting(isSorted === "asc")}
              >
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => (
          <TaskCell task={row.original} canOpenTask={canOpenTask} onTaskClick={onTaskClick} />
        ),
        enableSorting: true,
        sortingFn: "alphanumeric",
        enableHiding: false,
      },
      {
        accessorKey: "start_date",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex min-w-30 items-center gap-2">
              Start Date
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => column.toggleSorting(isSorted === "asc")}
              >
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => {
          const task = row.original;
          return task.start_date ? (
            formatDistance(new Date(task.start_date), new Date(), { addSuffix: true })
          ) : (
            <span className="text-muted-foreground">—</span>
          );
        },
        enableSorting: true,
        sortingFn: dateSortingFn,
      },
      {
        accessorKey: "due_date",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex min-w-30 items-center gap-2">
              Due Date
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => column.toggleSorting(isSorted === "asc")}
              >
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => {
          const task = row.original;
          return task.due_date ? (
            formatDistance(new Date(task.due_date), new Date(), { addSuffix: true })
          ) : (
            <span className="text-muted-foreground">—</span>
          );
        },
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
              Priority
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => column.toggleSorting(isSorted === "asc")}
              >
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => {
          const task = row.original;
          return (
            <Badge variant={priorityVariant[task.priority]}>
              {task.priority.replace("_", " ")}
            </Badge>
          );
        },
        sortingFn: prioritySortingFn,
      },
      {
        id: "comments",
        header: () => <span className="font-medium">Comments</span>,
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
        header: () => <span className="font-medium">Status</span>,
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
    [canOpenTask, onStatusChange, onTaskClick, priorityVariant, statusDisabled, taskStatuses]
  );

  return (
    <div>
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
          <div className="w-full overflow-x-auto">
            <div className="min-w-[720px]">
              <DataTable
                columns={columns}
                data={tasks}
                rowWrapper={({ row, children }) => (
                  <SortableRowWrapper row={row} dragDisabled={!canReorderTasks}>
                    {children}
                  </SortableRowWrapper>
                )}
                enableFilterInput
                filterInputColumnKey="title"
                filterInputPlaceholder="Filter tasks..."
                enableColumnVisibilityDropdown
                enableResetSorting
              />
            </div>
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
};

const DragHandleCell = () => {
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
      aria-label="Reorder task"
    >
      <GripVertical className="h-4 w-4" />
    </button>
  );
};

type TaskCellProps = {
  task: Task;
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
};

const TaskCell = ({ task, canOpenTask, onTaskClick }: TaskCellProps) => {
  const recurrenceSummary = task.recurrence
    ? summarizeRecurrence(task.recurrence, {
        referenceDate: task.start_date || task.due_date,
        strategy: task.recurrence_strategy,
      })
    : null;
  const recurrenceText = recurrenceSummary ? truncateText(recurrenceSummary, 100) : null;

  return (
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
      <p className="font-medium">{task.title}</p>
      {task.description ? <Markdown content={task.description} className="line-clamp-2" /> : null}
      <div className="text-muted-foreground space-y-1 text-xs">
        {task.assignees.length > 0 ? (
          <TaskAssigneeList assignees={task.assignees} className="text-xs" />
        ) : null}
        {recurrenceText ? <p>{recurrenceText}</p> : null}
      </div>
    </button>
  );
};
