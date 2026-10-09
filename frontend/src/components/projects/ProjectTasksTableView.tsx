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
import { GripVertical } from "lucide-react";
import type React from "react";
import { createContext, memo, useCallback, useContext, useMemo } from "react";
import { Trans, useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import {
  collectTagsByName,
  fanOutTasksByTag,
  TAG_GROUP_COLUMN_ID,
  type TaskTagRow,
  tagRowId,
  uniqueTasksFromRows,
} from "@/components/projects/taskTagGrouping";
import { propertyColumnIds } from "@/components/properties/propertyColumns";
import { SortHeader } from "@/components/SortIcon";
import { TagBadge } from "@/components/tags/TagBadge";
import { sharedTaskColumns } from "@/components/tasks/globalTaskColumns";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableRowWrapperProps } from "@/components/ui/data-table";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { TableRow } from "@/components/ui/table";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import type { useProjectTaskTableState } from "@/hooks/useProjectTaskView";
import { useProperties } from "@/hooks/useProperties";
import type { AppColumnDef } from "@/lib/table";
import { cn } from "@/lib/utils";
import { useProjectViewEnv } from "@/lib/views/fields";
import { taskFields } from "@/lib/views/tasks";

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
  taskActionsDisabled: boolean;
  onDragStart: (event: DragStartEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onStatusChange: (taskId: number, taskStatusId: number) => void;
  taskHref: (taskId: number) => string;
  onTaskSelectionChange?: (selectedTasks: TaskListRead[]) => void;
  onExitSelection?: () => void;
  /** How the reader left the table: from {@link useProjectTaskTableState},
   *  held by the section so its export follows the same sort. It seeds the
   *  table once, at mount, so the section keys this component by it. */
  tableState: ReturnType<typeof useProjectTaskTableState>;
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
      className={cn(row.original.archived_at !== null && "opacity-50")}
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
        className={cn(
          isDragging && "bg-muted/60",
          row.original.archived_at !== null && "opacity-50"
        )}
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
  taskActionsDisabled,
  onDragStart,
  onDragEnd,
  onDragCancel,
  onStatusChange,
  taskHref,
  onTaskSelectionChange,
  onExitSelection,
  tableState: [tableState, { setGrouping, setSorting }],
}: ProjectTasksListViewProps) => {
  const { t } = useTranslation(["projects", "comments", "tasks"]);
  const statusDisabled = !canEditTaskDetails || taskActionsDisabled;
  const env = useProjectViewEnv(taskHref);

  // Property columns are hidden by default, and persist their visibility.
  // Scoped to the project's initiative so the column list stays focused.
  const { data: propertyDefinitions = [] } = useProperties({ initiativeId });
  const fields = useMemo(() => taskFields(propertyDefinitions), [propertyDefinitions]);
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

  const columns = useMemo<AppColumnDef<TaskTagRow>[]>(() => {
    const shared = sharedTaskColumns<TaskTagRow>({
      fields,
      env,
      isPriorityDisabled: () => statusDisabled,
    });
    return [
      {
        id: "drag",
        header: () => <span className="sr-only">{t("table.reorder")}</span>,
        cell: ({ table }) => {
          const sorting = table.atoms.sorting?.get() ?? [];
          const grouping = table.atoms.grouping?.get() ?? [];
          const disableDnd = sorting.length > 0 || grouping.length > 0;
          return !disableDnd ? <DragHandleCell /> : null;
        },
        enableSorting: false,
        size: 40,
        enableHiding: false,
      },
      shared.dateGroup,
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
        sortFn: "alphanumeric",
        size: 150,
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
        ...shared.title,
        // The widest column, so it takes the largest share of whatever space
        // the others leave over.
        size: 360,
      },
      shared.startDate,
      shared.dueDate,
      shared.priority,
      shared.tags,
      ...shared.properties,
      shared.comments,
      {
        id: "status",
        // Board order, read from the statuses this view holds so a column
        // moved on the board sorts where it now stands.
        accessorFn: (task) =>
          taskStatuses.find((status) => status.id === task.task_status_id)?.position ??
          task.task_status.position,
        header: ({ column }) => <SortHeader column={column} label={t("table.statusColumn")} />,
        sortFn: (rowA, rowB, columnId) =>
          rowA.getValue<number>(columnId) - rowB.getValue<number>(columnId),
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
                <TaskStatusOption status={activeStatus} />
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
        // Wide enough for the w-40 status trigger plus cell padding.
        size: 190,
      },
    ];
  }, [
    fields,
    env,
    onStatusChange,
    statusDisabled,
    tagsByName,
    taskStatuses,
    statusLookup,
    t,
    untaggedLabel,
  ]);
  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("tasks:columns.dateWindow") },
      { id: TAG_GROUP_COLUMN_ID, label: t("table.tagGroup") },
    ],
    [t]
  );

  const sortableItems = useMemo(() => tasks.map((task) => task.id.toString()), [tasks]);

  const { grouping, sorting } = tableState;
  // Grouping and sorting each disable drag-to-reorder: a manual order can only
  // be expressed by the table's own row order.
  const dndEnabled = canReorderTasks && sorting.length === 0 && grouping.length === 0;

  // Grouping by tag means one row per (task, tag) pair — a task with three tags
  // belongs under all three, not under whichever one happens to come first.
  const isTagGrouped = grouping.includes(TAG_GROUP_COLUMN_ID);
  const rows = useMemo<TaskTagRow[]>(
    () => (isTagGrouped ? fanOutTasksByTag(tasks, untaggedLabel) : tasks),
    [isTagGrouped, tasks, untaggedLabel]
  );

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
          columns={columns}
          data={rows}
          enableVirtualization
          virtualContainerHeight="h-[calc(100vh-20rem)]"
          virtualRowHeight={52}
          groupingOptions={groupingOptions}
          columnVisibility={effectiveColumnVisibility}
          onColumnVisibilityChange={setColumnVisibility}
          onSortingChange={setSorting}
          onGroupingChange={setGrouping}
          helpText={(table) => {
            const sorting = table.atoms.sorting?.get() ?? [];
            const grouping = table.atoms.grouping?.get() ?? [];
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
          initialSorting={sorting}
          initialState={{
            grouping,
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
      prevProps.taskActionsDisabled === nextProps.taskActionsDisabled &&
      prevProps.initiativeId === nextProps.initiativeId &&
      prevProps.tableState[0] === nextProps.tableState[0]
      // Note: Intentionally ignoring callback prop changes as they're functionally the same
    );
  }
);

const DragHandleCell = () => {
  const { t } = useTranslation(["projects", "comments", "tasks"]);
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
