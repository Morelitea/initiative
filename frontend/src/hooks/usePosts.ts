import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import type {
  InitiativeGroupedCountsResponse,
  ListPostsApiV1GGuildIdPostsGetParams,
  PostCreate,
  PostListResponse,
  PostPinUpdate,
  PostRead,
  PostReaders,
  PostReadMarks,
  PostReadReceipt,
  PostUpdate,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPostApiV1GGuildIdPostsPost,
  deletePostApiV1GGuildIdPostsPostIdDelete,
  getGetPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGetQueryKey,
  getListPostReadersApiV1GGuildIdPostsPostIdReadsGetQueryKey,
  getListPostsApiV1GGuildIdPostsGetQueryKey,
  getPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGet,
  getReadPostApiV1GGuildIdPostsPostIdGetQueryKey,
  listPostReadersApiV1GGuildIdPostsPostIdReadsGet,
  listPostsApiV1GGuildIdPostsGet,
  markPostsReadApiV1GGuildIdPostsReadPost,
  markPostUnreadApiV1GGuildIdPostsPostIdReadDelete,
  readPostApiV1GGuildIdPostsPostIdGet,
  setPostGrantsApiV1GGuildIdPostsPostIdGrantsPut,
  setPostPinApiV1GGuildIdPostsPostIdPinPut,
  updatePostApiV1GGuildIdPostsPostIdPatch,
} from "@/api/generated/posts/posts";
import { invalidateAllPosts, invalidatePost, patchCachedPost } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Visible-post counts per initiative, for the sidebar badges. */
export const usePostCountsByInitiative = (options?: QueryOpts<InitiativeGroupedCountsResponse>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeGroupedCountsResponse>({
    queryKey: getGetPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGetQueryKey(guildId),
    queryFn: () => getPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGet(guildId),
    ...options,
  });
};

/**
 * One page of a board.
 *
 * Unlike every other tool list this carries whole posts — a board renders its
 * notices — so the server pages it in twenties. `keepPreviousData` keeps the
 * current page on screen while the next one loads, rather than blanking the
 * board between pages.
 */
export const usePostsList = (
  params?: ListPostsApiV1GGuildIdPostsGetParams,
  options?: QueryOpts<PostListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<PostListResponse>({
    queryKey: getListPostsApiV1GGuildIdPostsGetQueryKey(guildId, params),
    queryFn: () => listPostsApiV1GGuildIdPostsGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/**
 * The board, page by page, as somebody scrolls it.
 *
 * A board is read downwards, not paged through, so this is an infinite query
 * rather than a page cursor in the URL. Pages are small — five — because each
 * row is a body the client mounts an editor for, and what a page bounds is how
 * much is fetched ahead of the reader, not how much they have to look at.
 */
export const usePostsFeed = (params?: ListPostsApiV1GGuildIdPostsGetParams) => {
  const guildId = useActiveGuildId();
  return useInfiniteQuery({
    queryKey: getListPostsApiV1GGuildIdPostsGetQueryKey(guildId, params),
    queryFn: ({ pageParam }) =>
      listPostsApiV1GGuildIdPostsGet(guildId, { ...params, page: pageParam as number }),
    initialPageParam: 1,
    getNextPageParam: (last: PostListResponse) => (last.has_next ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
  });
};

/**
 * Who has read a notice, and who it is still waiting on.
 *
 * Fetched when somebody asks — the count is on the card, and the roster behind
 * it is a click. A board of five cards should not fetch five rosters nobody
 * opened.
 */
export const usePostReaders = (postId: number, options?: QueryOpts<PostReaders>) => {
  const guildId = useActiveGuildId();
  return useQuery<PostReaders>({
    queryKey: getListPostReadersApiV1GGuildIdPostsPostIdReadsGetQueryKey(guildId, postId),
    queryFn: () => listPostReadersApiV1GGuildIdPostsPostIdReadsGet(guildId, postId),
    ...options,
  });
};

export const usePost = (postId: number | null, options?: QueryOpts<PostRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<PostRead>({
    queryKey: getReadPostApiV1GGuildIdPostsPostIdGetQueryKey(guildId, postId!),
    queryFn: () => readPostApiV1GGuildIdPostsPostIdGet(guildId, postId!),
    enabled: postId !== null && Number.isFinite(postId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidatePostAndList = (postId: number) =>
  Promise.all([invalidatePost(postId), invalidateAllPosts()]);

export const useCreatePost = (options?: MutationOpts<PostRead, PostCreate>) =>
  useGuildMutation<PostRead, PostCreate>(
    {
      mutationFn: (guildId, data) => createPostApiV1GGuildIdPostsPost(guildId, data),
      invalidate: () => invalidateAllPosts(),
      errorKey: "posts:error",
    },
    options
  );

export const useUpdatePost = (postId: number, options?: MutationOpts<PostRead, PostUpdate>) => {
  const guildId = useActiveGuildId();
  return useGuildMutation<PostRead, PostUpdate>(
    {
      mutationFn: (guildId, data) => updatePostApiV1GGuildIdPostsPostIdPatch(guildId, postId, data),
      invalidate: (updated) => {
        // The PATCH answers with the row a refetch would fetch, so seed it
        // rather than leaving the cache on the pre-save copy until the refetch
        // lands — otherwise the editor shows the old body for a beat.
        queryClient.setQueryData(
          getReadPostApiV1GGuildIdPostsPostIdGetQueryKey(guildId, postId),
          updated
        );
        return invalidatePostAndList(postId);
      },
      errorKey: "posts:error",
    },
    options
  );
};

/**
 * Pin a notice to the top of its board, or take it down.
 *
 * Invalidates the whole list rather than patching the cached row: pinning
 * changes the board's *order*, not just this post, so every page of it is
 * stale.
 */
export const useSetPostPin = (postId: number, options?: MutationOpts<PostRead, PostPinUpdate>) =>
  useGuildMutation<PostRead, PostPinUpdate>(
    {
      mutationFn: (guildId, data) =>
        setPostPinApiV1GGuildIdPostsPostIdPinPut(guildId, postId, data),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );

/**
 * Write one post's read state into every cached copy of it.
 *
 * The count moves with it: marking read adds this reader to it, marking unread
 * takes them back off, so "Read by 12" does not sit there contradicting the
 * button beside it.
 */
const setCachedReadState = (postId: number, isRead: boolean) =>
  patchCachedPost(postId, (post) => {
    if (post.is_read === isRead) return post;
    const count = typeof post.read_count === "number" ? post.read_count : 0;
    return { ...post, is_read: isRead, read_count: Math.max(0, count + (isRead ? 1 : -1)) };
  });

/**
 * Tell the server which notices have been on screen.
 *
 * Deliberately does NOT invalidate. Read state changes continuously as
 * somebody scrolls, and refetching for it would move rows under the cursor —
 * and with the unread filter on, delete the one being read. The cached copies
 * are patched instead.
 *
 * Patched on the way OUT rather than on the way back, because nothing here
 * refetches: without an optimistic write the card would keep saying unread
 * until something else happened to refresh it. Put back if the request fails,
 * so a dropped connection does not quietly mark a board read.
 */
export const useMarkPostsRead = (options?: MutationOpts<PostReadReceipt, PostReadMarks>) =>
  useGuildMutation<PostReadReceipt, PostReadMarks>(
    {
      mutationFn: (guildId, data) => markPostsReadApiV1GGuildIdPostsReadPost(guildId, data),
      errorKey: "posts:error",
    },
    {
      ...options,
      // Rest args rather than a named signature, so this composes with
      // whatever arity react-query hands the caller's own callbacks.
      onMutate: (...args) => {
        for (const id of args[0].post_ids) setCachedReadState(id, true);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        for (const id of args[1].post_ids) setCachedReadState(id, false);
        options?.onError?.(...args);
      },
    }
  );

/**
 * Put one notice back to unread.
 *
 * Optimistic for the same reason: this is a button somebody pressed, and
 * nothing invalidates behind it, so the card has to answer immediately or look
 * broken. Restored on failure.
 */
export const useMarkPostUnread = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, postId) =>
        markPostUnreadApiV1GGuildIdPostsPostIdReadDelete(guildId, postId),
      errorKey: "posts:error",
    },
    {
      ...options,
      onMutate: (...args) => {
        setCachedReadState(args[0], false);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        setCachedReadState(args[1], true);
        options?.onError?.(...args);
      },
    }
  );

export const useDeletePost = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, postId) => deletePostApiV1GGuildIdPostsPostIdDelete(guildId, postId),
      invalidate: () => invalidateAllPosts(),
      errorKey: "posts:error",
    },
    options
  );

// ── Grants Mutation (unified resource sharing) ──────────────────────────────

export const useSetPostGrants = (
  postId: number,
  options?: MutationOpts<PostRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<PostRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setPostGrantsApiV1GGuildIdPostsPostIdGrantsPut(guildId, postId, grants),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );
