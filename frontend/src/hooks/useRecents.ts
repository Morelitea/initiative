import { type UseQueryOptions, useMutation, useQuery } from "@tanstack/react-query";

import { recordCounterGroupViewApiV1GGuildIdCounterGroupsGroupIdViewPost } from "@/api/generated/counters/counters";
import { recordDocumentViewApiV1GGuildIdDocumentsDocumentIdViewPost } from "@/api/generated/documents/documents";
import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { recordProjectViewApiV1GGuildIdProjectsProjectIdViewPost } from "@/api/generated/projects/projects";
import { recordQueueViewApiV1GGuildIdQueuesQueueIdViewPost } from "@/api/generated/queues/queues";
import {
  clearRecentApiV1GGuildIdRecentsEntityTypeEntityIdDelete,
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
    queryFn: () => listRecentsApiV1RecentsGet(),
    staleTime: 30 * 1000,
    ...options,
  });
};

const recorders: Record<RecentEntityType, (guildId: number, id: number) => Promise<unknown>> = {
  project: recordProjectViewApiV1GGuildIdProjectsProjectIdViewPost,
  document: recordDocumentViewApiV1GGuildIdDocumentsDocumentIdViewPost,
  queue: recordQueueViewApiV1GGuildIdQueuesQueueIdViewPost,
  counter_group: recordCounterGroupViewApiV1GGuildIdCounterGroupsGroupIdViewPost,
};

/**
 * Mutation that POSTs ``/<entity>/{id}/view`` to record a recent open. Pages
 * call this in a ``useEffect`` once the entity has loaded and access checks
 * have passed.
 *
 * ``guildId`` is the entity's OWN guild — pass the ``/g/{guildId}`` route param,
 * NOT the active guild. The active guild is shared across tabs (localStorage +
 * storage events), so recording with it tags the view under the wrong guild
 * when another tab is in a different guild; the URL path is per-tab.
 */
export const useRecordRecentView = (entityType: RecentEntityType, guildId: number) => {
  return useMutation({
    mutationFn: async (entityId: number) => {
      await recorders[entityType](guildId, entityId);
    },
    onSuccess: () => {
      void invalidateRecents();
    },
  });
};

/**
 * Mutation that DELETEs ``/recents/{type}/{id}?guild_id=`` (the X on a tab).
 *
 * Guild-ADDRESSED: a tab can belong to any of the user's guilds regardless of
 * the current context, and per-guild entity ids are only unique within their
 * guild, so the tab's ``guild_id`` travels with the call.
 */
export const useClearRecentView = () => {
  return useMutation({
    mutationFn: async ({
      entityType,
      entityId,
      guildId,
    }: {
      entityType: RecentEntityType;
      entityId: number;
      guildId: number;
    }) => {
      await clearRecentApiV1GGuildIdRecentsEntityTypeEntityIdDelete(guildId, entityType, entityId);
    },
    onSuccess: () => {
      void invalidateRecents();
    },
  });
};
