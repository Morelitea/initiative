import { useQuery } from "@tanstack/react-query";

import type {
  WikiPageCreate,
  WikiPageLinks,
  WikiPageMove,
  WikiPageRead,
  WikiPageTree,
  WikiPageUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  addDocumentToWikiApiV1GGuildIdWikisWikiIdDocumentsDocumentIdPut,
  createWikiPageApiV1GGuildIdWikisWikiIdPagesPost,
  deleteWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdDelete,
  getListWikiPagesApiV1GGuildIdWikisWikiIdPagesGetQueryKey,
  getReadWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdGetQueryKey,
  getReadWikiPageLinksApiV1GGuildIdWikisWikiIdPagesPageIdLinksGetQueryKey,
  listWikiPagesApiV1GGuildIdWikisWikiIdPagesGet,
  moveWikiDocumentApiV1GGuildIdWikisWikiIdDocumentsDocumentIdMovePost,
  moveWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdMovePost,
  readWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdGet,
  readWikiPageLinksApiV1GGuildIdWikisWikiIdPagesPageIdLinksGet,
  removeDocumentFromWikiApiV1GGuildIdWikisWikiIdDocumentsDocumentIdDelete,
  updateWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdPatch,
} from "@/api/generated/wikis/wikis";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const wikis = TOOL_HOOKS[Tool.wiki];
export const useWikisList = wikis.useList;
export const useWiki = wikis.useDetail;
export const useCreateWiki = wikis.useCreate;
export const useUpdateWiki = wikis.useUpdate;
export const useDeleteWiki = wikis.useDelete;
export const useSetWikiGrants = wikis.useSetGrants;

// ── A wiki's pages ──────────────────────────────────────────────────────────

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

/**
 * Put an existing document in this wiki, or take it back out.
 *
 * Neither writes the document. A document joins a wiki by an edge, so what
 * changes is what the wiki contains — which is why both invalidate the page
 * list and the wiki, and nothing belonging to the document itself.
 */
export const useAddWikiDocument = (wikiId: number, options?: MutationOpts<WikiPageTree, number>) =>
  useGuildMutation<WikiPageTree, number>(
    {
      mutationFn: (guildId, documentId) =>
        addDocumentToWikiApiV1GGuildIdWikisWikiIdDocumentsDocumentIdPut(
          guildId,
          wikiId,
          documentId
        ),
      invalidate: () => invalidate(q.wikiPages(wikiId), q.wiki(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useRemoveWikiDocument = (wikiId: number, options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, documentId) =>
        removeDocumentFromWikiApiV1GGuildIdWikisWikiIdDocumentsDocumentIdDelete(
          guildId,
          wikiId,
          documentId
        ),
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

/** Which row of the list is being moved, and where it now goes. The row
 *  travels in the variables rather than in the hook, because a drag names it
 *  at the moment it ends — a hook bound to a row would still be bound to the
 *  last one. */
export type MoveWikiPageVars = WikiPageMove & { pageId: number };

export const useMoveWikiPage = (
  wikiId: number,
  options?: MutationOpts<WikiPageRead, MoveWikiPageVars>
) =>
  useGuildMutation<WikiPageRead, MoveWikiPageVars>(
    {
      mutationFn: (guildId, { pageId, ...move }) =>
        moveWikiPageApiV1GGuildIdWikisWikiIdPagesPageIdMovePost(guildId, wikiId, pageId, move),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export type MoveWikiDocumentVars = WikiPageMove & { documentId: number };

/** A borrowed document is a row of the same list, so it moves the same way —
 *  the wiki records where it put it, and the document is not touched. */
export const useMoveWikiDocument = (
  wikiId: number,
  options?: MutationOpts<WikiPageTree, MoveWikiDocumentVars>
) =>
  useGuildMutation<WikiPageTree, MoveWikiDocumentVars>(
    {
      mutationFn: (guildId, { documentId, ...move }) =>
        moveWikiDocumentApiV1GGuildIdWikisWikiIdDocumentsDocumentIdMovePost(
          guildId,
          wikiId,
          documentId,
          move
        ),
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
