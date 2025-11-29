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
import type { ProjectTaskStatus, Task, TaskPriority } from "@/types/api";

import { KanbanColumn } from "@/components/projects/KanbanColumn";
import { Badge } from "@/components/ui/badge";
import { truncateText } from "@/lib/text";
import { TaskAssigneeList } from "./TaskAssigneeList";

type ProjectTasksKanbanViewProps = {
  taskStatuses: ProjectTaskStatus[];
  groupedTasks: Record<number, Task[]>;
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
};

export const ProjectTasksKanbanView = ({
  taskStatuses,
  groupedTasks,
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
}: ProjectTasksKanbanViewProps) => (
  <DndContext
    sensors={sensors}
    collisionDetection={kanbanCollisionDetection}
    onDragStart={onDragStart}
    onDragOver={onDragOver}
    onDragEnd={onDragEnd}
    onDragCancel={onDragCancel}
  >
  <div className="overflow-x-auto pb-4">
      <div className="flex gap-4">
        {taskStatuses.map((status) => (
          <div key={status.id} className="w-70 sm:w-89 shrink-0">
            <KanbanColumn
              status={status}
              tasks={groupedTasks[status.id] ?? []}
              canWrite={canReorderTasks}
              canOpenTask={canOpenTask}
              priorityVariant={priorityVariant}
              onTaskClick={onTaskClick}
            />
          </div>
        ))}
      </div>
    </div>
    <DragOverlay>
      {activeTask ? <TaskDragOverlay task={activeTask} priorityVariant={priorityVariant} /> : null}
    </DragOverlay>
  </DndContext>
);

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
  <div className="w-64 space-y-3 rounded-lg border bg-card p-3 shadow-lg">
    <div className="space-y-1">
      <p className="font-medium">{task.title}</p>
      {task.description ? (
        <p className="text-xs text-muted-foreground">{truncateText(task.description, 80)}</p>
      ) : null}
    </div>
    <div className="space-y-1 text-xs text-muted-foreground">
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
