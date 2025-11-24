import { useMutation } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { queryClient } from '../lib/queryClient';
import type { Project } from '../types/api';

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
    project.id === response.project_id ? { ...project, is_favorited: response.is_favorited } : project
  );
};

export const useProjectFavoriteMutation = () =>
  useMutation<ToggleResponse, unknown, ToggleArgs>({
    mutationFn: async ({ projectId, nextState }) => {
      if (nextState) {
        await apiClient.post(`/projects/${projectId}/favorite`);
      } else {
        await apiClient.delete(`/projects/${projectId}/favorite`);
      }
      return { project_id: projectId, is_favorited: nextState };
    },
    onSuccess: (data) => {
      queryClient.setQueryData<Project[]>(['projects'], (projects) => updateProjectListFavorite(projects, data));
      queryClient.setQueryData<Project[]>(['projects', 'templates'], (projects) =>
        updateProjectListFavorite(projects, data)
      );
      queryClient.setQueryData<Project[]>(['projects', 'archived'], (projects) =>
        updateProjectListFavorite(projects, data)
      );
      queryClient.setQueryData<Project>(['projects', data.project_id], (project) =>
        project ? { ...project, is_favorited: data.is_favorited } : project
      );
      queryClient.invalidateQueries({ queryKey: ['projects', 'favorites'] });
    },
  });
