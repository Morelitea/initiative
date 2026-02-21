import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useUpdateTask } from "@/hooks/useTasks";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import type { TaskListRead, TaskPriority } from "@/api/generated/initiativeAPI.schemas";

type TaskPrioritySelectorProps = {
  task: TaskListRead;
  /** Guild ID override. If not provided, uses the default from apiClient interceptor. */
  guildId?: number | null;
  disabled?: boolean;
};

export const TaskPrioritySelector = ({ task, disabled }: TaskPrioritySelectorProps) => {
  const { t } = useTranslation("tasks");

  const PRIORITIES: { value: TaskPriority; label: string }[] = useMemo(
    () => [
      { value: "low", label: t("priority.low") },
      { value: "medium", label: t("priority.medium") },
      { value: "high", label: t("priority.high") },
      { value: "urgent", label: t("priority.urgent") },
    ],
    [t]
  );

  const updatePriority = useUpdateTask({
    onSuccess: (updatedTask) => {
      toast.success(
        t("prioritySelector.changed", { priority: t(`priority.${updatedTask.priority}`) })
      );
    },
  });

  const handlePriorityChange = (value: string) => {
    const newPriority = value as TaskPriority;
    if (newPriority !== task.priority) {
      updatePriority.mutate({ taskId: task.id, data: { priority: newPriority } });
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled || updatePriority.isPending}>
        <button
          type="button"
          className="focus:ring-ring cursor-pointer rounded-md focus:ring-2 focus:ring-offset-2 focus:outline-none"
          aria-label={t("prioritySelector.ariaLabel", { priority: t(`priority.${task.priority}`) })}
        >
          <Badge variant={priorityVariant[task.priority]} className="capitalize">
            {task.priority.replace("_", " ")}
          </Badge>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup value={task.priority} onValueChange={handlePriorityChange}>
          {PRIORITIES.map((p) => (
            <DropdownMenuRadioItem key={p.value} value={p.value}>
              <Badge variant={priorityVariant[p.value]} className="capitalize">
                {p.label}
              </Badge>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
