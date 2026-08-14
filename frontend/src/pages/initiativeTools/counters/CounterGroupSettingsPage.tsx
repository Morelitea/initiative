import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { DuplicateCounterGroupCard } from "@/components/initiativeTools/counters/DuplicateCounterGroupCard";
import { ToolSettingsPage } from "@/components/tools/settings/ToolSettingsPage";
import {
  useCounterGroup,
  useDeleteCounterGroup,
  useSetCounterGroupGrants,
  useUpdateCounterGroup,
} from "@/hooks/useCounters";

export const CounterGroupSettingsPage = () => {
  const { counterGroupId } = useParams({ strict: false }) as { counterGroupId?: string };
  const parsedId = counterGroupId ? Number(counterGroupId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const groupQuery = useCounterGroup(isValidId ? parsedId : null);
  const update = useUpdateCounterGroup(parsedId);
  const setGrants = useSetCounterGroupGrants(parsedId);
  const remove = useDeleteCounterGroup();

  const group = groupQuery.data;

  return (
    <ToolSettingsPage
      tool={Tool.counter_group}
      entity={group}
      isLoading={isValidId && groupQuery.isLoading}
      isError={!isValidId || groupQuery.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
      advancedExtra={
        group ? <DuplicateCounterGroupCard groupId={group.id} groupName={group.name} /> : null
      }
    />
  );
};
