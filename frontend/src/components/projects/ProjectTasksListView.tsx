import {
  DndContext,
  closestCenter,
  type DragEndEvent,
  type DragStartEvent,
  type DndContextProps,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

import type { Task, TaskPriority, TaskStatus } from "../../types/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import { SortableTaskRow } from "./SortableTaskRow";
import { taskStatusOrder } from "./projectTasksConfig";

type ProjectTasksListViewProps = {
  listTasks: Task[];
  sensors: DndContextProps["sensors"];
  canReorderTasks: boolean;
  canEditTaskDetails: boolean;
  taskActionsDisabled: boolean;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  onDragStart: (event: DragStartEvent) => void;
  onDragEnd: (event: DragEndEvent) => void;
  onDragCancel: () => void;
  onStatusChange: (taskId: number, status: TaskStatus) => void;
  onTaskClick: (taskId: number) => void;
};

export const ProjectTasksListView = ({
  listTasks,
  sensors,
  canReorderTasks,
  canEditTaskDetails,
  taskActionsDisabled,
  priorityVariant,
  onDragStart,
  onDragEnd,
  onDragCancel,
  onStatusChange,
  onTaskClick,
}: ProjectTasksListViewProps) => (
  <Card className="shadow-sm">
    <CardHeader>
      <CardTitle>Task list</CardTitle>
      <CardDescription>
        View every task at once and update their status inline.
      </CardDescription>
    </CardHeader>
    <CardContent className="overflow-x-auto">
      {listTasks.length === 0 ? (
        <p className="text-sm text-muted-foreground">No tasks yet.</p>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onDragCancel={onDragCancel}
        >
          <SortableContext
            items={listTasks.map((task) => task.id.toString())}
            strategy={verticalListSortingStrategy}
          >
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="pb-2 pl-3 font-medium">Done</th>
                  <th className="pb-2 font-medium">Task</th>
                  <th className="pb-2 font-medium">Priority</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {listTasks.map((task) => (
                  <SortableTaskRow
                    key={task.id}
                    task={task}
                    dragDisabled={!canReorderTasks}
                    statusDisabled={!canEditTaskDetails || taskActionsDisabled}
                    canOpenTask={canEditTaskDetails}
                    statusOrder={taskStatusOrder}
                    priorityVariant={priorityVariant}
                    onStatusChange={(taskId, value) => onStatusChange(taskId, value)}
                    onTaskClick={onTaskClick}
                  />
                ))}
              </tbody>
            </table>
          </SortableContext>
        </DndContext>
      )}
    </CardContent>
  </Card>
);
