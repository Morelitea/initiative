import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { BulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { DialogWithSuccessProps } from "@/types/dialog";

interface BulkEditTaskTagsDialogProps extends DialogWithSuccessProps {
  tasks: TaskListRead[];
}

export function BulkEditTaskTagsDialog({ tasks, ...dialogProps }: BulkEditTaskTagsDialogProps) {
  const communityId = useActiveCommunityId();

  return (
    <BulkEditTagsDialog
      {...dialogProps}
      items={tasks}
      targetType="task"
      communityId={communityId}
      onInvalidate={() => void invalidate(q.allTasks())}
    />
  );
}
