import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";

import { Markdown } from "../Markdown";
import { Badge } from "../ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import type { Task, TaskPriority, TaskStatus } from "../../types/api";

interface SortableTaskRowProps {
  task: Task;
  dragDisabled: boolean;
  statusDisabled: boolean;
  statusOrder: TaskStatus[];
  priorityVariant: Record<
    TaskPriority,
    "default" | "secondary" | "destructive"
  >;
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
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: task.id.toString(),
    data: { type: "list-task" },
    disabled: dragDisabled,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <tr
      ref={setNodeRef}
      style={style}
      className={isDragging ? "bg-muted/60" : undefined}
    >
      <td className="py-3">
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
              <Markdown content={task.description} className="[&>*]:my-1" />
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
        </div>
      </td>
      <td className="py-3">
        <Badge variant="secondary" className="capitalize">
          {task.status.replace("_", " ")}
        </Badge>
      </td>
      <td className="py-3">
        <Badge variant={priorityVariant[task.priority]}>
          {task.priority.replace("_", " ")}
        </Badge>
      </td>
      <td className="py-3">
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
