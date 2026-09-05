import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  InitiativeGroupedCountsResponse,
  ListPostsApiV1GGuildIdPostsGetParams,
  PostCreate,
  PostListResponse,
  PostPinUpdate,
  PostRead,
  PostUpdate,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPostApiV1GGuildIdPostsPost,
  deletePostApiV1GGuildIdPostsPostIdDelete,
  getGetPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGetQueryKey,
  getListPostsApiV1GGuildIdPostsGetQueryKey,
  getPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGet,
  getReadPostApiV1GGuildIdPostsPostIdGetQueryKey,
  listPostsApiV1GGuildIdPostsGet,
  readPostApiV1GGuildIdPostsPostIdGet,
  setPostGrantsApiV1GGuildIdPostsPostIdGrantsPut,
  setPostPinApiV1GGuildIdPostsPostIdPinPut,
  updatePostApiV1GGuildIdPostsPostIdPatch,
} from "@/api/generated/posts/posts";
import { invalidateAllPosts, invalidatePost } from "@/api/query-keys";
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
