import {
  closestCenter,
  DndContext,
  type DndContextProps,
  type DragEndEvent,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
  type DragStartEvent,
} from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ColumnDef } from "@tanstack/react-table";
import { GripVertical, MessageSquare } from "lucide-react";
import type React from "react";
import { createContext, memo, useCallback, useContext, useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import {
  collectTagsByName,
  fanOutTasksByTag,
  TAG_GROUP_COLUMN_ID,
  type TaskTagRow,
  tagRowId,
  uniqueTasksFromRows,
} from "@/components/projects/taskTagGrouping";
import { buildPropertyColumns, propertyColumnIds } from "@/components/properties/propertyColumns";
import { SortIcon } from "@/components/SortIcon";
import { TagBadge } from "@/components/tags/TagBadge";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { TaskPrioritySelector } from "@/components/tasks/TaskPrioritySelector";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableRowWrapperProps } from "@/components/ui/data-table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TableRow } from "@/components/ui/table";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { useProperties } from "@/hooks/useProperties";
import { useGuildPath } from "@/lib/guildUrl";
import { summarizeRecurrence } from "@/lib/recurrence";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { truncateText } from "@/lib/text";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

type ProjectTasksListViewProps = {
  projectId: number;
  /**
   * Initiative the project belongs to. Scopes the property column list so
   * this table surfaces only the initiative's property definitions (global
   * views like My Tasks still use the unbound union).
   */
  initiativeId: number;
  tasks: TaskListRead[];
  taskStatuses: TaskStatusRead[];
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
  onTaskSelectionChange?: (selectedTasks: TaskListRead[]) => void;
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

/**
 * Plain row wrapper — no useSortable hook overhead.
 * Used when DnD is disabled (sorting/grouping active, or no reorder permission).
 */
const PlainRowWrapper = ({
  row,
  children,
  virtualStyle,
  virtualIndex,
  measureRef,
}: DataTableRowWrapperProps<TaskTagRow>) => {
  return (
    <TableRow
      ref={measureRef}
      style={virtualStyle}
      className={cn(row.original.is_archived && "opacity-50")}
      data-state={row.getIsSelected() && "selected"}
      data-index={virtualIndex}
    >
      {children}
    </TableRow>
  );
};

/**
 * Sortable row wrapper — calls useSortable hook for DnD support.
 * Only used when DnD is actually possible (no sorting/grouping, has reorder permission).
 */
const SortableRowWrapperInner = ({
  row,
  children,
  virtualStyle,
  virtualIndex,
  measureRef,
}: DataTableRowWrapperProps<TaskTagRow>) => {
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
  });

  const style: React.CSSProperties = {
    ...virtualStyle,
    transform: CSS.Transform.toString(transform) || virtualStyle?.transform,
    transition,
  };

  const contextValue = useMemo(
    () => ({
      attributes,
      listeners,
      setActivatorNodeRef,
      dragDisabled: false,
    }),
    [attributes, listeners, setActivatorNodeRef]
  );

  const setRefs = useCallback(
    (el: HTMLElement | null) => {
      setNodeRef(el);
      measureRef?.(el);
    },
    [setNodeRef, measureRef]
  );

  return (
    <SortableRowContext.Provider value={contextValue}>
      <TableRow
        ref={setRefs}
        style={style}
        className={cn(isDragging && "bg-muted/60", row.original.is_archived && "opacity-50")}
        data-state={row.getIsSelected() && "selected"}
        data-index={virtualIndex}
      >
        {children}
      </TableRow>
    </SortableRowContext.Provider>
  );
};

const ProjectTasksTableViewComponent = ({
  projectId,
  initiativeId,
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

  // Programmatic property columns (hidden by default, persist visibility).
  // Scoped to the project's initiative so the column list stays focused.
  const { data: propertyDefinitions = [] } = useProperties({ initiativeId });
  const propertyColumns = useMemo(
    () => buildPropertyColumns<TaskTagRow>(propertyDefinitions, (row) => row.properties),
    [propertyDefinitions]
  );
  const propertyHiddenIds = useMemo(
    () => propertyColumnIds(propertyDefinitions),
    [propertyDefinitions]
  );
  const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
    `initiative-project-${projectId}-task-columns`,
    propertyHiddenIds
  );
  // "date group" column must always start hidden in this view (non-property
  // toggle). Merge it once with the persisted map. The tag group column drives
  // "group by tag" only — the tags column already shows a task's tags — so it
  // stays hidden whatever the persisted map holds.
  const effectiveColumnVisibility = useMemo(() => {
    const withDateGroup =
      "date group" in columnVisibility
        ? columnVisibility
        : { ...columnVisibility, "date group": false };
    return { ...withDateGroup, [TAG_GROUP_COLUMN_ID]: false };
  }, [columnVisibility]);

  // Tag grouping keys rows by tag name; keep the tags around so a group header
  // can render its badge, and name the group tasks without tags fall into.
  const tagsByName = useMemo(() => collectTagsByName(tasks), [tasks]);
  const untaggedLabel = t("table.untagged");

  // Memoize status lookups to avoid repeated array searches
  const statusLookup = useMemo(() => {
    const doneStatus = taskStatuses.find((status) => status.category === "done");
    const inProgressStatus =
      taskStatuses.find((status) => status.category === "in_progress") ??
      taskStatuses.find((status) => status.category === "todo") ??
      taskStatuses.find((status) => status.category === "backlog");
    return { doneStatus, inProgressStatus };
  }, [taskStatuses]);

  const columns = useMemo<ColumnDef<TaskTagRow>[]>(
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
          <span className="font-medium text-base">
            {getTaskDateStatusLabel(getValue<string>(), t as TranslateFn)}
          </span>
        ),
        enableHiding: true,
        enableSorting: true,
        sortingFn: "alphanumeric",
      },
      {
        // Never rendered as a column of its own (see effectiveColumnVisibility);
        // it holds the single tag a row is grouped under so the table can group
        // by tag, and renders that tag as the group header.
        id: TAG_GROUP_COLUMN_ID,
        accessorFn: (task) => task.tagGroup ?? untaggedLabel,
        header: () => <span className="font-medium">{t("table.tagGroup")}</span>,
        cell: ({ getValue }) => {
          const label = getValue<string>();
          const tag = tagsByName.get(label);
          return tag ? (
            <TagBadge tag={tag} size="md" />
          ) : (
            <span className="font-medium text-base">{label}</span>
          );
        },
        enableHiding: false,
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
              <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
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
          const activeStatus =
            taskStatuses.find((status) => status.id === task.task_status_id) ?? task.task_status;
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
              <SelectTrigger
                className="w-40 border-2"
                style={statusTriggerStyle(activeStatus)}
                disabled={statusDisabled}
                aria-label={t("table.statusColumn")}
              >
                <SelectValue asChild>
                  <TaskStatusOption status={activeStatus} />
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {taskStatuses.map((status) => (
                  <SelectItem key={status.id} value={String(status.id)}>
                    <TaskStatusOption status={status} />
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
      gp,
      onStatusChange,
      onTaskClick,
      statusDisabled,
      tagsByName,
      taskStatuses,
      statusLookup,
      t,
      untaggedLabel,
    ]
  );
  // Insert programmatic property columns between tags (index of "tags") and
  // comments. We splice by id so the insertion point is robust to column-list
  // refactors.
  const columnsWithProperties = useMemo<ColumnDef<TaskTagRow>[]>(() => {
    if (propertyColumns.length === 0) return columns;
    const tagsIdx = columns.findIndex((c) => (c as { id?: string }).id === "tags");
    if (tagsIdx === -1) return [...columns, ...propertyColumns];
    return [...columns.slice(0, tagsIdx + 1), ...propertyColumns, ...columns.slice(tagsIdx + 1)];
  }, [columns, propertyColumns]);
  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("table.dateWindow") },
      { id: TAG_GROUP_COLUMN_ID, label: t("table.tagGroup") },
    ],
    [t]
  );

  const sortableItems = useMemo(() => tasks.map((task) => task.id.toString()), [tasks]);

  // Track sorting/grouping state to know when DnD is possible.
  // When either is active, we skip useSortable hooks entirely for performance.
  const [hasSorting, setHasSorting] = useState(false);
  const [grouping, setGrouping] = useState<string[]>([]);
  const dndEnabled = canReorderTasks && !hasSorting && grouping.length === 0;

  // Grouping by tag means one row per (task, tag) pair — a task with three tags
  // belongs under all three, not under whichever one happens to come first.
  const isTagGrouped = grouping.includes(TAG_GROUP_COLUMN_ID);
  const rows = useMemo<TaskTagRow[]>(
    () => (isTagGrouped ? fanOutTasksByTag(tasks, untaggedLabel) : tasks),
    [isTagGrouped, tasks, untaggedLabel]
  );

  const handleSortingChange = useCallback(
    (sorting: { id: string; desc: boolean }[]) => setHasSorting(sorting.length > 0),
    []
  );
  const handleGroupingChange = useCallback((next: string[]) => setGrouping(next), []);

  // Selection reports rows; a tag-grouped task holds one row per tag, so
  // collapse them back to the tasks themselves.
  const tasksById = useMemo(() => new Map(tasks.map((task) => [task.id, task])), [tasks]);
  const handleSelectionChange = useCallback(
    (selectedRows: TaskTagRow[]) =>
      onTaskSelectionChange?.(uniqueTasksFromRows(selectedRows, tasksById)),
    [onTaskSelectionChange, tasksById]
  );

  const rowWrapper = useCallback(
    (props: DataTableRowWrapperProps<TaskTagRow>) => {
      if (!dndEnabled) {
        return <PlainRowWrapper {...props} />;
      }
      return <SortableRowWrapperInner {...props} />;
    },
    [dndEnabled]
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
        items={dndEnabled ? sortableItems : []}
        strategy={verticalListSortingStrategy}
      >
        <DataTable
          columns={columnsWithProperties}
          data={rows}
          enableVirtualization
          virtualContainerHeight="h-[calc(100vh-20rem)]"
          virtualRowHeight={52}
          groupingOptions={groupingOptions}
          columnVisibility={effectiveColumnVisibility}
          onColumnVisibilityChange={setColumnVisibility}
          onSortingChange={handleSortingChange}
          onGroupingChange={handleGroupingChange}
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
                        className="px-0 text-base text-foreground"
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
          }}
          rowWrapper={rowWrapper}
          enableFilterInput
          filterInputColumnKey="title"
          filterInputPlaceholder={t("table.filterPlaceholder")}
          enableColumnVisibilityDropdown
          enableResetSorting
          enableRowSelection
          onRowSelectionChange={handleSelectionChange}
          getRowId={tagRowId}
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
      prevProps.initiativeId === nextProps.initiativeId
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
  task: TaskListRead;
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
};

const TaskCell = ({ task, canOpenTask, onTaskClick }: TaskCellProps) => {
  const { t } = useTranslation(["projects", "dates"]);
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
        <div className="space-y-1 text-muted-foreground text-xs">
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
