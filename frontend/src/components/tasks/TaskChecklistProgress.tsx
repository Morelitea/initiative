import { Progress } from "@/components/ui/progress";
import type { TaskSubtaskProgress } from "@/types/api";
import { cn } from "@/lib/utils";

type TaskChecklistProgressProps = {
  progress?: TaskSubtaskProgress | null;
  className?: string;
};

export const TaskChecklistProgress = ({ progress, className }: TaskChecklistProgressProps) => {
  if (!progress || progress.total === 0) {
    return null;
  }

  const ratio = progress.total === 0 ? 0 : Math.round((progress.completed / progress.total) * 100);

  return (
    <div className={cn("space-y-1", className)}>
      <Progress value={ratio} className="h-1.5" />
      <p className="text-muted-foreground text-[11px] font-medium">
        {progress.completed}/{progress.total} subtask{progress.total === 1 ? "" : "s"}
      </p>
    </div>
  );
};
