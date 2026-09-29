import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createCommentApiV1CGuildIdCommentsPost,
  deleteCommentApiV1CGuildIdCommentsCommentIdDelete,
  getListCommentsApiV1CGuildIdCommentsGetQueryKey,
  getRecentCommentsApiV1CGuildIdCommentsRecentGetQueryKey,
  listCommentsApiV1CGuildIdCommentsGet,
  recentCommentsApiV1CGuildIdCommentsRecentGet,
  updateCommentApiV1CGuildIdCommentsCommentIdPatch,
} from "@/api/generated/comments/comments";
import type {
  CommentRead,
  ListCommentsApiV1CGuildIdCommentsGetParams,
  RecentActivityEntry,
  RecentCommentsApiV1CGuildIdCommentsRecentGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useComments = (
  params: ListCommentsApiV1CGuildIdCommentsGetParams,
  options?: QueryOpts<CommentRead[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<CommentRead[]>({
    queryKey: getListCommentsApiV1CGuildIdCommentsGetQueryKey(guildId, params),
    queryFn: () => listCommentsApiV1CGuildIdCommentsGet(guildId, params),
    ...options,
  });
};

export const useRecentComments = (
  params?: RecentCommentsApiV1CGuildIdCommentsRecentGetParams,
  options?: QueryOpts<RecentActivityEntry[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<RecentActivityEntry[]>({
    queryKey: getRecentCommentsApiV1CGuildIdCommentsRecentGetQueryKey(guildId, params),
    queryFn: () => recentCommentsApiV1CGuildIdCommentsRecentGet(guildId, params),
    staleTime: 30 * 1000,
    ...options,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

export const useCommentsCache = (params: ListCommentsApiV1CGuildIdCommentsGetParams) => {
  const guildId = useActiveGuildId();
  const qc = useQueryClient();
  const queryKey = getListCommentsApiV1CGuildIdCommentsGetQueryKey(guildId, params);

  const addComment = (comment: CommentRead) => {
    qc.setQueryData<CommentRead[]>(queryKey, (prev) => (prev ? [...prev, comment] : [comment]));
  };

  const removeComment = (commentId: number) => {
    qc.setQueryData<CommentRead[]>(queryKey, (prev) => prev?.filter((c) => c.id !== commentId));
  };

  const updateComment = (updated: CommentRead) => {
    qc.setQueryData<CommentRead[]>(queryKey, (prev) =>
      prev?.map((c) => (c.id === updated.id ? updated : c))
    );
  };

  return { addComment, removeComment, updateComment };
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateComment = (
  options?: MutationOpts<CommentRead, Parameters<typeof createCommentApiV1CGuildIdCommentsPost>[1]>
) =>
  useGuildMutation<CommentRead, Parameters<typeof createCommentApiV1CGuildIdCommentsPost>[1]>(
    {
      mutationFn: (guildId, data) => createCommentApiV1CGuildIdCommentsPost(guildId, data),
      invalidate: () => invalidate(q.allComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );

export const useUpdateComment = (
  options?: MutationOpts<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateCommentApiV1CGuildIdCommentsCommentIdPatch>[2];
    }
  >
) =>
  useGuildMutation<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateCommentApiV1CGuildIdCommentsCommentIdPatch>[2];
    }
  >(
    {
      mutationFn: (guildId, { commentId, data }) =>
        updateCommentApiV1CGuildIdCommentsCommentIdPatch(guildId, commentId, data),
      invalidate: () => invalidate(q.allComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );

export const useDeleteComment = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, commentId) =>
        deleteCommentApiV1CGuildIdCommentsCommentIdDelete(guildId, commentId),
      invalidate: () => invalidate(q.allComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );
