import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listTagsApiV1TagsGet,
  getListTagsApiV1TagsGetQueryKey,
  getTagApiV1TagsTagIdGet,
  getGetTagApiV1TagsTagIdGetQueryKey,
  createTagApiV1TagsPost,
  updateTagApiV1TagsTagIdPatch,
  deleteTagApiV1TagsTagIdDelete,
  getTagEntitiesApiV1TagsTagIdEntitiesGet,
  getGetTagEntitiesApiV1TagsTagIdEntitiesGetQueryKey,
} from "@/api/generated/tags/tags";
import { setTaskTagsApiV1TasksTaskIdTagsPut } from "@/api/generated/tasks/tasks";
import { setProjectTagsApiV1ProjectsProjectIdTagsPut } from "@/api/generated/projects/projects";
import { setDocumentTagsApiV1DocumentsDocumentIdTagsPut } from "@/api/generated/documents/documents";
import {
  invalidateAllTags,
  invalidateAllTasks,
  invalidateAllProjects,
  invalidateAllDocuments,
} from "@/api/query-keys";
import type {
  DocumentRead,
  ProjectRead,
  TagCreate,
  TagRead,
  TagUpdate,
  TaggedEntitiesResponse,
  TaskListRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";

export const useTags = () => {
  return useQuery<TagRead[]>({
    queryKey: getListTagsApiV1TagsGetQueryKey(),
    queryFn: () => listTagsApiV1TagsGet() as unknown as Promise<TagRead[]>,
    staleTime: 60 * 1000,
  });
};

export const useTag = (tagId: number | null) => {
  return useQuery<TagRead>({
    queryKey: getGetTagApiV1TagsTagIdGetQueryKey(tagId!),
    queryFn: () => getTagApiV1TagsTagIdGet(tagId!) as unknown as Promise<TagRead>,
    enabled: !!tagId,
    staleTime: 60 * 1000,
  });
};

export const useCreateTag = (options?: MutationOpts<TagRead, TagCreate>) => {
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: TagCreate) => {
      return createTagApiV1TagsPost(data) as unknown as Promise<TagRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTags();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("createError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateTag = (
  options?: MutationOpts<TagRead, { tagId: number; data: TagUpdate }>
) => {
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ tagId, data }: { tagId: number; data: TagUpdate }) => {
      return updateTagApiV1TagsTagIdPatch(tagId, data) as unknown as Promise<TagRead>;
    },
    onSuccess: (...args) => {
      toast.success(t("updated"));
      void invalidateAllTags();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("updateError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteTag = (options?: MutationOpts<void, number>) => {
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (tagId: number) => {
      await deleteTagApiV1TagsTagIdDelete(tagId);
    },
    onSuccess: (...args) => {
      toast.success(t("deleted"));
      void invalidateAllTags();
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("deleteError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetTaskTags = (
  options?: MutationOpts<TaskListRead, { taskId: number; tagIds: number[] }>
) => {
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ taskId, tagIds }: { taskId: number; tagIds: number[] }) => {
      return setTaskTagsApiV1TasksTaskIdTagsPut(taskId, {
        tag_ids: tagIds,
      }) as unknown as Promise<TaskListRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("taskTagsError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useTagEntities = (tagId: number | null) => {
  return useQuery<TaggedEntitiesResponse>({
    queryKey: getGetTagEntitiesApiV1TagsTagIdEntitiesGetQueryKey(tagId!),
    queryFn: () =>
      getTagEntitiesApiV1TagsTagIdEntitiesGet(tagId!) as unknown as Promise<TaggedEntitiesResponse>,
    enabled: !!tagId,
    staleTime: 30 * 1000,
  });
};

export const useSetProjectTags = (
  options?: MutationOpts<ProjectRead, { projectId: number; tagIds: number[] }>
) => {
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, tagIds }: { projectId: number; tagIds: number[] }) => {
      return setProjectTagsApiV1ProjectsProjectIdTagsPut(projectId, {
        tag_ids: tagIds,
      }) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("projectTagsError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};

export const useSetDocumentTags = (
  options?: MutationOpts<DocumentRead, { documentId: number; tagIds: number[] }>
) => {
  const { t } = useTranslation("tags");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ documentId, tagIds }: { documentId: number; tagIds: number[] }) => {
      return setDocumentTagsApiV1DocumentsDocumentIdTagsPut(documentId, {
        tag_ids: tagIds,
      }) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("documentTagsError");
      toast.error(message);
      onError?.(...args);
    },
    onSettled,
  });
};
