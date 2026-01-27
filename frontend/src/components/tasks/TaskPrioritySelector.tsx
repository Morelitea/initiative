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

const PRIORITIES: { value: TaskPriority; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

type TaskPrioritySelectorProps = {
  task: Task;
  /** Guild ID override. If not provided, uses the default from apiClient interceptor. */
  guildId?: number | null;
  disabled?: boolean;
};

export const TaskPrioritySelector = ({ task, guildId, disabled }: TaskPrioritySelectorProps) => {
  const queryClient = useQueryClient();

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
      toast.success(`Priority changed to ${updatedTask.priority}`);
    },
    onError: (error) => {
      console.error(error);
      const message = error instanceof Error ? error.message : "Unable to update priority.";
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
          aria-label={`Priority: ${task.priority}. Click to change.`}
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
