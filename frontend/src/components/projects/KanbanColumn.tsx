import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { MessageSquare } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import type { ProjectTaskStatus, Task, TaskPriority } from "@/types/api";
import { truncateText } from "@/lib/text";
import { summarizeRecurrence } from "@/lib/recurrence";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";

interface KanbanColumnProps {
  status: ProjectTaskStatus;
  tasks: Task[];
  canWrite: boolean;
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
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
    id: `column-${status.id}`,
    data: { type: "column", statusId: status.id },
  });

  return (
    <Card className="flex h-full flex-col shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg">{status.name}</CardTitle>
      </CardHeader>
      <CardContent
        ref={setNodeRef}
        className={`flex-1 space-y-3 overflow-y-auto ${isOver ? "bg-muted/40" : ""}`}
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
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
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
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id.toString(),
    data: { type: "task", statusId: task.task_status_id },
    disabled: !canWrite,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : undefined,
  };

  const recurrenceSummary = task.recurrence
    ? summarizeRecurrence(task.recurrence, { referenceDate: task.start_date || task.due_date })
    : null;
  const recurrenceText = recurrenceSummary ? truncateText(recurrenceSummary, 80) : null;
  const formattedStart = task.start_date ? new Date(task.start_date).toLocaleString() : null;
  const formattedDue = task.due_date ? new Date(task.due_date).toLocaleString() : null;
  const commentCount = task.comment_count ?? 0;

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
          <p className="text-xs text-muted-foreground">{truncateText(task.description, 80)}</p>
        ) : null}
        <div className="space-y-1 text-xs text-muted-foreground">
          {task.assignees.length > 0 ? (
            <TaskAssigneeList assignees={task.assignees} className="text-xs" />
          ) : null}
          {formattedStart ? <p>Starts: {formattedStart}</p> : null}
          {formattedDue ? <p>Due: {formattedDue}</p> : null}
          {recurrenceText ? <p>{recurrenceText}</p> : null}
        </div>
      </button>
      <div className="flex flex-wrap gap-2">
        <Badge variant={priorityVariant[task.priority]}>
          Priority: {task.priority.replace("_", " ")}
        </Badge>
        {commentCount > 0 ? (
          <Badge variant="outline" className="inline-flex items-center gap-1 text-xs">
            <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
            {commentCount}
          </Badge>
        ) : null}
      </div>
    </div>
  );
};
