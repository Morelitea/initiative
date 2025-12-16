import { createContext, useContext, useMemo, memo } from "react";
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
import { SortIcon } from "@/components/SortIcon";
import { summarizeRecurrence } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { cn } from "@/lib/utils";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";

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
        className={cn(isDragging && "bg-muted/60")}
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
  priorityVariant,
  onDragStart,
  onDragEnd,
  onDragCancel,
  onStatusChange,
  onTaskClick,
  onTaskSelectionChange,
  onExitSelection,
}: ProjectTasksListViewProps) => {
  const statusDisabled = !canEditTaskDetails || taskActionsDisabled;

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
        header: () => <span className="sr-only">Reorder</span>,
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
                Date window
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ getValue }) => (
          <span className="text-base font-medium">
            {getTaskDateStatusLabel(getValue<string>())}
          </span>
        ),
        enableHiding: true,
        enableSorting: true,
        sortingFn: "alphanumeric",
      },
      {
        id: "completed",
        header: () => <span className="font-medium">Done</span>,
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
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                Task
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
                Start Date
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
                Due Date
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => <DateCell date={row.original.due_date} isPastVariant="destructive" />,
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
                Priority
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
    [
      canOpenTask,
      onStatusChange,
      onTaskClick,
      priorityVariant,
      statusDisabled,
      taskStatuses,
      statusLookup,
    ]
  );
  const groupingOptions = useMemo(() => [{ id: "date group", label: "Date" }], []);

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
                Manual sorting disabled,{" "}
                <Button
                  variant="link"
                  className="text-foreground px-0 text-base"
                  onClick={() => {
                    table.resetSorting();
                    table.resetGrouping();
                  }}
                >
                  reset column sorting and row grouping
                </Button>{" "}
                to reorder.
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
          filterInputPlaceholder="Filter tasks..."
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
      prevProps.taskActionsDisabled === nextProps.taskActionsDisabled &&
      prevProps.priorityVariant === nextProps.priorityVariant
      // Note: Intentionally ignoring callback prop changes as they're functionally the same
    );
  }
);

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
      <GripVertical className="mt-1 h-4 w-4" />
    </button>
  );
};

type TaskCellProps = {
  task: Task;
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
};

const TaskCell = ({ task, canOpenTask, onTaskClick }: TaskCellProps) => {
  // Memoize expensive recurrence computation
  const recurrenceText = useMemo(() => {
    if (!task.recurrence) return null;
    const summary = summarizeRecurrence(task.recurrence, {
      referenceDate: task.start_date || task.due_date,
      strategy: task.recurrence_strategy,
    });
    return summary ? truncateText(summary, 100) : null;
  }, [task.recurrence, task.start_date, task.due_date, task.recurrence_strategy]);

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
