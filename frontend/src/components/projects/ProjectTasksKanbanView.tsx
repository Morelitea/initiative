import {
  DndContext,
  DragOverlay,
  closestCorners,
  pointerWithin,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  type DndContextProps,
  type DroppableContainer,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import { useEffect, useRef } from "react";
import type { ProjectTaskStatus, Task, TaskPriority } from "@/types/api";

import { KanbanColumn } from "@/components/projects/KanbanColumn";
import { Badge } from "@/components/ui/badge";
import { truncateText } from "@/lib/text";
import { cn } from "@/lib/utils";
import { TaskAssigneeList } from "./TaskAssigneeList";

type ProjectTasksKanbanViewProps = {
  taskStatuses: ProjectTaskStatus[];
  groupedTasks: Record<number, Task[]>;
  collapsedStatusIds: Set<number>;
  canReorderTasks: boolean;
  canOpenTask: boolean;
  onTaskClick: (taskId: number) => void;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  sensors: DndContextProps["sensors"];
  activeTask: Task | null;
  onDragStart: (event: DragStartEvent) => void;
  onDragOver: (event: DragOverEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onToggleCollapse: (statusId: number) => void;
};

export const ProjectTasksKanbanView = ({
  taskStatuses,
  groupedTasks,
  collapsedStatusIds,
  canReorderTasks,
  canOpenTask,
  onTaskClick,
  priorityVariant,
  sensors,
  activeTask,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDragCancel,
  onToggleCollapse,
}: ProjectTasksKanbanViewProps) => {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  useHorizontalDragScroll(scrollContainerRef);

  const taskStatusesLength = taskStatuses.length;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={kanbanCollisionDetection}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={onDragCancel}
    >
      <div
        ref={scrollContainerRef}
        className="cursor-grab overflow-x-auto pb-4"
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
                onTaskClick={onTaskClick}
                collapsed={isCollapsed}
                onToggleCollapse={onToggleCollapse}
                taskCount={groupedTasks[status.id]?.length ?? 0}
                className={cn(
                  "max-h-[70vh] min-h-[70vh] shrink-0 transition-[width] duration-200",
                  isCollapsed
                    ? "w-12 min-w-12"
                    : taskStatusesLength > 4
                      ? "w-70 sm:w-80"
                      : "w-70 sm:w-89"
                )}
              />
            );
          })}
        </div>
      </div>
      <DragOverlay>
        {activeTask ? (
          <TaskDragOverlay task={activeTask} priorityVariant={priorityVariant} />
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
}: {
  task: Task;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
}) => (
  <div className="bg-card w-64 space-y-3 rounded-lg border p-3 shadow-lg">
    <div className="space-y-1">
      <p className="font-medium">{task.title}</p>
      {task.description ? (
        <p className="text-muted-foreground text-xs">{truncateText(task.description, 80)}</p>
      ) : null}
    </div>
    <div className="text-muted-foreground space-y-1 text-xs">
      {task.assignees.length > 0 ? (
        <TaskAssigneeList assignees={task.assignees} className="text-xs" />
      ) : null}
      {task.due_date ? <p>Due: {new Date(task.due_date).toLocaleString()}</p> : null}
    </div>
    <Badge variant={priorityVariant[task.priority]}>
      Priority: {task.priority.replace("_", " ")}
    </Badge>
  </div>
);

const useHorizontalDragScroll = (ref: React.RefObject<HTMLDivElement>) => {
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
