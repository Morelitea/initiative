import {
  type CollisionDetection,
  closestCorners,
  DndContext,
  type DndContextProps,
  type DragEndEvent,
  type DragOverEvent,
  DragOverlay,
  type DragStartEvent,
  type DroppableContainer,
  pointerWithin,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskListRead,
  TaskPriority,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { KanbanColumn } from "@/components/projects/KanbanColumn";
import { KanbanFieldsMenu } from "@/components/projects/KanbanFieldsMenu";
import {
  buildKanbanCardFields,
  type KanbanCardFields,
  kanbanFieldsStorageKey,
} from "@/components/projects/kanbanFields";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Badge } from "@/components/ui/badge";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { useProperties } from "@/hooks/useProperties";
import { truncateText } from "@/lib/text";
import { cn } from "@/lib/utils";

import { TaskAssigneeList } from "./TaskAssigneeList";

type ProjectTasksKanbanViewProps = {
  projectId: number;
  initiativeId: number;
  taskStatuses: TaskStatusRead[];
  groupedTasks: Record<number, TaskListRead[]>;
  collapsedStatusIds: Set<number>;
  canReorderTasks: boolean;
  canOpenTask: boolean;
  taskHref: (taskId: number) => string;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  sensors: DndContextProps["sensors"];
  activeTask: TaskListRead | null;
  onDragStart: (event: DragStartEvent) => void;
  onDragOver: (event: DragOverEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onToggleCollapse: (statusId: number) => void;
  onArchiveDoneTasks?: (statusId: number) => void;
  isArchivingDoneTasks?: boolean;
};

export const ProjectTasksKanbanView = ({
  projectId,
  initiativeId,
  taskStatuses,
  groupedTasks,
  collapsedStatusIds,
  canReorderTasks,
  canOpenTask,
  taskHref,
  priorityVariant,
  sensors,
  activeTask,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDragCancel,
  onToggleCollapse,
  onArchiveDoneTasks,
  isArchivingDoneTasks,
}: ProjectTasksKanbanViewProps) => {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  useHorizontalDragScroll(scrollContainerRef);

  // Which fields each card shows. Scoped to this project's initiative, like
  // the table's property columns, so the menu lists the properties a task
  // here can actually carry. No default-hidden ids: a board that has never
  // been configured shows everything, as it did before the menu existed.
  const { data: propertyDefinitions = [] } = useProperties({ initiativeId });
  // The hook holds this in state, so its identity is stable between changes —
  // which is what lets the memoized card skip re-rendering on every parent pass.
  const [fieldVisibility, setFieldVisibility] = usePersistedColumnVisibility(
    kanbanFieldsStorageKey(projectId),
    EMPTY_DEFAULT_HIDDEN
  );
  // Built once per change rather than once per card, and stable in between so
  // the memoized cards skip re-rendering on an unrelated parent pass.
  const visibleFields = useMemo(
    () => buildKanbanCardFields(fieldVisibility, propertyDefinitions),
    [fieldVisibility, propertyDefinitions]
  );

  const taskStatusesLength = taskStatuses.length;
  // Basis rather than min-width: it is what the collapse animates.
  const columnBasis = cn(
    "grow-0 basis-70 sm:grow",
    taskStatusesLength > 4 ? "sm:basis-80" : "sm:basis-89"
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={kanbanCollisionDetection}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={onDragCancel}
    >
      <div className="mb-3 flex justify-end">
        <KanbanFieldsMenu
          propertyDefinitions={propertyDefinitions}
          visibility={fieldVisibility}
          onChange={setFieldVisibility}
        />
      </div>
      <div
        ref={scrollContainerRef}
        className="scrollbar-thin cursor-grab overflow-x-auto pb-4"
        data-kanban-scroll-container
      >
        <div className="flex gap-4">
          {taskStatuses.map((status) => {
            const isCollapsed = collapsedStatusIds.has(status.id);
            return (
              <KanbanColumn
                key={status.id}
                status={status}
                tasks={groupedTasks[status.id] ?? []}
                canWrite={canReorderTasks}
                canOpenTask={canOpenTask}
                priorityVariant={priorityVariant}
                visibleFields={visibleFields}
                taskHref={taskHref}
                collapsed={isCollapsed}
                onToggleCollapse={onToggleCollapse}
                taskCount={groupedTasks[status.id]?.length ?? 0}
                className={cn(
                  "max-h-[70vh] min-h-[70vh] shrink-0 transition-[flex-basis,flex-grow] duration-200",
                  isCollapsed ? "grow-0 basis-12" : columnBasis
                )}
                onArchiveDoneTasks={onArchiveDoneTasks}
                isArchiving={isArchivingDoneTasks}
              />
            );
          })}
        </div>
      </div>
      <DragOverlay>
        {activeTask ? (
          <TaskDragOverlay
            task={activeTask}
            priorityVariant={priorityVariant}
            visibleFields={visibleFields}
          />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
};

// Prefer pointer-over targets to avoid snapping tasks into neighboring columns.
const kanbanCollisionDetection: CollisionDetection = (args) => {
  const pointerIntersections = pointerWithin(args);
  if (pointerIntersections.length > 0) {
    const prioritized = [...pointerIntersections].sort((a, b) => {
      const aType = getDroppableType(args.droppableContainers, a.id);
      const bType = getDroppableType(args.droppableContainers, b.id);

      if (aType === bType) {
        return 0;
      }
      if (aType === "task") {
        return -1;
      }
      if (bType === "task") {
        return 1;
      }
      return 0;
    });
    return prioritized;
  }
  return closestCorners(args);
};

const getDroppableType = (
  containers: DroppableContainer[],
  id: UniqueIdentifier
): string | undefined => containers.find((container) => container.id === id)?.data.current?.type;

const TaskDragOverlay = ({
  task,
  priorityVariant,
  visibleFields,
}: {
  task: TaskListRead;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  visibleFields: KanbanCardFields;
}) => {
  const { t } = useTranslation("projects");
  // The thing being dragged is the card, so it drops the same fields the card
  // dropped — otherwise picking one up puts back what you just turned off.
  const { shows } = visibleFields;
  return (
    <div className="w-64 space-y-3 rounded-lg border bg-card p-3 shadow-lg">
      <div className="space-y-1">
        <p className="font-medium">{task.title}</p>
        {shows("description") && task.description ? (
          <p className="text-muted-foreground text-xs">{truncateText(task.description, 80)}</p>
        ) : null}
      </div>
      <div className="space-y-1 text-muted-foreground text-xs">
        {shows("assignees") && task.assignees.length > 0 ? (
          <TaskAssigneeList assignees={task.assignees} className="text-xs" />
        ) : null}
        {shows("dueDate") && task.due_date ? (
          <p>{t("kanban.due", { date: new Date(task.due_date).toLocaleString() })}</p>
        ) : null}
      </div>
      {shows("checklist") ? <TaskChecklistProgress progress={task.checklist_progress} /> : null}
      {shows("priority") ? (
        <Badge variant={priorityVariant[task.priority]}>
          {t("kanban.priority", { priority: task.priority.replace("_", " ") })}
        </Badge>
      ) : null}
    </div>
  );
};

// Module-level so its identity is stable; the hook re-seeds defaults whenever
// this array's contents change.
const EMPTY_DEFAULT_HIDDEN: string[] = [];

const useHorizontalDragScroll = (ref: React.RefObject<HTMLDivElement | null>) => {
  useEffect(() => {
    const container = ref.current;
    if (!container) {
      return;
    }
    let isDragging = false;
    let startX = 0;
    let scrollStart = 0;
    let pointerId: number | null = null;

    const shouldIgnoreEvent = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) {
        return false;
      }
      return Boolean(target.closest('[data-kanban-scroll-lock="true"]'));
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) {
        return;
      }
      if (shouldIgnoreEvent(event.target)) {
        return;
      }
      isDragging = true;
      pointerId = event.pointerId;
      startX = event.clientX;
      scrollStart = container.scrollLeft;
      container.setPointerCapture(event.pointerId);
      container.style.cursor = "grabbing";
      // Suppress the browser's native text-selection drag while we're
      // pan-scrolling, otherwise the user smears a selection across every
      // card their pointer moves over.
      container.style.userSelect = "none";
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (!isDragging || pointerId !== event.pointerId) {
        return;
      }
      const delta = event.clientX - startX;
      container.scrollLeft = scrollStart - delta;
    };

    const stopDragging = () => {
      if (!isDragging) {
        return;
      }
      isDragging = false;
      if (pointerId !== null) {
        try {
          container.releasePointerCapture(pointerId);
        } catch {
          // ignore
        }
      }
      pointerId = null;
      container.style.cursor = "";
      container.style.userSelect = "";
    };

    container.addEventListener("pointerdown", handlePointerDown);
    container.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("pointerup", stopDragging);
    container.addEventListener("pointerleave", stopDragging);
    container.addEventListener("pointercancel", stopDragging);

    return () => {
      container.removeEventListener("pointerdown", handlePointerDown);
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerup", stopDragging);
      container.removeEventListener("pointerleave", stopDragging);
      container.removeEventListener("pointercancel", stopDragging);
    };
  }, [ref]);
};
