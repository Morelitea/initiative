import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { useGuilds } from "@/hooks/useGuilds";
import type {
  DocumentRead,
  Project,
  Tag,
  TagCreate,
  TagUpdate,
  TaggedEntitiesResponse,
  Task,
} from "@/types/api";

const TAGS_KEY = "tags";
const TASKS_KEY = "tasks";
const PROJECTS_KEY = "projects";
const DOCUMENTS_KEY = "documents";

export const useTags = () => {
  const { activeGuildId } = useGuilds();
  return useQuery<Tag[]>({
    queryKey: [TAGS_KEY, { guildId: activeGuildId }],
    queryFn: async () => {
      const response = await apiClient.get<Tag[]>("/tags/");
      return response.data;
    },
    staleTime: 60 * 1000, // 1 minute
  });
};

export const useTag = (tagId: number | null) => {
  const { activeGuildId } = useGuilds();
  return useQuery<Tag>({
    queryKey: [TAGS_KEY, { guildId: activeGuildId }, tagId],
    queryFn: async () => {
      const response = await apiClient.get<Tag>(`/tags/${tagId}`);
      return response.data;
    },
    enabled: !!tagId,
    staleTime: 60 * 1000,
  });
};

export const useCreateTag = () => {
  const { t } = useTranslation("tags");
  const queryClient = useQueryClient();
  const { activeGuildId } = useGuilds();

  return useMutation({
    mutationFn: async (data: TagCreate) => {
      const response = await apiClient.post<Tag>("/tags/", data);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [TAGS_KEY, { guildId: activeGuildId }] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("createError");
      toast.error(message);
    },
  });
};

export const useUpdateTag = () => {
  const { t } = useTranslation("tags");
  const queryClient = useQueryClient();
  const { activeGuildId } = useGuilds();

  return useMutation({
    mutationFn: async ({ tagId, data }: { tagId: number; data: TagUpdate }) => {
      const response = await apiClient.patch<Tag>(`/tags/${tagId}`, data);
      return response.data;
    },
    onSuccess: () => {
      toast.success(t("updated"));
      void queryClient.invalidateQueries({ queryKey: [TAGS_KEY, { guildId: activeGuildId }] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("updateError");
      toast.error(message);
    },
  });
};

export const useDeleteTag = () => {
  const { t } = useTranslation("tags");
  const queryClient = useQueryClient();
  const { activeGuildId } = useGuilds();

  return useMutation({
    mutationFn: async (tagId: number) => {
      await apiClient.delete(`/tags/${tagId}`);
    },
    onSuccess: () => {
      toast.success(t("deleted"));
      void queryClient.invalidateQueries({ queryKey: [TAGS_KEY, { guildId: activeGuildId }] });
      // Also invalidate tasks since they may have had this tag
      void queryClient.invalidateQueries({ queryKey: [TASKS_KEY] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("deleteError");
      toast.error(message);
    },
  });
};

export const useSetTaskTags = () => {
  const { t } = useTranslation("tags");
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ taskId, tagIds }: { taskId: number; tagIds: number[] }) => {
      const response = await apiClient.put<Task>(`/tasks/${taskId}/tags`, {
        tag_ids: tagIds,
      });
      return response.data;
    },
    onSuccess: (data) => {
      // Update the specific task in cache
      void queryClient.invalidateQueries({
        queryKey: [TASKS_KEY],
      });
      // Also invalidate the single task query if it exists
      void queryClient.invalidateQueries({
        queryKey: ["task", data.id],
      });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("taskTagsError");
      toast.error(message);
    },
  });
};

export const useTagEntities = (tagId: number | null) => {
  const { activeGuildId } = useGuilds();
  return useQuery<TaggedEntitiesResponse>({
    queryKey: [TAGS_KEY, { guildId: activeGuildId }, tagId, "entities"],
    queryFn: async () => {
      const response = await apiClient.get<TaggedEntitiesResponse>(`/tags/${tagId}/entities`);
      return response.data;
    },
    enabled: !!tagId,
    staleTime: 30 * 1000, // 30 seconds
  });
};

export const useSetProjectTags = () => {
  const { t } = useTranslation("tags");
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ projectId, tagIds }: { projectId: number; tagIds: number[] }) => {
      const response = await apiClient.put<Project>(`/projects/${projectId}/tags`, {
        tag_ids: tagIds,
      });
      return response.data;
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: [PROJECTS_KEY] });
      void queryClient.invalidateQueries({ queryKey: ["project", data.id] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("projectTagsError");
      toast.error(message);
    },
  });
};

export const useSetDocumentTags = () => {
  const { t } = useTranslation("tags");
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ documentId, tagIds }: { documentId: number; tagIds: number[] }) => {
      const response = await apiClient.put<DocumentRead>(`/documents/${documentId}/tags`, {
        tag_ids: tagIds,
      });
      return response.data;
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: [DOCUMENTS_KEY] });
      void queryClient.invalidateQueries({ queryKey: ["document", data.id] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("documentTagsError");
      toast.error(message);
    },
  });
};
