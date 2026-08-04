import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

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
import { useGuildMutation } from "@/hooks/useApiMutation";
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
    queryFn: () => listCommentsApiV1GGuildIdCommentsGet(guildId, params),
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
    queryFn: () => recentCommentsApiV1GGuildIdCommentsRecentGet(guildId, params),
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
    // The endpoint returns a paginated envelope; the pickers only need the
    // first page's items.
    queryFn: async () => {
      const res = await searchMentionablesApiV1GGuildIdCommentsMentionsSearchGet(guildId, {
        entity_type: type,
        initiative_id: initiativeId,
        q: query,
      });
      return res.items ?? [];
    },
    staleTime: 30_000,
    enabled: initiativeId > 0,
    // Keep the prior page visible while the next keystroke's request is in
    // flight so the dropdown doesn't flash empty on every character.
    placeholderData: keepPreviousData,
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
) =>
  useGuildMutation<CommentRead, Parameters<typeof createCommentApiV1GGuildIdCommentsPost>[1]>(
    {
      mutationFn: (guildId, data) => createCommentApiV1GGuildIdCommentsPost(guildId, data),
      invalidate: () => invalidateAllComments(),
      errorKey: "common:error",
    },
    options
  );

export const useUpdateComment = (
  options?: MutationOpts<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateCommentApiV1GGuildIdCommentsCommentIdPatch>[2];
    }
  >
) =>
  useGuildMutation<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateCommentApiV1GGuildIdCommentsCommentIdPatch>[2];
    }
  >(
    {
      mutationFn: (guildId, { commentId, data }) =>
        updateCommentApiV1GGuildIdCommentsCommentIdPatch(guildId, commentId, data),
      invalidate: () => invalidateAllComments(),
      errorKey: "common:error",
    },
    options
  );

export const useDeleteComment = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, commentId) =>
        deleteCommentApiV1GGuildIdCommentsCommentIdDelete(guildId, commentId),
      invalidate: () => invalidateAllComments(),
      errorKey: "common:error",
    },
    options
  );
