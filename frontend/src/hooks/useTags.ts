import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  TagCreate,
  TaggedEntitiesResponse,
  TagRead,
  TagUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createTag,
  deleteTag,
  getGetTagEntitiesQueryKey,
  getGetTagQueryKey,
  getListTagsQueryKey,
  getTag,
  getTagEntities,
  listTags,
  updateTag,
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
    queryKey: getListTagsQueryKey(guildId),
    queryFn: () => listTags(guildId),
    staleTime: 60 * 1000,
    enabled: options?.enabled ?? true,
  });
};

export const useTag = (tagId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<TagRead>({
    queryKey: getGetTagQueryKey(guildId, tagId!),
    queryFn: () => getTag(guildId, tagId!),
    enabled: !!tagId,
    staleTime: 60 * 1000,
  });
};

export const useCreateTag = (options?: MutationOpts<TagRead, TagCreate>) =>
  useGuildMutation<TagRead, TagCreate>(
    {
      mutationFn: (guildId, data) => createTag(guildId, data),
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
      return updateTag(guildId, tagId, data);
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
      await deleteTag(guildId, tagId);
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
    queryKey: getGetTagEntitiesQueryKey(guildId, tagId!),
    queryFn: () => getTagEntities(guildId, tagId!),
    enabled: !!tagId,
    staleTime: 30 * 1000,
  });
};
