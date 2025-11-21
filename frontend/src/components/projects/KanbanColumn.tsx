import { useDroppable } from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { Markdown } from "../Markdown";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import type { Task, TaskPriority, TaskStatus } from "../../types/api";

interface KanbanColumnProps {
  status: TaskStatus;
  tasks: Task[];
  canWrite: boolean;
  priorityVariant: Record<
    TaskPriority,
    "default" | "secondary" | "destructive"
  >;
  onTaskClick: (taskId: number) => void;
  canOpenTask: boolean;
}

export const KanbanColumn = ({
  status,
  tasks,
  canWrite,
  priorityVariant,
  onTaskClick,
  canOpenTask,
}: KanbanColumnProps) => {
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${status}`,
    data: { type: "column", status },
  });

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg capitalize">
          {status.replace("_", " ")}
        </CardTitle>
      </CardHeader>
      <CardContent
        ref={setNodeRef}
        className={`space-y-3 ${isOver ? "bg-muted/40" : ""}`}
      >
        <SortableContext
          items={tasks.map((task) => task.id.toString())}
          strategy={verticalListSortingStrategy}
        >
          {tasks.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tasks yet.</p>
          ) : (
            tasks.map((task) => (
              <KanbanTaskCard
                key={task.id}
                task={task}
                canWrite={canWrite}
                priorityVariant={priorityVariant}
                onTaskClick={onTaskClick}
                canOpenTask={canOpenTask}
              />
            ))
          )}
        </SortableContext>
      </CardContent>
    </Card>
  );
};

interface KanbanTaskCardProps {
  task: Task;
  canWrite: boolean;
  priorityVariant: Record<
    TaskPriority,
    "default" | "secondary" | "destructive"
  >;
  onTaskClick: (taskId: number) => void;
  canOpenTask: boolean;
}

const KanbanTaskCard = ({
  task,
  canWrite,
  priorityVariant,
  onTaskClick,
  canOpenTask,
}: KanbanTaskCardProps) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: task.id.toString(),
    data: { type: "task", status: task.status },
    disabled: !canWrite,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="space-y-3 rounded-lg border bg-card p-3 shadow-sm"
    >
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          if (!canOpenTask) {
            return;
          }
          onTaskClick(task.id);
        }}
        disabled={!canOpenTask}
        className={`flex w-full flex-col items-start gap-1 text-left ${
          canOpenTask ? "" : "cursor-not-allowed opacity-70"
        }`}
      >
        <p className="font-medium">{task.title}</p>
        {task.description ? (
          <Markdown content={task.description} className="text-xs [&>*]:my-1" />
        ) : null}
        <div className="text-xs text-muted-foreground">
          {task.assignees.length > 0 ? (
            <p>
              Assigned:{" "}
              {task.assignees
                .map((assignee) => assignee.full_name ?? assignee.email)
                .join(", ")}
            </p>
          ) : null}
          {task.due_date ? (
            <p>Due: {new Date(task.due_date).toLocaleString()}</p>
          ) : null}
        </div>
      </button>
      <Badge variant={priorityVariant[task.priority]}>
        Priority: {task.priority.replace("_", " ")}
      </Badge>
    </div>
  );
};
