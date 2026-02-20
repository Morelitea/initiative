import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
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
import type { Comment, MentionEntityType } from "@/types/api";
import type {
  ListCommentsApiV1CommentsGetParams,
  RecentCommentsApiV1CommentsRecentGetParams,
  RecentActivityEntry,
  MentionSuggestion,
} from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useComments = (
  params: ListCommentsApiV1CommentsGetParams,
  options?: QueryOpts<Comment[]>
) => {
  return useQuery<Comment[]>({
    queryKey: getListCommentsApiV1CommentsGetQueryKey(params),
    queryFn: () => listCommentsApiV1CommentsGet(params) as unknown as Promise<Comment[]>,
    ...options,
  });
};

export const useRecentComments = (
  params?: RecentCommentsApiV1CommentsRecentGetParams,
  options?: QueryOpts<RecentActivityEntry[]>
) => {
  return useQuery<RecentActivityEntry[]>({
    queryKey: getRecentCommentsApiV1CommentsRecentGetQueryKey(params),
    queryFn: () =>
      recentCommentsApiV1CommentsRecentGet(params) as unknown as Promise<RecentActivityEntry[]>,
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
    queryFn: () =>
      searchMentionablesApiV1CommentsMentionsSearchGet({
        entity_type: type,
        initiative_id: initiativeId,
        q: query,
      }) as unknown as Promise<MentionSuggestion[]>,
    staleTime: 30_000,
    enabled: initiativeId > 0,
    ...options,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

export const useCommentsCache = (params: ListCommentsApiV1CommentsGetParams) => {
  const qc = useQueryClient();
  const queryKey = getListCommentsApiV1CommentsGetQueryKey(params);

  const addComment = (comment: Comment) => {
    qc.setQueryData<Comment[]>(queryKey, (prev) => (prev ? [...prev, comment] : [comment]));
  };

  const removeComment = (commentId: number) => {
    qc.setQueryData<Comment[]>(queryKey, (prev) => prev?.filter((c) => c.id !== commentId));
  };

  const updateComment = (updated: Comment) => {
    qc.setQueryData<Comment[]>(queryKey, (prev) =>
      prev?.map((c) => (c.id === updated.id ? updated : c))
    );
  };

  return { addComment, removeComment, updateComment };
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateComment = () => {
  const { t } = useTranslation("common");

  return useMutation({
    mutationFn: async (data: Parameters<typeof createCommentApiV1CommentsPost>[0]) => {
      return createCommentApiV1CommentsPost(data) as unknown as Promise<Comment>;
    },
    onSuccess: () => {
      void invalidateAllComments();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("error");
      toast.error(message);
    },
  });
};

export const useUpdateComment = () => {
  const { t } = useTranslation("common");

  return useMutation({
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
      ) as unknown as Promise<Comment>;
    },
    onSuccess: () => {
      void invalidateAllComments();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("error");
      toast.error(message);
    },
  });
};

export const useDeleteComment = () => {
  const { t } = useTranslation("common");

  return useMutation({
    mutationFn: async (commentId: number) => {
      await deleteCommentApiV1CommentsCommentIdDelete(commentId);
    },
    onSuccess: () => {
      void invalidateAllComments();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("error");
      toast.error(message);
    },
  });
};
