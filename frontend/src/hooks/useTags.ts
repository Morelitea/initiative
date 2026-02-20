import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export const useCreateTag = () => {
  const { t } = useTranslation("tags");
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: TagCreate) => {
      return createTagApiV1TagsPost(data) as unknown as Promise<TagRead>;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: getListTagsApiV1TagsGetQueryKey() });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("createError");
      toast.error(message);
    },
  });
};

export const useUpdateTag = () => {
  const { t } = useTranslation("tags");

  return useMutation({
    mutationFn: async ({ tagId, data }: { tagId: number; data: TagUpdate }) => {
      return updateTagApiV1TagsTagIdPatch(tagId, data) as unknown as Promise<TagRead>;
    },
    onSuccess: () => {
      toast.success(t("updated"));
      void invalidateAllTags();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("updateError");
      toast.error(message);
    },
  });
};

export const useDeleteTag = () => {
  const { t } = useTranslation("tags");

  return useMutation({
    mutationFn: async (tagId: number) => {
      await deleteTagApiV1TagsTagIdDelete(tagId);
    },
    onSuccess: () => {
      toast.success(t("deleted"));
      void invalidateAllTags();
      void invalidateAllTasks();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("deleteError");
      toast.error(message);
    },
  });
};

export const useSetTaskTags = () => {
  const { t } = useTranslation("tags");

  return useMutation({
    mutationFn: async ({ taskId, tagIds }: { taskId: number; tagIds: number[] }) => {
      return setTaskTagsApiV1TasksTaskIdTagsPut(taskId, {
        tag_ids: tagIds,
      }) as unknown as Promise<TaskListRead>;
    },
    onSuccess: () => {
      void invalidateAllTasks();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("taskTagsError");
      toast.error(message);
    },
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

export const useSetProjectTags = () => {
  const { t } = useTranslation("tags");

  return useMutation({
    mutationFn: async ({ projectId, tagIds }: { projectId: number; tagIds: number[] }) => {
      return setProjectTagsApiV1ProjectsProjectIdTagsPut(projectId, {
        tag_ids: tagIds,
      }) as unknown as Promise<ProjectRead>;
    },
    onSuccess: () => {
      void invalidateAllProjects();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("projectTagsError");
      toast.error(message);
    },
  });
};

export const useSetDocumentTags = () => {
  const { t } = useTranslation("tags");

  return useMutation({
    mutationFn: async ({ documentId, tagIds }: { documentId: number; tagIds: number[] }) => {
      return setDocumentTagsApiV1DocumentsDocumentIdTagsPut(documentId, {
        tag_ids: tagIds,
      }) as unknown as Promise<DocumentRead>;
    },
    onSuccess: () => {
      void invalidateAllDocuments();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("documentTagsError");
      toast.error(message);
    },
  });
};
