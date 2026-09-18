import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  InitiativeGroupedCountsResponse,
  ListWikisApiV1GGuildIdWikisGetParams,
  ResourceGrantSchema,
  WikiCreate,
  WikiListResponse,
  WikiPageCreate,
  WikiPageLinks,
  WikiPageMove,
  WikiPageRead,
  WikiPageTree,
  WikiPageUpdate,
  WikiRead,
  WikiUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  createWikiApiV1GGuildIdWikisPost,
  createWikiPageApiV1GGuildIdWikisWikiIdPagesPost,
  deleteWikiApiV1GGuildIdWikisWikiIdDelete,
  deleteWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdDelete,
  getGetWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGetQueryKey,
  getListWikiPagesApiV1GGuildIdWikisWikiIdPagesGetQueryKey,
  getListWikisApiV1GGuildIdWikisGetQueryKey,
  getReadWikiApiV1GGuildIdWikisWikiIdGetQueryKey,
  getReadWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdGetQueryKey,
  getReadWikiPageLinksApiV1GGuildIdWikisWikiIdPagesPageIdLinksGetQueryKey,
  getWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGet,
  listWikiPagesApiV1GGuildIdWikisWikiIdPagesGet,
  listWikisApiV1GGuildIdWikisGet,
  moveWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdMovePost,
  readWikiApiV1GGuildIdWikisWikiIdGet,
  readWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdGet,
  readWikiPageLinksApiV1GGuildIdWikisWikiIdPagesPageIdLinksGet,
  setWikiGrantsApiV1GGuildIdWikisWikiIdGrantsPut,
  updateWikiApiV1GGuildIdWikisWikiIdPatch,
  updateWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdPatch,
} from "@/api/generated/wikis/wikis";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Visible-wiki counts per initiative, for the sidebar badges. */
export const useWikiCountsByInitiative = (options?: QueryOpts<InitiativeGroupedCountsResponse>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeGroupedCountsResponse>({
    queryKey: getGetWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGetQueryKey(guildId),
    queryFn: () => getWikiCountsByInitiativeApiV1GGuildIdWikisCountsByInitiativeGet(guildId),
    ...options,
  });
};

export const useWikisList = (
  params?: ListWikisApiV1GGuildIdWikisGetParams,
  options?: QueryOpts<WikiListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<WikiListResponse>({
    queryKey: getListWikisApiV1GGuildIdWikisGetQueryKey(guildId, params),
    queryFn: () => listWikisApiV1GGuildIdWikisGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

export const useWiki = (wikiId: number | null, options?: QueryOpts<WikiRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<WikiRead>({
    queryKey: getReadWikiApiV1GGuildIdWikisWikiIdGetQueryKey(guildId, wikiId!),
    queryFn: () => readWikiApiV1GGuildIdWikisWikiIdGet(guildId, wikiId!),
    enabled: wikiId !== null && Number.isFinite(wikiId) && userEnabled,
    ...rest,
  });
};

/**
 * Every page of a wiki, flat and in reading order.
 *
 * One query for the whole tree, because the navigation draws all of it — and
 * the rows carry no bodies, so this stays small however much has been written.
 */
export const useWikiPages = (wikiId: number | null, options?: QueryOpts<WikiPageTree>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<WikiPageTree>({
    queryKey: getListWikiPagesApiV1GGuildIdWikisWikiIdPagesGetQueryKey(guildId, wikiId!),
    queryFn: () => listWikiPagesApiV1GGuildIdWikisWikiIdPagesGet(guildId, wikiId!),
    enabled: wikiId !== null && Number.isFinite(wikiId) && userEnabled,
    ...rest,
  });
};

export const useWikiPage = (
  wikiId: number | null,
  pageId: number | null,
  options?: QueryOpts<WikiPageRead>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  const ready =
    wikiId !== null && pageId !== null && Number.isFinite(wikiId) && Number.isFinite(pageId);
  return useQuery<WikiPageRead>({
    queryKey: getReadWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdGetQueryKey(
      guildId,
      wikiId!,
      pageId!
    ),
    queryFn: () => readWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdGet(guildId, wikiId!, pageId!),
    enabled: ready && userEnabled,
    ...rest,
  });
};

/** What a page links to, and what links back — the backlinks panel. */
export const useWikiPageLinks = (
  wikiId: number | null,
  pageId: number | null,
  options?: QueryOpts<WikiPageLinks>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  const ready =
    wikiId !== null && pageId !== null && Number.isFinite(wikiId) && Number.isFinite(pageId);
  return useQuery<WikiPageLinks>({
    queryKey: getReadWikiPageLinksApiV1GGuildIdWikisWikiIdPagesPageIdLinksGetQueryKey(
      guildId,
      wikiId!,
      pageId!
    ),
    queryFn: () =>
      readWikiPageLinksApiV1GGuildIdWikisWikiIdPagesPageIdLinksGet(guildId, wikiId!, pageId!),
    enabled: ready && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateWiki = (options?: MutationOpts<WikiRead, WikiCreate>) =>
  useGuildMutation<WikiRead, WikiCreate>(
    {
      mutationFn: (guildId, data) => createWikiApiV1GGuildIdWikisPost(guildId, data),
      invalidate: () => invalidate(q.allWikis()),
      errorKey: "wikis:error",
    },
    options
  );

export const useUpdateWiki = (wikiId: number, options?: MutationOpts<WikiRead, WikiUpdate>) =>
  useGuildMutation<WikiRead, WikiUpdate>(
    {
      mutationFn: (guildId, data) => updateWikiApiV1GGuildIdWikisWikiIdPatch(guildId, wikiId, data),
      invalidate: () => invalidate(q.tool(Tool.wiki, wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useDeleteWiki = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, wikiId) =>
        deleteWikiApiV1GGuildIdWikisWikiIdDelete(guildId, wikiId).then(() => undefined),
      invalidate: () => invalidate(q.allWikis()),
      errorKey: "wikis:error",
    },
    options
  );

export const useSetWikiGrants = (
  wikiId: number,
  options?: MutationOpts<WikiRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<WikiRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setWikiGrantsApiV1GGuildIdWikisWikiIdGrantsPut(guildId, wikiId, grants),
      invalidate: () => invalidate(q.wiki(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useCreateWikiPage = (
  wikiId: number,
  options?: MutationOpts<WikiPageRead, WikiPageCreate>
) =>
  useGuildMutation<WikiPageRead, WikiPageCreate>(
    {
      mutationFn: (guildId, data) =>
        createWikiPageApiV1GGuildIdWikisWikiIdPagesPost(guildId, wikiId, data),
      // The tree gains a row and the wiki's page count changes with it.
      invalidate: () => invalidate(q.wikiPages(wikiId), q.wiki(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useUpdateWikiPage = (
  wikiId: number,
  pageId: number,
  options?: MutationOpts<WikiPageRead, WikiPageUpdate>
) =>
  useGuildMutation<WikiPageRead, WikiPageUpdate>(
    {
      mutationFn: (guildId, data) =>
        updateWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdPatch(guildId, wikiId, pageId, data),
      // A rename changes the tree, and a body edit changes what links out of
      // this page — so both the tree and the connections are stale.
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useMoveWikiPage = (
  wikiId: number,
  pageId: number,
  options?: MutationOpts<WikiPageRead, WikiPageMove>
) =>
  useGuildMutation<WikiPageRead, WikiPageMove>(
    {
      mutationFn: (guildId, data) =>
        moveWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdMovePost(guildId, wikiId, pageId, data),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useDeleteWikiPage = (wikiId: number, options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, pageId) =>
        deleteWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdDelete(guildId, wikiId, pageId).then(
          () => undefined
        ),
      invalidate: () => invalidate(q.wikiPages(wikiId), q.wiki(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );
