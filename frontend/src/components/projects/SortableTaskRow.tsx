import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Task, TaskPriority, TaskStatus } from "@/types/api";
import { truncateText } from "@/lib/text";
import { summarizeRecurrence } from "@/lib/recurrence";
import { Checkbox } from "@/components/ui/checkbox";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";

interface SortableTaskRowProps {
  task: Task;
  dragDisabled: boolean;
  statusDisabled: boolean;
  statusOrder: TaskStatus[];
  priorityVariant: Record<TaskPriority, "default" | "secondary" | "destructive">;
  onStatusChange: (taskId: number, status: TaskStatus) => void;
  onTaskClick: (taskId: number) => void;
  canOpenTask: boolean;
}

export const SortableTaskRow = ({
  task,
  dragDisabled,
  statusDisabled,
  statusOrder,
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
  const isDone = task.status === "done";
  const recurrenceSummary = task.recurrence
    ? summarizeRecurrence(task.recurrence, { referenceDate: task.start_date || task.due_date })
    : null;
  const recurrenceText = recurrenceSummary ? truncateText(recurrenceSummary, 100) : null;
  const formattedStart = task.start_date ? new Date(task.start_date).toLocaleString() : null;
  const formattedDue = task.due_date ? new Date(task.due_date).toLocaleString() : null;

  const handleCompletionToggle = (checked: boolean) => {
    if (statusDisabled) {
      return;
    }
    const nextStatus: TaskStatus = checked ? "done" : "in_progress";
    if (nextStatus !== task.status) {
      onStatusChange(task.id, nextStatus);
    }
  };

  return (
    <tr ref={setNodeRef} style={style} className={isDragging ? "bg-muted/60" : undefined}>
      <td className="py-4 px-2 align-top">
        <Checkbox
          checked={isDone}
          onCheckedChange={(value) => handleCompletionToggle(Boolean(value))}
          disabled={statusDisabled}
          aria-label={isDone ? "Mark task as in progress" : "Mark task as done"}
        />
      </td>
      <td className="py-2 px-2">
        <div className="flex items-start gap-2">
          <button
            type="button"
            className="mt-1 text-muted-foreground"
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
              <p className="text-sm text-muted-foreground">{truncateText(task.description, 100)}</p>
            ) : null}
            <div className="space-y-1 text-xs text-muted-foreground">
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
            </div>
          </button>
        </div>
      </td>
      <td className="py-2 px-2 align-top">
        <Badge variant={priorityVariant[task.priority]}>{task.priority.replace("_", " ")}</Badge>
      </td>
      <td className="py-2 px-2 align-top">
        <Select
          value={task.status}
          onValueChange={(value) => {
            if (statusDisabled) {
              return;
            }
            onStatusChange(task.id, value as TaskStatus);
          }}
          disabled={statusDisabled}
        >
          <SelectTrigger className="w-[160px]" disabled={statusDisabled}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {statusOrder.map((status) => (
              <SelectItem key={status} value={status}>
                {status.replace("_", " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
    </tr>
  );
};
