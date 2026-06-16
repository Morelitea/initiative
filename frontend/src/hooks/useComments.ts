import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createCommentApiV1GGuildIdCommentsPost,
  deleteCommentApiV1GGuildIdCommentsCommentIdDelete,
  getListCommentsApiV1GGuildIdCommentsGetQueryKey,
  getRecentCommentsApiV1GGuildIdCommentsRecentGetQueryKey,
  getSearchMentionablesApiV1GGuildIdCommentsMentionsSearchGetQueryKey,
  listCommentsApiV1GGuildIdCommentsGet,
  recentCommentsApiV1GGuildIdCommentsRecentGet,
  searchMentionablesApiV1GGuildIdCommentsMentionsSearchGet,
  updateCommentApiV1GGuildIdCommentsCommentIdPatch,
} from "@/api/generated/comments/comments";
import type {
  CommentRead,
  ListCommentsApiV1GGuildIdCommentsGetParams,
  MentionEntityType,
  MentionSuggestion,
  RecentActivityEntry,
  RecentCommentsApiV1GGuildIdCommentsRecentGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllComments } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { castQueryFn } from "@/lib/query-utils";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useComments = (
  params: ListCommentsApiV1GGuildIdCommentsGetParams,
  options?: QueryOpts<CommentRead[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<CommentRead[]>({
    queryKey: getListCommentsApiV1GGuildIdCommentsGetQueryKey(guildId, params),
    queryFn: castQueryFn<CommentRead[]>(() =>
      listCommentsApiV1GGuildIdCommentsGet(guildId, params)
    ),
    ...options,
  });
};

export const useRecentComments = (
  params?: RecentCommentsApiV1GGuildIdCommentsRecentGetParams,
  options?: QueryOpts<RecentActivityEntry[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<RecentActivityEntry[]>({
    queryKey: getRecentCommentsApiV1GGuildIdCommentsRecentGetQueryKey(guildId, params),
    queryFn: castQueryFn<RecentActivityEntry[]>(() =>
      recentCommentsApiV1GGuildIdCommentsRecentGet(guildId, params)
    ),
    staleTime: 30 * 1000,
    ...options,
  });
};

export const useMentionSuggestions = (
  type: MentionEntityType,
  initiativeId: number,
  query: string,
  options?: QueryOpts<MentionSuggestion[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<MentionSuggestion[]>({
    queryKey: getSearchMentionablesApiV1GGuildIdCommentsMentionsSearchGetQueryKey(guildId, {
      entity_type: type,
      initiative_id: initiativeId,
      q: query,
    }),
    queryFn: castQueryFn<MentionSuggestion[]>(() =>
      searchMentionablesApiV1GGuildIdCommentsMentionsSearchGet(guildId, {
        entity_type: type,
        initiative_id: initiativeId,
        q: query,
      })
    ),
    staleTime: 30_000,
    enabled: initiativeId > 0,
    ...options,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

export const useCommentsCache = (params: ListCommentsApiV1GGuildIdCommentsGetParams) => {
  const guildId = useActiveGuildId();
  const qc = useQueryClient();
  const queryKey = getListCommentsApiV1GGuildIdCommentsGetQueryKey(guildId, params);

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
  options?: MutationOpts<CommentRead, Parameters<typeof createCommentApiV1GGuildIdCommentsPost>[1]>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof createCommentApiV1GGuildIdCommentsPost>[1]) => {
      return createCommentApiV1GGuildIdCommentsPost(
        guildId,
        data
      ) as unknown as Promise<CommentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllComments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "common:error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateComment = (
  options?: MutationOpts<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateCommentApiV1GGuildIdCommentsCommentIdPatch>[2];
    }
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      commentId,
      data,
    }: {
      commentId: number;
      data: Parameters<typeof updateCommentApiV1GGuildIdCommentsCommentIdPatch>[2];
    }) => {
      return updateCommentApiV1GGuildIdCommentsCommentIdPatch(
        guildId,
        commentId,
        data
      ) as unknown as Promise<CommentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllComments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "common:error"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteComment = (options?: MutationOpts<void, number>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (commentId: number) => {
      await deleteCommentApiV1GGuildIdCommentsCommentIdDelete(guildId, commentId);
    },
    onSuccess: (...args) => {
      void invalidateAllComments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "common:error"));
      onError?.(...args);
    },
    onSettled,
  });
};
