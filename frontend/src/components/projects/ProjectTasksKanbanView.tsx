import {
  DndContext,
  DragOverlay,
  closestCorners,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  type DndContextProps,
} from "@dnd-kit/core";
import type { Task, TaskPriority, TaskStatus } from "../../types/api";

import { KanbanColumn } from "./KanbanColumn";
import { taskStatusOrder } from "./projectTasksConfig";
import { Badge } from "../ui/badge";
import { Markdown } from "../Markdown";
import { TaskAssigneeList } from "./TaskAssigneeList";

type ProjectTasksKanbanViewProps = {
  groupedTasks: Record<TaskStatus, Task[]>;
  canReorderTasks: boolean;
  canEditTaskDetails: boolean;
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
  groupedTasks,
  canReorderTasks,
  canEditTaskDetails,
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
    collisionDetection={closestCorners}
    onDragStart={onDragStart}
    onDragOver={onDragOver}
    onDragEnd={onDragEnd}
    onDragCancel={onDragCancel}
  >
    <div className="overflow-x-auto pb-4">
      <div className="flex gap-4">
        {taskStatusOrder.map((status) => (
          <div key={status} className="w-89 shrink-0">
            <KanbanColumn
              status={status}
              tasks={groupedTasks[status]}
              canWrite={canReorderTasks}
              canOpenTask={canEditTaskDetails}
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
        <Markdown content={task.description} className="text-xs [&>*]:my-1" />
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
