import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
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
    <ToolSettingsLayout
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
