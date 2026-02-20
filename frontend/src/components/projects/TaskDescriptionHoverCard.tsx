import { TextAlignStart } from "lucide-react";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { HoverCard, HoverCardTrigger, HoverCardContent } from "@/components/ui/hover-card";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/Markdown";
import { cn } from "@/lib/utils";

interface TaskDescriptionHoverCardProps {
  task: TaskListRead;
  className?: string;
}

export const TaskDescriptionHoverCard = ({ task, className }: TaskDescriptionHoverCardProps) => {
  return task.description && task.description.length > 0 ? (
    <HoverCard>
      <HoverCardTrigger asChild>
        <Button variant="ghost" size="icon-sm">
          <TextAlignStart className={cn("h-4 w-4", className)} />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="max-h-120 w-screen max-w-120 overflow-y-auto">
        <Markdown content={task.description} />
      </HoverCardContent>
    </HoverCard>
  ) : null;
};
