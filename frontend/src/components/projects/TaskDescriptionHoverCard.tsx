import { TextAlignStart } from "lucide-react";
import { useState } from "react";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { useReadTask } from "@/api/generated/tasks/tasks";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { Button } from "@/components/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { cn } from "@/lib/utils";

interface TaskDescriptionHoverCardProps {
  task: Pick<TaskListRead, "id" | "community_id" | "has_description" | "description_excerpt">;
  className?: string;
}

/**
 * A task's description, where the task is a row in a list.
 *
 * A list row carries only an excerpt, so the whole text is read from the task
 * once the card opens, under the key the task's own page reads it with; the
 * excerpt stands in while it loads.
 */
export const TaskDescriptionHoverCard = ({ task, className }: TaskDescriptionHoverCardProps) => {
  const [open, setOpen] = useState(false);
  const activeGuildId = useActiveGuildId();
  const { data } = useReadTask(task.community_id ?? activeGuildId, task.id, undefined, {
    query: { enabled: open },
  });

  if (!task.has_description) return null;

  return (
    <HoverCard open={open} onOpenChange={setOpen}>
      <HoverCardTrigger asChild>
        <Button variant="ghost" size="icon-sm">
          <TextAlignStart className={cn("h-4 w-4", className)} />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="max-h-120 w-screen max-w-120 overflow-y-auto">
        {data?.description ? (
          <TaskDescription content={data.description} />
        ) : (
          <p className="text-muted-foreground text-sm">{task.description_excerpt}</p>
        )}
      </HoverCardContent>
    </HoverCard>
  );
};
