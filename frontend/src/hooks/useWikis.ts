import { useQuery } from "@tanstack/react-query";

import type {
  WikiPageCreate,
  WikiPageMove,
  WikiPageRead,
  WikiPageTree,
  WikiPageUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  addDocumentToWiki,
  createWikiPage,
  deleteWikiPage,
  duplicateWikiPage,
  getListWikiPagesQueryKey,
  getReadWikiPageQueryKey,
  listWikiPages,
  moveWikiDocument,
  moveWikiPage,
  readWikiPage,
  removeDocumentFromWiki,
  updateWikiPage,
} from "@/api/generated/wikis/wikis";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const wikis = TOOL_HOOKS[Tool.wiki];
export const useWikisList = wikis.useList;
export const useWiki = wikis.useDetail;
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
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<WikiPageTree>({
    queryKey: getListWikiPagesQueryKey(communityId, wikiId!),
    queryFn: () => listWikiPages(communityId, wikiId!),
    enabled: wikiId !== null && Number.isFinite(wikiId) && userEnabled,
    ...rest,
  });
};

export const useWikiPage = (pageId: number | null, options?: QueryOpts<WikiPageRead>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  const ready = pageId !== null && Number.isFinite(pageId);
  return useQuery<WikiPageRead>({
    queryKey: getReadWikiPageQueryKey(communityId, pageId!),
    queryFn: () => readWikiPage(communityId, pageId!),
    enabled: ready && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateWikiPage = (
  wikiId: number,
  options?: MutationOpts<WikiPageRead, WikiPageCreate>
) =>
  useCommunityMutation<WikiPageRead, WikiPageCreate>(
    {
      mutationFn: (communityId, data) => createWikiPage(communityId, wikiId, data),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useDuplicateWikiPage = (
  wikiId: number,
  options?: MutationOpts<WikiPageRead, number>
) =>
  useCommunityMutation<WikiPageRead, number>(
    {
      mutationFn: (communityId, pageId) => duplicateWikiPage(communityId, pageId),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

/**
 * Put an existing document in this wiki, or take it back out.
 *
 * Neither writes the document. A document joins a wiki by an edge, so what
 * changes is what the wiki contains — which is why both invalidate the page
 * list, and nothing belonging to the document itself.
 */
export const useAddWikiDocument = (wikiId: number, options?: MutationOpts<WikiPageTree, number>) =>
  useCommunityMutation<WikiPageTree, number>(
    {
      mutationFn: (communityId, documentId) => addDocumentToWiki(communityId, wikiId, documentId),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useRemoveWikiDocument = (wikiId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, documentId) =>
        removeDocumentFromWiki(communityId, wikiId, documentId),
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
  useCommunityMutation<WikiPageRead, WikiPageUpdate>(
    {
      mutationFn: (communityId, data) => updateWikiPage(communityId, pageId, data),
      // A rename changes the tree, and a body edit changes what links out of
      // this page — so both the tree and the connections are stale.
      invalidate: () => invalidate(q.wikiPages(wikiId), q.relationships()),
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
  useCommunityMutation<WikiPageRead, MoveWikiPageVars>(
    {
      mutationFn: (communityId, { pageId, ...move }) => moveWikiPage(communityId, pageId, move),
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
  useCommunityMutation<WikiPageTree, MoveWikiDocumentVars>(
    {
      mutationFn: (communityId, { documentId, ...move }) =>
        moveWikiDocument(communityId, wikiId, documentId, move),
      invalidate: () => invalidate(q.wikiPages(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );

export const useDeleteWikiPage = (wikiId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, pageId) =>
        deleteWikiPage(communityId, pageId).then(() => undefined),
      invalidate: () => invalidate(q.wikiPages(wikiId), q.wiki(wikiId)),
      errorKey: "wikis:error",
    },
    options
  );
