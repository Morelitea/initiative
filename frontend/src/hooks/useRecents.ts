import { type UseQueryOptions, useMutation, useQuery } from "@tanstack/react-query";

import { recordCalendarViewApiV1CGuildIdCalendarsCalendarIdViewPost } from "@/api/generated/calendars/calendars";
import { recordCounterGroupViewApiV1CGuildIdCounterGroupsGroupIdViewPost } from "@/api/generated/counters/counters";
import { recordDashboardViewApiV1CGuildIdDashboardsDashboardIdViewPost } from "@/api/generated/dashboards/dashboards";
import { recordDocumentViewApiV1CGuildIdDocumentsDocumentIdViewPost } from "@/api/generated/documents/documents";
import { recordGalleryViewApiV1CGuildIdGalleriesGalleryIdViewPost } from "@/api/generated/galleries/galleries";
import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { recordPostViewApiV1CGuildIdPostsPostIdViewPost } from "@/api/generated/posts/posts";
import { recordProjectViewApiV1CGuildIdProjectsProjectIdViewPost } from "@/api/generated/projects/projects";
import { recordQueueViewApiV1CGuildIdQueuesQueueIdViewPost } from "@/api/generated/queues/queues";
import {
  clearRecentApiV1CGuildIdRecentsEntityTypeEntityIdDelete,
  getListRecentsApiV1RecentsGetQueryKey,
  listRecentsApiV1RecentsGet,
} from "@/api/generated/recents/recents";
import { invalidate, q } from "@/api/query-keys";

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

import { recordWikiViewApiV1CGuildIdWikisWikiIdViewPost } from "@/api/generated/wikis/wikis";

const recorders: Record<RecentEntityType, (guildId: number, id: number) => Promise<unknown>> = {
  project: recordProjectViewApiV1CGuildIdProjectsProjectIdViewPost,
  document: recordDocumentViewApiV1CGuildIdDocumentsDocumentIdViewPost,
  queue: recordQueueViewApiV1CGuildIdQueuesQueueIdViewPost,
  counter_group: recordCounterGroupViewApiV1CGuildIdCounterGroupsGroupIdViewPost,
  calendar: recordCalendarViewApiV1CGuildIdCalendarsCalendarIdViewPost,
  dashboard: recordDashboardViewApiV1CGuildIdDashboardsDashboardIdViewPost,
  post: recordPostViewApiV1CGuildIdPostsPostIdViewPost,
  gallery: recordGalleryViewApiV1CGuildIdGalleriesGalleryIdViewPost,
  wiki: recordWikiViewApiV1CGuildIdWikisWikiIdViewPost,
};

/**
 * Mutation that POSTs ``/<entity>/{id}/view`` to record a recent open. Pages
 * call this in a ``useEffect`` once the entity has loaded and access checks
 * have passed.
 *
 * ``guildId`` is the entity's OWN guild — pass the ``/c/{guildId}`` route param,
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
      void invalidate(q.recents());
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
      await clearRecentApiV1CGuildIdRecentsEntityTypeEntityIdDelete(guildId, entityType, entityId);
    },
    onSuccess: () => {
      void invalidate(q.recents());
    },
  });
};

export interface ClearRecentTarget {
  entityType: RecentEntityType;
  entityId: number;
  guildId: number;
}

/**
 * Mutation that closes several tabs at once (the "close others" / "close all"
 * context-menu actions). Issues one guild-addressed delete per tab in
 * parallel — each tab can live in a different guild — then invalidates the
 * recents query a single time.
 *
 * Uses ``onSettled`` (not ``onSuccess``) so the cache is refreshed even on a
 * partial failure: ``Promise.all`` rejects on the first failed DELETE, but
 * earlier deletes may already have succeeded server-side, so we must resync
 * regardless of outcome rather than leave stale tabs until the query expires.
 */
export const useClearRecentViews = () => {
  return useMutation({
    mutationFn: async (targets: ClearRecentTarget[]) => {
      await Promise.all(
        targets.map(({ entityType, entityId, guildId }) =>
          clearRecentApiV1CGuildIdRecentsEntityTypeEntityIdDelete(guildId, entityType, entityId)
        )
      );
    },
    onSettled: () => {
      void invalidate(q.recents());
    },
  });
};
