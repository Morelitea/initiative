import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ProjectTaskStatus, Task } from "@/types/api";

type TaskStatusSelectorProps = {
  task: Task;
  activeGuildId: number | null;
  isUpdatingTaskStatus: boolean;
  changeTaskStatusById: (task: Task, statusId: number) => Promise<void>;
  fetchProjectStatuses: (projectId: number, guildId: number | null) => Promise<ProjectTaskStatus[]>;
  projectStatusCache: React.MutableRefObject<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >;
};

export const TaskStatusSelector = ({
  task,
  activeGuildId,
  isUpdatingTaskStatus,
  changeTaskStatusById,
  fetchProjectStatuses,
  projectStatusCache,
}: TaskStatusSelectorProps) => {
  const [statuses, setStatuses] = useState<ProjectTaskStatus[]>(() => {
    const cached = projectStatusCache.current.get(task.project_id);
    return cached?.statuses ?? [task.task_status];
  });

  const handleOpenChange = useCallback(
    async (open: boolean) => {
      if (open) {
        const guildId = task.guild_id ?? activeGuildId ?? null;
        const fetchedStatuses = await fetchProjectStatuses(task.project_id, guildId);
        setStatuses(fetchedStatuses);
      }
    },
    [task, activeGuildId, fetchProjectStatuses]
  );

  const sortedStatuses = useMemo(
    () => [...statuses].sort((a, b) => a.position - b.position),
    [statuses]
  );

  return (
    <Select
      value={String(task.task_status.id)}
      onValueChange={(value) => {
        const targetId = Number(value);
        if (Number.isNaN(targetId)) {
          toast.error("Invalid status selected.");
          return;
        }
        void changeTaskStatusById(task, targetId);
      }}
      onOpenChange={handleOpenChange}
      disabled={isUpdatingTaskStatus}
    >
      <SelectTrigger className="w-40">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {sortedStatuses.map((status) => (
          <SelectItem key={status.id} value={String(status.id)}>
            {status.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};
