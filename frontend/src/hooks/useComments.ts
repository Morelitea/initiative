import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listCommentsApiV1CommentsGet,
  getListCommentsApiV1CommentsGetQueryKey,
  recentCommentsApiV1CommentsRecentGet,
  getRecentCommentsApiV1CommentsRecentGetQueryKey,
  searchMentionablesApiV1CommentsMentionsSearchGet,
  getSearchMentionablesApiV1CommentsMentionsSearchGetQueryKey,
  createCommentApiV1CommentsPost,
  updateCommentApiV1CommentsCommentIdPatch,
  deleteCommentApiV1CommentsCommentIdDelete,
} from "@/api/generated/comments/comments";
import { invalidateAllComments } from "@/api/query-keys";
import type {
  MentionEntityType,
  CommentRead,
  ListCommentsApiV1CommentsGetParams,
  MentionSuggestion,
  RecentActivityEntry,
  RecentCommentsApiV1CommentsRecentGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { castQueryFn } from "@/lib/query-utils";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useComments = (
  params: ListCommentsApiV1CommentsGetParams,
  options?: QueryOpts<CommentRead[]>
) => {
  return useQuery<CommentRead[]>({
    queryKey: getListCommentsApiV1CommentsGetQueryKey(params),
    queryFn: castQueryFn<CommentRead[]>(() => listCommentsApiV1CommentsGet(params)),
    ...options,
  });
};

export const useRecentComments = (
  params?: RecentCommentsApiV1CommentsRecentGetParams,
  options?: QueryOpts<RecentActivityEntry[]>
) => {
  return useQuery<RecentActivityEntry[]>({
    queryKey: getRecentCommentsApiV1CommentsRecentGetQueryKey(params),
    queryFn: castQueryFn<RecentActivityEntry[]>(() => recentCommentsApiV1CommentsRecentGet(params)),
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
  return useQuery<MentionSuggestion[]>({
    queryKey: getSearchMentionablesApiV1CommentsMentionsSearchGetQueryKey({
      entity_type: type,
      initiative_id: initiativeId,
      q: query,
    }),
    queryFn: castQueryFn<MentionSuggestion[]>(() =>
      searchMentionablesApiV1CommentsMentionsSearchGet({
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

export const useCommentsCache = (params: ListCommentsApiV1CommentsGetParams) => {
  const qc = useQueryClient();
  const queryKey = getListCommentsApiV1CommentsGetQueryKey(params);

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
  options?: MutationOpts<CommentRead, Parameters<typeof createCommentApiV1CommentsPost>[0]>
) => {
  const { t } = useTranslation("common");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof createCommentApiV1CommentsPost>[0]) => {
      return createCommentApiV1CommentsPost(data) as unknown as Promise<CommentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllComments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("error");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateComment = (
  options?: MutationOpts<
    CommentRead,
    { commentId: number; data: Parameters<typeof updateCommentApiV1CommentsCommentIdPatch>[1] }
  >
) => {
  const { t } = useTranslation("common");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      commentId,
      data,
    }: {
      commentId: number;
      data: Parameters<typeof updateCommentApiV1CommentsCommentIdPatch>[1];
    }) => {
      return updateCommentApiV1CommentsCommentIdPatch(
        commentId,
        data
      ) as unknown as Promise<CommentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllComments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("error");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteComment = (options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("common");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (commentId: number) => {
      await deleteCommentApiV1CommentsCommentIdDelete(commentId);
    },
    onSuccess: (...args) => {
      void invalidateAllComments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("error");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};
