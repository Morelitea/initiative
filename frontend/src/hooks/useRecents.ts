import { type UseQueryOptions, useMutation, useQuery } from "@tanstack/react-query";

import {
  clearCounterGroupViewApiV1CounterGroupsGroupIdViewDelete,
  recordCounterGroupViewApiV1CounterGroupsGroupIdViewPost,
} from "@/api/generated/counters/counters";
import {
  clearDocumentViewApiV1DocumentsDocumentIdViewDelete,
  recordDocumentViewApiV1DocumentsDocumentIdViewPost,
} from "@/api/generated/documents/documents";
import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import {
  clearProjectViewApiV1ProjectsProjectIdViewDelete,
  recordProjectViewApiV1ProjectsProjectIdViewPost,
} from "@/api/generated/projects/projects";
import {
  clearQueueViewApiV1QueuesQueueIdViewDelete,
  recordQueueViewApiV1QueuesQueueIdViewPost,
} from "@/api/generated/queues/queues";
import {
  getListRecentsApiV1RecentsGetQueryKey,
  listRecentsApiV1RecentsGet,
} from "@/api/generated/recents/recents";
import { invalidateRecents } from "@/api/query-keys";

export type RecentEntityType = RecentItemRead["entity_type"];

type QueryOpts<TData> = Omit<UseQueryOptions<TData>, "queryKey" | "queryFn">;

/**
 * Fetches the up-to-20 mixed-type recent items for the header tabs bar.
 *
 * Replaces the previous projects-only ``useRecentProjects`` hook. Items come
 * back ordered by ``last_viewed_at`` desc with entity-specific metadata for
 * rendering icons (emoji for projects, document-type icons for documents).
 */
export const useRecents = (options?: QueryOpts<RecentItemRead[]>) => {
  return useQuery<RecentItemRead[]>({
    queryKey: getListRecentsApiV1RecentsGetQueryKey(),
    queryFn: () => listRecentsApiV1RecentsGet() as unknown as Promise<RecentItemRead[]>,
    staleTime: 30 * 1000,
    ...options,
  });
};

const recorders: Record<RecentEntityType, (id: number) => Promise<unknown>> = {
  project: recordProjectViewApiV1ProjectsProjectIdViewPost,
  document: recordDocumentViewApiV1DocumentsDocumentIdViewPost,
  queue: recordQueueViewApiV1QueuesQueueIdViewPost,
  counter_group: recordCounterGroupViewApiV1CounterGroupsGroupIdViewPost,
};

const clearers: Record<RecentEntityType, (id: number) => Promise<unknown>> = {
  project: clearProjectViewApiV1ProjectsProjectIdViewDelete,
  document: clearDocumentViewApiV1DocumentsDocumentIdViewDelete,
  queue: clearQueueViewApiV1QueuesQueueIdViewDelete,
  counter_group: clearCounterGroupViewApiV1CounterGroupsGroupIdViewDelete,
};

/**
 * Mutation that POSTs ``/<entity>/{id}/view`` to record a recent open. Pages
 * call this in a ``useEffect`` once the entity has loaded and access checks
 * have passed.
 */
export const useRecordRecentView = (entityType: RecentEntityType) => {
  return useMutation({
    mutationFn: async (entityId: number) => {
      await recorders[entityType](entityId);
    },
    onSuccess: () => {
      void invalidateRecents();
    },
  });
};

/**
 * Mutation that DELETEs ``/<entity>/{id}/view`` (the X on a tab).
 */
export const useClearRecentView = () => {
  return useMutation({
    mutationFn: async ({
      entityType,
      entityId,
    }: {
      entityType: RecentEntityType;
      entityId: number;
    }) => {
      await clearers[entityType](entityId);
    },
    onSuccess: () => {
      void invalidateRecents();
    },
  });
};
