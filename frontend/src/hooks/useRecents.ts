import { type UseQueryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouterState } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import {
  RecentEntityType,
  type RecentItemRead,
  type RecentKind,
  type ViewSource,
} from "@/api/generated/initiativeAPI.schemas";
import {
  clearRecent,
  getListRecentsQueryKey,
  listRecents,
  recordRecent,
} from "@/api/generated/recents/recents";
import { invalidate, q } from "@/api/query-keys";

type QueryOpts<TData> = Omit<UseQueryOptions<TData>, "queryKey" | "queryFn">;

/**
 * Fetches the up-to-20 mixed-type recent items for the header tabs bar.
 *
 * Replaces the previous projects-only ``useRecentProjects`` hook. Items come
 * back ordered by ``last_viewed_at`` desc with entity-specific metadata for
 * rendering icons (emoji for projects, file-type icons for files).
 */
export const useRecents = (options?: QueryOpts<RecentItemRead[]>) => {
  return useQuery<RecentItemRead[]>({
    queryKey: getListRecentsQueryKey(),
    queryFn: () => listRecents(),
    staleTime: 30 * 1000,
    ...options,
  });
};

const TAB_KINDS = new Set<string>(Object.values(RecentEntityType));

/**
 * Mutation that POSTs ``/recents/{type}/{id}`` to record a recent open: of a
 * tool, which becomes a tab, or of something inside one, which does not. Pages
 * call this in a ``useEffect`` once the entity has loaded and access checks
 * have passed. ``source`` is where the open came from; absent is a direct one.
 *
 * ``communityId`` is the entity's OWN community — pass the ``/c/{communityId}`` route param,
 * NOT the active community. The active community is shared across tabs (localStorage +
 * storage events), so recording with it tags the view under the wrong community
 * when another tab is in a different community; the URL path is per-tab.
 */
export const useRecordRecentView = (
  entityType: RecentKind,
  communityId: number,
  source?: ViewSource
) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entityId: number) =>
      recordRecent(communityId, entityType, entityId, source ? { source } : undefined),
    onSuccess: (written) => {
      if (!TAB_KINDS.has(written.entity_type)) {
        return;
      }
      // The bar is read across every community the reader is in, so it is
      // read again only for a tab it does not have yet — whose name and icon
      // nothing here knows. Reopening one already there moves it to the front.
      const key = getListRecentsQueryKey();
      const held = client.getQueryData<RecentItemRead[]>(key);
      const opened = held?.find(
        (item) =>
          item.community_id === communityId &&
          item.entity_type === written.entity_type &&
          item.entity_id === written.entity_id
      );
      if (!held || !opened) {
        void invalidate(q.recents());
        return;
      }
      // Ordered by when each was viewed, as the server orders them, rather
      // than by which answer arrived last.
      client.setQueryData(
        key,
        held
          .map((item) =>
            item === opened ? { ...opened, last_viewed_at: written.last_viewed_at } : item
          )
          .sort((a, b) => Date.parse(b.last_viewed_at) - Date.parse(a.last_viewed_at))
      );
    },
  });
};

interface OpenOptions {
  /** Where an open inside a page came from (an image in the lightbox, an item
   *  in its dialog). The history entry there is the page's, not the open's. */
  source?: ViewSource;
  /** Record again each time this changes: a wiki is opened by each page. */
  each?: number;
}

/**
 * Records that the reader opened this, once it has loaded (``id`` is set only
 * after the read passed its access checks), in the community the route
 * addresses, with where the open came from: the history entry's
 * ``viewSource``, which a search sets when it navigates. A search that brings
 * the reader back to what is already open records it again.
 */
export const useRecordOpen = (
  kind: RecentKind,
  id: number | undefined,
  { source, each }: OpenOptions = {}
) => {
  const { communityId } = useParams({ strict: false }) as { communityId?: string };
  // Read once a navigation has settled, when the page and its history entry
  // agree: while one is under way they move at different times.
  const settled = useRouterState({ select: (state) => state.status === "idle" });
  const arrivedFrom = useRouterState({
    select: (state) => state.resolvedLocation?.state.viewSource,
  });
  const entry = useRouterState({ select: (state) => state.resolvedLocation?.state.__TSR_key });
  const path = useRouterState({ select: (state) => state.resolvedLocation?.pathname });
  const { mutate } = useRecordRecentView(kind, Number(communityId), source ?? arrivedFrom);
  const recorded = useRef<{ id?: number; each?: number; entry?: string; path?: string }>({});
  useEffect(() => {
    // Closed: opening it again is another open.
    if (!id) {
      recorded.current = {};
      return;
    }
    if (!settled) return;
    const last = recorded.current;
    // A search back to the address of what is open. At another address the
    // page is still loading what it names, and `id` is the one being left.
    const searchedAgain =
      !source && arrivedFrom !== undefined && entry !== last.entry && path === last.path;
    if (id === last.id && each === last.each && !searchedAgain) return;
    recorded.current = { id, each, entry, path };
    mutate(id);
  }, [id, each, entry, path, arrivedFrom, settled, source, mutate]);
};

/**
 * Mutation that DELETEs ``/recents/{type}/{id}?community_id=`` (the X on a tab).
 *
 * Community-ADDRESSED: a tab can belong to any of the user's communities regardless of
 * the current context, and per-community entity ids are only unique within their
 * community, so the tab's ``community_id`` travels with the call.
 */
export const useClearRecentView = () => {
  return useMutation({
    mutationFn: async ({
      entityType,
      entityId,
      communityId,
    }: {
      entityType: RecentEntityType;
      entityId: number;
      communityId: number;
    }) => {
      await clearRecent(communityId, entityType, entityId);
    },
    onSuccess: () => {
      void invalidate(q.recents());
    },
  });
};

export interface ClearRecentTarget {
  entityType: RecentEntityType;
  entityId: number;
  communityId: number;
}

/**
 * Mutation that closes several tabs at once (the "close others" / "close all"
 * context-menu actions). Issues one community-addressed delete per tab in
 * parallel — each tab can live in a different community — then invalidates the
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
        targets.map(({ entityType, entityId, communityId }) =>
          clearRecent(communityId, entityType, entityId)
        )
      );
    },
    onSettled: () => {
      void invalidate(q.recents());
    },
  });
};
