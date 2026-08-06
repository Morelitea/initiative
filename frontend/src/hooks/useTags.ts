import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  TagCreate,
  TaggedEntitiesResponse,
  TagRead,
  TagUpdate,
  TaskRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createTagApiV1GGuildIdTagsPost,
  deleteTagApiV1GGuildIdTagsTagIdDelete,
  getGetTagApiV1GGuildIdTagsTagIdGetQueryKey,
  getGetTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGetQueryKey,
  getListTagsApiV1GGuildIdTagsGetQueryKey,
  getTagApiV1GGuildIdTagsTagIdGet,
  getTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGet,
  listTagsApiV1GGuildIdTagsGet,
  updateTagApiV1GGuildIdTagsTagIdPatch,
} from "@/api/generated/tags/tags";
import { setTaskTagsApiV1GGuildIdTasksTaskIdTagsPut } from "@/api/generated/tasks/tasks";
import {
  invalidateAllAdvancedTools,
  invalidateAllCalendars,
  invalidateAllCounterGroups,
  invalidateAllDocuments,
  invalidateAllProjects,
  invalidateAllQueues,
  invalidateAllTags,
  invalidateAllTasks,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";

/** Refresh every list that embeds TagSummary chips — a rename/recolor or
 * delete must reach all of them, not just the tags list. */
const invalidateTagBearers = () => {
  void invalidateAllTasks();
  void invalidateAllProjects();
  void invalidateAllDocuments();
  void invalidateAllQueues();
  void invalidateAllCounterGroups();
  void invalidateAllCalendars();
  void invalidateAllAdvancedTools();
};

export const useTags = (options?: { enabled?: boolean }) => {
  const guildId = useActiveGuildId();
  return useQuery<TagRead[]>({
    queryKey: getListTagsApiV1GGuildIdTagsGetQueryKey(guildId),
    queryFn: () => listTagsApiV1GGuildIdTagsGet(guildId),
    staleTime: 60 * 1000,
    enabled: options?.enabled ?? true,
  });
};

export const useTag = (tagId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<TagRead>({
    queryKey: getGetTagApiV1GGuildIdTagsTagIdGetQueryKey(guildId, tagId!),
    queryFn: () => getTagApiV1GGuildIdTagsTagIdGet(guildId, tagId!),
    enabled: !!tagId,
    staleTime: 60 * 1000,
  });
};

export const useCreateTag = (options?: MutationOpts<TagRead, TagCreate>) =>
  useGuildMutation<TagRead, TagCreate>(
    {
      mutationFn: (guildId, data) => createTagApiV1GGuildIdTagsPost(guildId, data),
      invalidate: () => invalidateAllTags(),
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
      return updateTagApiV1GGuildIdTagsTagIdPatch(guildId, tagId, data);
    },
    onSuccess: (...args) => {
      toast.success(t("updated"));
      void invalidateAllTags();
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
      await deleteTagApiV1GGuildIdTagsTagIdDelete(guildId, tagId);
    },
    onSuccess: (...args) => {
      if (!silent) {
        toast.success(t("deleted"));
      }
      void invalidateAllTags();
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

export const useSetTaskTags = (
  options?: MutationOpts<TaskRead, { taskId: number; tagIds: number[] }>
) =>
  useGuildMutation<TaskRead, { taskId: number; tagIds: number[] }>(
    {
      mutationFn: (guildId, { taskId, tagIds }) =>
        setTaskTagsApiV1GGuildIdTasksTaskIdTagsPut(guildId, taskId, {
          tag_ids: tagIds,
        }),
      invalidate: () => invalidateAllTasks(),
      errorKey: "tags:taskTagsError",
    },
    options
  );

export const useTagEntities = (tagId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<TaggedEntitiesResponse>({
    queryKey: getGetTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGetQueryKey(guildId, tagId!),
    queryFn: () => getTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGet(guildId, tagId!),
    enabled: !!tagId,
    staleTime: 30 * 1000,
  });
};
