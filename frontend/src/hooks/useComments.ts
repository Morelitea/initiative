import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listCommentsApiV1CommentsGet,
  getListCommentsApiV1CommentsGetQueryKey,
  recentCommentsApiV1CommentsRecentGet,
  getRecentCommentsApiV1CommentsRecentGetQueryKey,
  createCommentApiV1CommentsPost,
  updateCommentApiV1CommentsCommentIdPatch,
  deleteCommentApiV1CommentsCommentIdDelete,
} from "@/api/generated/comments/comments";
import { invalidateAllComments } from "@/api/query-keys";
import type { Comment } from "@/types/api";
import type {
  ListCommentsApiV1CommentsGetParams,
  RecentCommentsApiV1CommentsRecentGetParams,
  RecentActivityEntry,
} from "@/api/generated/initiativeAPI.schemas";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useComments = (
  params: ListCommentsApiV1CommentsGetParams,
  options?: { enabled?: boolean }
) => {
  return useQuery<Comment[]>({
    queryKey: getListCommentsApiV1CommentsGetQueryKey(params),
    queryFn: () => listCommentsApiV1CommentsGet(params) as unknown as Promise<Comment[]>,
    enabled: options?.enabled,
  });
};

export const useRecentComments = (params?: RecentCommentsApiV1CommentsRecentGetParams) => {
  return useQuery<RecentActivityEntry[]>({
    queryKey: getRecentCommentsApiV1CommentsRecentGetQueryKey(params),
    queryFn: () =>
      recentCommentsApiV1CommentsRecentGet(params) as unknown as Promise<RecentActivityEntry[]>,
    staleTime: 30 * 1000,
  });
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
