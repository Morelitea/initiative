import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsPage } from "@/components/tools/settings/ToolSettingsPage";
import { useDeleteQueue, useQueue, useSetQueueGrants, useUpdateQueue } from "@/hooks/useQueues";

export const QueueSettingsPage = () => {
  const { queueId } = useParams({ strict: false }) as { queueId?: string };
  const parsedId = queueId ? Number(queueId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const queueQuery = useQueue(isValidId ? parsedId : null);
  const update = useUpdateQueue(parsedId);
  const setGrants = useSetQueueGrants(parsedId);
  const remove = useDeleteQueue();

  return (
    <ToolSettingsPage
      tool={Tool.queue}
      entity={queueQuery.data}
      isLoading={isValidId && queueQuery.isLoading}
      isError={!isValidId || queueQuery.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
    />
  );
};
