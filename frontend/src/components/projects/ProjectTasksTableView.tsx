import { createContext, useContext, useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
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

import type { ProjectTaskStatus, Task, TaskPriority } from "@/types/api";
import { DataTable, type DataTableRowWrapperProps } from "@/components/ui/data-table";
import { TableRow } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { summarizeRecurrence } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { cn } from "@/lib/utils";

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
              disabled={statusDisabled}
              aria-label={isDone ? "Mark task as in progress" : "Mark task as done"}
            />
          );
        },
        enableSorting: false,
        size: 64,
      },
      {
        accessorKey: "title",
        header: () => <span className="font-medium">Task</span>,
        cell: ({ row }) => (
          <TaskCell task={row.original} canOpenTask={canOpenTask} onTaskClick={onTaskClick} />
        ),
      },
      {
        id: "priority",
        header: () => <span className="font-medium">Priority</span>,
        cell: ({ row }) => {
          const task = row.original;
          return (
            <Badge variant={priorityVariant[task.priority]}>
              {task.priority.replace("_", " ")}
            </Badge>
          );
        },
      },
      {
        id: "comments",
        header: () => <span className="font-medium">Comments</span>,
        cell: ({ row }) => {
          const count = row.original.comment_count ?? 0;
          return count > 0 ? (
            <span className="inline-flex items-center gap-1 text-sm">
              <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {count}
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">0</span>
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
      },
    ],
    [canOpenTask, onStatusChange, onTaskClick, priorityVariant, statusDisabled, taskStatuses]
  );

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
            />
          </div>
        </div>
      </SortableContext>
    </DndContext>
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
      })
    : null;
  const recurrenceText = recurrenceSummary ? truncateText(recurrenceSummary, 100) : null;
  const formattedStart = task.start_date ? new Date(task.start_date).toLocaleString() : null;
  const formattedDue = task.due_date ? new Date(task.due_date).toLocaleString() : null;

  return (
    <button
      type="button"
      className="flex w-full flex-col items-start text-left"
      onClick={() => {
        if (!canOpenTask) {
          return;
        }
        onTaskClick(task.id);
      }}
      disabled={!canOpenTask}
    >
      <p className="font-medium">{task.title}</p>
      {task.description ? (
        <p className="text-sm text-muted-foreground">{truncateText(task.description, 100)}</p>
      ) : null}
      <div className="space-y-1 text-xs text-muted-foreground">
        {task.assignees.length > 0 ? (
          <TaskAssigneeList assignees={task.assignees} className="text-xs" />
        ) : null}
        {formattedStart || formattedDue ? (
          <p>
            {formattedStart ? `Starts: ${formattedStart}` : null}
            {formattedStart && formattedDue ? <span> &mdash; </span> : null}
            {formattedDue ? `Due: ${formattedDue}` : null}
          </p>
        ) : null}
        {recurrenceText ? <p>{recurrenceText}</p> : null}
      </div>
    </button>
  );
};
