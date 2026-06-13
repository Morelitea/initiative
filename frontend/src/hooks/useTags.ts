import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { setDocumentTagsApiV1GGuildIdDocumentsDocumentIdTagsPut } from "@/api/generated/documents/documents";
import type {
  DocumentRead,
  ProjectRead,
  TagCreate,
  TaggedEntitiesResponse,
  TagRead,
  TagUpdate,
  TaskListRead,
} from "@/api/generated/initiativeAPI.schemas";
import { setProjectTagsApiV1GGuildIdProjectsProjectIdTagsPut } from "@/api/generated/projects/projects";
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
  invalidateAllDocuments,
  invalidateAllProjects,
  invalidateAllTags,
  invalidateAllTasks,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";

export const useTags = (options?: { enabled?: boolean }) => {
  const guildId = useActiveGuildId();
  return useQuery<TagRead[]>({
    queryKey: getListTagsApiV1GGuildIdTagsGetQueryKey(guildId),
    queryFn: () => listTagsApiV1GGuildIdTagsGet(guildId) as unknown as Promise<TagRead[]>,
    staleTime: 60 * 1000,
    enabled: options?.enabled ?? true,
  });
};

export const useTag = (tagId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<TagRead>({
    queryKey: getGetTagApiV1GGuildIdTagsTagIdGetQueryKey(guildId, tagId!),
    queryFn: () => getTagApiV1GGuildIdTagsTagIdGet(guildId, tagId!) as unknown as Promise<TagRead>,
    enabled: !!tagId,
    staleTime: 60 * 1000,
  });
};

export const useCreateTag = (options?: MutationOpts<TagRead, TagCreate>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: TagCreate) => {
      return createTagApiV1GGuildIdTagsPost(guildId, data) as unknown as Promise<TagRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTags();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tags:createError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateTag = (
  options?: MutationOpts<TagRead, { tagId: number; data: TagUpdate }>
) => {
  const guildId = useActiveGuildId();
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ tagId, data }: { tagId: number; data: TagUpdate }) => {
      return updateTagApiV1GGuildIdTagsTagIdPatch(
        guildId,
        tagId,
        data
      ) as unknown as Promise<TagRead>;
    },
    onSuccess: (...args) => {
      toast.success(t("updated"));
      void invalidateAllTags();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tags:updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteTag = (options?: MutationOpts<void, number>) => {
  const guildId = useActiveGuildId();
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (tagId: number) => {
      await deleteTagApiV1GGuildIdTagsTagIdDelete(guildId, tagId);
    },
    onSuccess: (...args) => {
      toast.success(t("deleted"));
      void invalidateAllTags();
      void invalidateAllTasks();
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
  options?: MutationOpts<TaskListRead, { taskId: number; tagIds: number[] }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ taskId, tagIds }: { taskId: number; tagIds: number[] }) => {
      return setTaskTagsApiV1GGuildIdTasksTaskIdTagsPut(guildId, taskId, {
        tag_ids: tagIds,
      }) as unknown as Promise<TaskListRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tags:taskTagsError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useTagEntities = (tagId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<TaggedEntitiesResponse>({
    queryKey: getGetTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGetQueryKey(guildId, tagId!),
    queryFn: () =>
      getTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGet(
        guildId,
        tagId!
      ) as unknown as Promise<TaggedEntitiesResponse>,
    enabled: !!tagId,
    staleTime: 30 * 1000,
  });
};

export const useSetProjectTags = (
  options?: MutationOpts<ProjectRead, { projectId: number; tagIds: number[] }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, tagIds }: { projectId: number; tagIds: number[] }) => {
      return setProjectTagsApiV1GGuildIdProjectsProjectIdTagsPut(guildId, projectId, {
        tag_ids: tagIds,
      }) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tags:projectTagsError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetDocumentTags = (
  options?: MutationOpts<DocumentRead, { documentId: number; tagIds: number[] }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, tagIds }: { documentId: number; tagIds: number[] }) => {
      return setDocumentTagsApiV1GGuildIdDocumentsDocumentIdTagsPut(guildId, documentId, {
        tag_ids: tagIds,
      }) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "tags:documentTagsError"));
      onError?.(...args);
    },
    onSettled,
  });
};
