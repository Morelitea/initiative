import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiClient } from "@/api/client";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import type { Task, TaskPriority } from "@/types/api";

type TaskPrioritySelectorProps = {
  task: Task;
  /** Guild ID override. If not provided, uses the default from apiClient interceptor. */
  guildId?: number | null;
  disabled?: boolean;
};

export const TaskPrioritySelector = ({ task, guildId, disabled }: TaskPrioritySelectorProps) => {
  const { t } = useTranslation("tasks");
  const queryClient = useQueryClient();

  const PRIORITIES: { value: TaskPriority; label: string }[] = useMemo(
    () => [
      { value: "low", label: t("priority.low") },
      { value: "medium", label: t("priority.medium") },
      { value: "high", label: t("priority.high") },
      { value: "urgent", label: t("priority.urgent") },
    ],
    [t]
  );

  const updatePriority = useMutation({
    mutationFn: async (priority: TaskPriority) => {
      const response = await apiClient.patch<Task>(
        `/tasks/${task.id}`,
        { priority },
        guildId != null ? { headers: { "X-Guild-ID": String(guildId) } } : undefined
      );
      return response.data;
    },
    onSuccess: (updatedTask) => {
      // Invalidate relevant queries
      void queryClient.invalidateQueries({ queryKey: ["tasks", task.project_id] });
      void queryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
      void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
      toast.success(
        t("prioritySelector.changed", { priority: t(`priority.${updatedTask.priority}`) })
      );
    },
    onError: (error) => {
      console.error(error);
      const message = error instanceof Error ? error.message : t("prioritySelector.updateError");
      toast.error(message);
    },
  });

  const handlePriorityChange = (value: string) => {
    const newPriority = value as TaskPriority;
    if (newPriority !== task.priority) {
      updatePriority.mutate(newPriority);
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
