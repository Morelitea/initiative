import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/api/client";
import { queryClient } from "@/lib/queryClient";
import type { Project } from "@/types/api";

interface ToggleArgs {
  projectId: number;
  nextState: boolean;
}

const replaceProjectInList = (projects: Project[] | undefined, updated: Project) => {
  if (!projects) {
    return projects;
  }
  return projects.map((project) => (project.id === updated.id ? updated : project));
};

export const useProjectPinMutation = () =>
  useMutation<Project, unknown, ToggleArgs>({
    mutationFn: async ({ projectId, nextState }) => {
      const response = await apiClient.patch<Project>(`/projects/${projectId}`, {
        pinned: nextState,
      });
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData<Project[]>(["projects"], (projects) =>
        replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<Project[]>(["projects", "templates"], (projects) =>
        replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<Project[]>(["projects", "archived"], (projects) =>
        replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<Project>(["projects", data.id], () => data);
    },
  });
