import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import type { Tag, TagCreate, TagUpdate, Task } from "@/types/api";

const TAGS_KEY = "tags";
const TASKS_KEY = "tasks";

export const useTags = () => {
  return useQuery<Tag[]>({
    queryKey: [TAGS_KEY],
    queryFn: async () => {
      const response = await apiClient.get<Tag[]>("/tags/");
      return response.data;
    },
    staleTime: 60 * 1000, // 1 minute
  });
};

export const useTag = (tagId: number | null) => {
  return useQuery<Tag>({
    queryKey: [TAGS_KEY, tagId],
    queryFn: async () => {
      const response = await apiClient.get<Tag>(`/tags/${tagId}`);
      return response.data;
    },
    enabled: !!tagId,
    staleTime: 60 * 1000,
  });
};

export const useCreateTag = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: TagCreate) => {
      const response = await apiClient.post<Tag>("/tags/", data);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [TAGS_KEY] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to create tag.";
      toast.error(message);
    },
  });
};

export const useUpdateTag = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ tagId, data }: { tagId: number; data: TagUpdate }) => {
      const response = await apiClient.patch<Tag>(`/tags/${tagId}`, data);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Tag updated.");
      void queryClient.invalidateQueries({ queryKey: [TAGS_KEY] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to update tag.";
      toast.error(message);
    },
  });
};

export const useDeleteTag = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (tagId: number) => {
      await apiClient.delete(`/tags/${tagId}`);
    },
    onSuccess: () => {
      toast.success("Tag deleted.");
      void queryClient.invalidateQueries({ queryKey: [TAGS_KEY] });
      // Also invalidate tasks since they may have had this tag
      void queryClient.invalidateQueries({ queryKey: [TASKS_KEY] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to delete tag.";
      toast.error(message);
    },
  });
};

export const useSetTaskTags = () => {
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
      const message = error instanceof Error ? error.message : "Unable to update task tags.";
      toast.error(message);
    },
  });
};
