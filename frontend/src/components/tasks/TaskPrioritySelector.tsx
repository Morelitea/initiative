import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead, TaskPriority } from "@/api/generated/initiativeAPI.schemas";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useUpdateTaskInGuild } from "@/hooks/useTasks";
import { toast } from "@/lib/chesterToast";

type TaskPrioritySelectorProps = {
  task: TaskListRead;
  disabled?: boolean;
};

export const TaskPrioritySelector = ({ task, disabled }: TaskPrioritySelectorProps) => {
  const { t } = useTranslation("tasks");
  const activeGuildId = useActiveGuildId();

  const PRIORITIES: { value: TaskPriority; label: string }[] = useMemo(
    () => [
      { value: "low", label: t("priority.low") },
      { value: "medium", label: t("priority.medium") },
      { value: "high", label: t("priority.high") },
      { value: "urgent", label: t("priority.urgent") },
    ],
    [t]
  );

  // A cross-guild list names each task's guild; a guild page's rows need not.
  const updatePriority = useUpdateTaskInGuild({
    onSuccess: (updatedTask) => {
      toast.success(
        t("prioritySelector.changed", { priority: t(`priority.${updatedTask.priority}`) })
      );
    },
  });

  const handlePriorityChange = (value: string) => {
    const newPriority = value as TaskPriority;
    if (newPriority !== task.priority) {
      updatePriority.mutate({
        guildId: task.guild_id ?? activeGuildId,
        taskId: task.id,
        data: { priority: newPriority },
      });
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled || updatePriority.isPending}>
        <button
          type="button"
          className="cursor-pointer rounded-md focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
          aria-label={t("prioritySelector.ariaLabel", { priority: t(`priority.${task.priority}`) })}
        >
          <Badge variant={priorityVariant[task.priority]} className="capitalize">
            {t(`priority.${task.priority}`)}
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
