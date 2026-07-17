import { useMutation } from "@tanstack/react-query";

import { setAdvancedToolTagsApiV1GGuildIdAdvancedToolsAdvancedToolIdTagsPut } from "@/api/generated/advanced-tools/advanced-tools";
import { setCounterGroupTagsApiV1GGuildIdCounterGroupsGroupIdTagsPut } from "@/api/generated/counters/counters";
import type {
  AdvancedToolRead,
  CounterGroupRead,
  QueueRead,
} from "@/api/generated/initiativeAPI.schemas";
import { setQueueTagsApiV1GGuildIdQueuesQueueIdTagsPut } from "@/api/generated/queues/queues";
import {
  invalidateAdvancedTool,
  invalidateAllAdvancedTools,
  invalidateAllCounterGroups,
  invalidateAllQueues,
  invalidateCounterGroup,
  invalidateQueue,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";

/**
 * Set-tags mutations for the queue, counter-group, and advanced-tool tools.
 *
 * Each PUTs the FULL tag id list (the picker owns the complete selection, so
 * there is no read-modify) and then invalidates that tool's list + detail
 * queries so every consumer (settings surface and card) reflects the change.
 * Lives in its own file so it can add these hooks without touching the tool
 * hook modules.
 */

export const useSetQueueTags = (
  options?: MutationOpts<QueueRead, { queueId: number; tagIds: number[] }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation<QueueRead, Error, { queueId: number; tagIds: number[] }>({
    ...rest,
    mutationFn: async ({ queueId, tagIds }) =>
      setQueueTagsApiV1GGuildIdQueuesQueueIdTagsPut(guildId, queueId, {
        tag_ids: tagIds,
      }) as unknown as Promise<QueueRead>,
    onSuccess: (...args) => {
      void invalidateQueue(args[1].queueId);
      void invalidateAllQueues();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "queues:error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetCounterGroupTags = (
  options?: MutationOpts<CounterGroupRead, { groupId: number; tagIds: number[] }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation<CounterGroupRead, Error, { groupId: number; tagIds: number[] }>({
    ...rest,
    mutationFn: async ({ groupId, tagIds }) =>
      setCounterGroupTagsApiV1GGuildIdCounterGroupsGroupIdTagsPut(guildId, groupId, {
        tag_ids: tagIds,
      }) as unknown as Promise<CounterGroupRead>,
    onSuccess: (...args) => {
      void invalidateCounterGroup(args[1].groupId);
      void invalidateAllCounterGroups();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "counterGroups:error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetAdvancedToolTags = (
  options?: MutationOpts<AdvancedToolRead, { advancedToolId: number; tagIds: number[] }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation<AdvancedToolRead, Error, { advancedToolId: number; tagIds: number[] }>({
    ...rest,
    mutationFn: async ({ advancedToolId, tagIds }) =>
      setAdvancedToolTagsApiV1GGuildIdAdvancedToolsAdvancedToolIdTagsPut(guildId, advancedToolId, {
        tag_ids: tagIds,
      }) as unknown as Promise<AdvancedToolRead>,
    onSuccess: (...args) => {
      void invalidateAdvancedTool(args[1].advancedToolId);
      void invalidateAllAdvancedTools();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "advancedTools:error"));
      onError?.(...args);
    },
    onSettled,
  });
};
