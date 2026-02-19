import { useMutation } from "@tanstack/react-query";

import { updateProjectApiV1ProjectsProjectIdPatch } from "@/api/generated/projects/projects";
import {
  getListProjectsApiV1ProjectsGetQueryKey,
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
} from "@/api/generated/projects/projects";
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
      return updateProjectApiV1ProjectsProjectIdPatch(projectId, {
        pinned: nextState,
      }) as unknown as Promise<Project>;
    },
    onSuccess: (data) => {
      queryClient.setQueryData<Project[]>(getListProjectsApiV1ProjectsGetQueryKey(), (projects) =>
        replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<Project[]>(
        getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
        (projects) => replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<Project[]>(
        getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
        (projects) => replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<Project>(
        getReadProjectApiV1ProjectsProjectIdGetQueryKey(data.id) as unknown as string[],
        () => data
      );
    },
  });
