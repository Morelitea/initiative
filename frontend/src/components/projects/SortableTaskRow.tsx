import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, MessageSquare } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ProjectTaskStatus, Task, TaskPriority, TaskStatusCategory } from "@/types/api";
import { truncateText } from "@/lib/text";
import { summarizeRecurrence } from "@/lib/recurrence";
import { Checkbox } from "@/components/ui/checkbox";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";

interface SortableTaskRowProps {
  task: Task;
  dragDisabled: boolean;
  statusDisabled: boolean;
  taskStatuses: ProjectTaskStatus[];
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  onStatusChange: (taskId: number, taskStatusId: number) => void;
  onTaskClick: (taskId: number) => void;
  canOpenTask: boolean;
}

export const SortableTaskRow = ({
  task,
  dragDisabled,
  statusDisabled,
  taskStatuses,
  priorityVariant,
  onStatusChange,
  onTaskClick,
  canOpenTask,
}: SortableTaskRowProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id.toString(),
    data: { type: "list-task" },
    disabled: dragDisabled,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const fallbackCategoryOrder: Record<TaskStatusCategory, TaskStatusCategory[]> = {
    backlog: ["backlog"],
    todo: ["todo", "backlog"],
    in_progress: ["in_progress", "todo", "backlog"],
    done: ["done", "in_progress", "todo", "backlog"],
  };
  const resolveStatusId = (category: TaskStatusCategory): number | null => {
    const fallback = fallbackCategoryOrder[category] ?? [category];
    for (const candidate of fallback) {
      const match = taskStatuses.find((status) => status.category === candidate);
      if (match) {
        return match.id;
      }
    }
    return null;
  };
  const isDone = task.task_status.category === "done";
  const recurrenceSummary = task.recurrence
    ? summarizeRecurrence(task.recurrence, {
        referenceDate: task.start_date || task.due_date,
        strategy: task.recurrence_strategy,
      })
    : null;
  const recurrenceText = recurrenceSummary ? truncateText(recurrenceSummary, 100) : null;
  const formattedStart = task.start_date ? new Date(task.start_date).toLocaleString() : null;
  const formattedDue = task.due_date ? new Date(task.due_date).toLocaleString() : null;
  const commentCount = task.comment_count ?? 0;

  const handleCompletionToggle = (checked: boolean) => {
    if (statusDisabled) {
      return;
    }
    const targetCategory: TaskStatusCategory = checked ? "done" : "in_progress";
    const nextStatusId = resolveStatusId(targetCategory);
    if (nextStatusId && nextStatusId !== task.task_status_id) {
      onStatusChange(task.id, nextStatusId);
    }
  };

  return (
    <tr ref={setNodeRef} style={style} className={isDragging ? "bg-muted/60" : undefined}>
      <td className="px-2 py-4 align-top">
        <Checkbox
          checked={isDone}
          onCheckedChange={(value) => handleCompletionToggle(Boolean(value))}
          disabled={statusDisabled}
          aria-label={isDone ? "Mark task as in progress" : "Mark task as done"}
        />
      </td>
      <td className="px-2 py-2">
        <div className="flex items-start gap-2">
          <button
            type="button"
            className="text-muted-foreground mt-1"
            {...attributes}
            {...listeners}
            disabled={dragDisabled}
          >
            <GripVertical className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="flex flex-col items-start text-left"
            onClick={() => {
              if (!canOpenTask) {
                return;
              }
              onTaskClick(task.id);
            }}
            disabled={!canOpenTask}
          >
            <p className="font-medium">{task.title}</p>
            {task.description ? (
              <p className="text-muted-foreground text-sm">{truncateText(task.description, 100)}</p>
            ) : null}
            <div className="text-muted-foreground space-y-1 text-xs">
              {task.assignees.length > 0 ? (
                <TaskAssigneeList assignees={task.assignees} className="text-xs" />
              ) : null}
              {formattedStart || formattedDue ? (
                <p>
                  {formattedStart ? `Starts: ${formattedStart}` : null}
                  {formattedStart && formattedDue ? <span> &mdash; </span> : null}
                  {formattedDue ? `Due: ${formattedDue}` : null}
                </p>
              ) : null}
              {recurrenceText ? <p>{recurrenceText}</p> : null}
              {commentCount > 0 ? (
                <p className="inline-flex items-center gap-1">
                  <MessageSquare className="h-3 w-3" aria-hidden="true" />
                  {commentCount} comment{commentCount === 1 ? "" : "s"}
                </p>
              ) : null}
            </div>
            <TaskChecklistProgress
              progress={task.subtask_progress}
              className="mt-2 max-w-[200px]"
            />
          </button>
        </div>
      </td>
      <td className="px-2 py-2 align-top">
        <Badge variant={priorityVariant[task.priority]}>{task.priority.replace("_", " ")}</Badge>
      </td>
      <td className="px-2 py-2 align-top">
        <Select
          value={String(task.task_status_id)}
          onValueChange={(value) => {
            if (statusDisabled) {
              return;
            }
            const parsed = Number(value);
            if (Number.isFinite(parsed) && parsed !== task.task_status_id) {
              onStatusChange(task.id, parsed);
            }
          }}
          disabled={statusDisabled}
        >
          <SelectTrigger className="w-[160px]" disabled={statusDisabled}>
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
      </td>
    </tr>
  );
};
