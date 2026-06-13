import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useRouter } from "@tanstack/react-router";
import { GripVertical, MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  TaskListRead,
  TaskPriority,
  TaskStatusCategory,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { TaskAssigneeList } from "@/components/projects/TaskAssigneeList";
import { TagBadge } from "@/components/tags";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { statusTriggerStyle, TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGuilds } from "@/hooks/useGuilds";
import { useGuildPath } from "@/lib/guildUrl";
import { summarizeRecurrence } from "@/lib/recurrence";
import { truncateText } from "@/lib/text";
import type { TranslateFn } from "@/types/i18n";

interface SortableTaskRowProps {
  task: TaskListRead;
  dragDisabled: boolean;
  statusDisabled: boolean;
  taskStatuses: TaskStatusRead[];
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
  const { t } = useTranslation(["projects", "dates", "tasks"]);
  const router = useRouter();
  const gp = useGuildPath();
  const { activeGuildId } = useGuilds();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id.toString(),
    data: { type: "list-task" },
    disabled: dragDisabled,
  });

  const handlePrefetch = () => {
    if (canOpenTask && activeGuildId) {
      router.preloadRoute({
        to: "/g/$guildId/tasks/$taskId",
        params: { guildId: String(activeGuildId), taskId: String(task.id) },
      });
    }
  };

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
    ? summarizeRecurrence(
        task.recurrence,
        {
          referenceDate: task.start_date || task.due_date,
          strategy: task.recurrence_strategy,
        },
        t as TranslateFn
      )
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
          aria-label={isDone ? t("tasks:checkbox.markInProgress") : t("tasks:checkbox.markDone")}
        />
      </td>
      <td className="px-2 py-2">
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
            onMouseEnter={handlePrefetch}
            disabled={!canOpenTask}
          >
            <p className="font-medium">{task.title}</p>
            {task.description ? (
              <p className="text-muted-foreground text-sm">{truncateText(task.description, 100)}</p>
            ) : null}
            <div className="space-y-1 text-muted-foreground text-xs">
              {task.assignees.length > 0 ? (
                <TaskAssigneeList assignees={task.assignees} className="text-xs" />
              ) : null}
              {formattedStart || formattedDue ? (
                <p>
                  {formattedStart ? t("kanban.starts", { date: formattedStart }) : null}
                  {formattedStart && formattedDue ? <span> &mdash; </span> : null}
                  {formattedDue ? t("kanban.due", { date: formattedDue }) : null}
                </p>
              ) : null}
              {recurrenceText ? <p>{recurrenceText}</p> : null}
              {commentCount > 0 ? (
                <p className="inline-flex items-center gap-1">
                  <MessageSquare className="h-3 w-3" aria-hidden="true" />
                  {t("kanban.comments", { count: commentCount })}
                </p>
              ) : null}
            </div>
            <TaskChecklistProgress
              progress={task.subtask_progress}
              className="mt-2 max-w-[200px]"
            />
            {task.tags && task.tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {task.tags.map((tag) => (
                  <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
                ))}
              </div>
            )}
          </button>
        </div>
      </td>
      <td className="px-2 py-2 align-top">
        <Badge variant={priorityVariant[task.priority]}>
          {t("kanban.priority", { priority: task.priority.replace("_", " ") })}
        </Badge>
      </td>
      <td className="px-2 py-2 align-top">
        {(() => {
          const activeStatus =
            taskStatuses.find((status) => status.id === task.task_status_id) ?? task.task_status;
          return (
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
              <SelectTrigger
                className="w-40 border-2"
                style={statusTriggerStyle(activeStatus)}
                disabled={statusDisabled}
              >
                <SelectValue asChild>
                  <TaskStatusOption status={activeStatus} />
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {taskStatuses.map((status) => (
                  <SelectItem key={status.id} value={String(status.id)}>
                    <TaskStatusOption status={status} />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          );
        })()}
      </td>
    </tr>
  );
};
