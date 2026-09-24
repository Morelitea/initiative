import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  TagCreate,
  TaggedEntitiesResponse,
  TagRead,
  TagUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createTagApiV1CGuildIdTagsPost,
  deleteTagApiV1CGuildIdTagsTagIdDelete,
  getGetTagApiV1CGuildIdTagsTagIdGetQueryKey,
  getGetTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGetQueryKey,
  getListTagsApiV1CGuildIdTagsGetQueryKey,
  getTagApiV1CGuildIdTagsTagIdGet,
  getTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGet,
  listTagsApiV1CGuildIdTagsGet,
  updateTagApiV1CGuildIdTagsTagIdPatch,
} from "@/api/generated/tags/tags";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";

/** Refresh every list that embeds TagSummary chips — a rename/recolor or
 * delete must reach all of them, not just the tags list. */
const invalidateTagBearers = () => {
  void invalidate(
    q.allTasks(),
    q.allProjects(),
    q.allDocuments(),
    q.allQueues(),
    q.allCounterGroups(),
    q.allCalendars()
  );
};

export const useTags = (options?: { enabled?: boolean }) => {
  const guildId = useActiveGuildId();
  return useQuery<TagRead[]>({
    queryKey: getListTagsApiV1CGuildIdTagsGetQueryKey(guildId),
    queryFn: () => listTagsApiV1CGuildIdTagsGet(guildId),
    staleTime: 60 * 1000,
    enabled: options?.enabled ?? true,
  });
};

export const useTag = (tagId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<TagRead>({
    queryKey: getGetTagApiV1CGuildIdTagsTagIdGetQueryKey(guildId, tagId!),
    queryFn: () => getTagApiV1CGuildIdTagsTagIdGet(guildId, tagId!),
    enabled: !!tagId,
    staleTime: 60 * 1000,
  });
};

export const useCreateTag = (options?: MutationOpts<TagRead, TagCreate>) =>
  useGuildMutation<TagRead, TagCreate>(
    {
      mutationFn: (guildId, data) => createTagApiV1CGuildIdTagsPost(guildId, data),
      invalidate: () => invalidate(q.allTags()),
      errorKey: "tags:createError",
    },
    options
  );

export const useUpdateTag = (
  options?: MutationOpts<TagRead, { tagId: number; data: TagUpdate }>
) => {
  const guildId = useActiveGuildId();
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ tagId, data }: { tagId: number; data: TagUpdate }) => {
      return updateTagApiV1CGuildIdTagsTagIdPatch(guildId, tagId, data);
    },
    onSuccess: (...args) => {
      toast.success(t("updated"));
      void invalidate(q.allTags());
      invalidateTagBearers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tags:updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteTag = (
  options?: MutationOpts<void, number> & {
    /** Skip the per-delete success toast — for batch callers that show one
     * summary toast instead. Error toasts still fire per tag. */
    silent?: boolean;
  }
) => {
  const guildId = useActiveGuildId();
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, silent, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (tagId: number) => {
      await deleteTagApiV1CGuildIdTagsTagIdDelete(guildId, tagId);
    },
    onSuccess: (...args) => {
      if (!silent) {
        toast.success(t("deleted"));
      }
      void invalidate(q.allTags());
      invalidateTagBearers();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tags:deleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useTagEntities = (tagId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<TaggedEntitiesResponse>({
    queryKey: getGetTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGetQueryKey(guildId, tagId!),
    queryFn: () => getTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGet(guildId, tagId!),
    enabled: !!tagId,
    staleTime: 30 * 1000,
  });
};
