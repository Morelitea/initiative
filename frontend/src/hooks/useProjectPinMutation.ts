import { useMutation } from "@tanstack/react-query";

import { updateProjectApiV1ProjectsProjectIdPatch } from "@/api/generated/projects/projects";
import {
  getListProjectsApiV1ProjectsGetQueryKey,
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
} from "@/api/generated/projects/projects";
import { queryClient } from "@/lib/queryClient";
import type { ProjectListResponse, ProjectRead } from "@/api/generated/initiativeAPI.schemas";

interface ToggleArgs {
  projectId: number;
  nextState: boolean;
}

const replaceProjectInList = (
  prev: ProjectListResponse | undefined,
  updated: ProjectRead
): ProjectListResponse | undefined => {
  if (!prev) {
    return prev;
  }
  return {
    ...prev,
    items: prev.items.map((project) => (project.id === updated.id ? updated : project)),
  };
};

export const useProjectPinMutation = () =>
  useMutation<ProjectRead, unknown, ToggleArgs>({
    mutationFn: async ({ projectId, nextState }) => {
      return updateProjectApiV1ProjectsProjectIdPatch(projectId, {
        pinned: nextState,
      }) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (data) => {
      queryClient.setQueryData<ProjectListResponse>(
        getListProjectsApiV1ProjectsGetQueryKey(),
        (prev) => replaceProjectInList(prev, data)
      );
      queryClient.setQueryData<ProjectListResponse>(
        getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
        (prev) => replaceProjectInList(prev, data)
      );
      queryClient.setQueryData<ProjectListResponse>(
        getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
        (prev) => replaceProjectInList(prev, data)
      );
      queryClient.setQueryData<ProjectRead>(
        getReadProjectApiV1ProjectsProjectIdGetQueryKey(data.id) as unknown as string[],
        () => data
      );
    },
  });
