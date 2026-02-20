import { useMutation } from "@tanstack/react-query";

import { updateProjectApiV1ProjectsProjectIdPatch } from "@/api/generated/projects/projects";
import {
  getListProjectsApiV1ProjectsGetQueryKey,
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
} from "@/api/generated/projects/projects";
import { queryClient } from "@/lib/queryClient";
import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";

interface ToggleArgs {
  projectId: number;
  nextState: boolean;
}

const replaceProjectInList = (projects: ProjectRead[] | undefined, updated: ProjectRead) => {
  if (!projects) {
    return projects;
  }
  return projects.map((project) => (project.id === updated.id ? updated : project));
};

export const useProjectPinMutation = () =>
  useMutation<ProjectRead, unknown, ToggleArgs>({
    mutationFn: async ({ projectId, nextState }) => {
      return updateProjectApiV1ProjectsProjectIdPatch(projectId, {
        pinned: nextState,
      }) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (data) => {
      queryClient.setQueryData<ProjectRead[]>(
        getListProjectsApiV1ProjectsGetQueryKey(),
        (projects) => replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<ProjectRead[]>(
        getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
        (projects) => replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<ProjectRead[]>(
        getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
        (projects) => replaceProjectInList(projects, data)
      );
      queryClient.setQueryData<ProjectRead>(
        getReadProjectApiV1ProjectsProjectIdGetQueryKey(data.id) as unknown as string[],
        () => data
      );
    },
  });
