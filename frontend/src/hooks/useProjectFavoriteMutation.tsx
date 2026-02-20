import { useMutation } from "@tanstack/react-query";

import {
  favoriteProjectApiV1ProjectsProjectIdFavoritePost,
  unfavoriteProjectApiV1ProjectsProjectIdFavoriteDelete,
  getListProjectsApiV1ProjectsGetQueryKey,
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
  getFavoriteProjectsApiV1ProjectsFavoritesGetQueryKey,
} from "@/api/generated/projects/projects";
import { queryClient } from "../lib/queryClient";
import type { Project } from "../types/api";

interface ToggleArgs {
  projectId: number;
  nextState: boolean;
}

interface ToggleResponse {
  project_id: number;
  is_favorited: boolean;
}

const updateProjectListFavorite = (projects: Project[] | undefined, response: ToggleResponse) => {
  if (!projects) {
    return projects;
  }
  return projects.map((project) =>
    project.id === response.project_id
      ? { ...project, is_favorited: response.is_favorited }
      : project
  );
};

export const useProjectFavoriteMutation = () => {
  return useMutation<ToggleResponse, unknown, ToggleArgs>({
    mutationFn: async ({ projectId, nextState }) => {
      if (nextState) {
        await favoriteProjectApiV1ProjectsProjectIdFavoritePost(projectId);
      } else {
        await unfavoriteProjectApiV1ProjectsProjectIdFavoriteDelete(projectId);
      }
      return { project_id: projectId, is_favorited: nextState };
    },
    onSuccess: (data) => {
      queryClient.setQueryData<Project[]>(getListProjectsApiV1ProjectsGetQueryKey(), (projects) =>
        updateProjectListFavorite(projects, data)
      );
      queryClient.setQueryData<Project[]>(
        getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
        (projects) => updateProjectListFavorite(projects, data)
      );
      queryClient.setQueryData<Project[]>(
        getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
        (projects) => updateProjectListFavorite(projects, data)
      );
      queryClient.setQueryData<Project>(
        getReadProjectApiV1ProjectsProjectIdGetQueryKey(data.project_id) as unknown as string[],
        (project) => (project ? { ...project, is_favorited: data.is_favorited } : project)
      );
      queryClient.invalidateQueries({
        queryKey: getFavoriteProjectsApiV1ProjectsFavoritesGetQueryKey(),
      });
    },
  });
};
