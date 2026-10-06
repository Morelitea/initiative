import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  ListMyProjectsParams,
  ProjectListResponse,
  ProjectRead,
  TaskStatusCreate,
  TaskStatusDeleteRequest,
  TaskStatusRead,
  TaskStatusReorderRequest,
  TaskStatusUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  favoriteProject,
  favoriteProjects,
  getFavoriteProjectsQueryKey,
  getListProjectsQueryKey,
  getReadProjectQueryKey,
  listProjects,
  reorderProjects,
  unfavoriteProject,
  updateProject,
} from "@/api/generated/projects/projects";
import {
  createTaskStatus,
  deleteTaskStatus,
  getListTaskStatusesQueryKey,
  listTaskStatuses,
  reorderTaskStatuses,
  updateTaskStatus,
} from "@/api/generated/task-statuses/task-statuses";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { toolViewParams } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard six ────────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const projects = TOOL_HOOKS[Tool.project];
export const useProjects = projects.useList;
export const useProject = projects.useDetail;
export const useUpdateProject = projects.useUpdate;
export const useCreateProject = projects.useCreate;
export const useDeleteProject = projects.useDelete;
export const useSetProjectGrants = projects.useSetGrants;

// ── Queries ─────────────────────────────────────────────────────────────────

/** Templates across every initiative the caller can see — the create dialog's
 *  "start from a template" picker, read once the dialog is open. */
export const useTemplateProjects = (open: boolean) =>
  useProjects({ is_template: true }, { enabled: open });

/** Every live project the reader may edit — where a task can be moved to; a
 *  template takes no tasks moved into it. Walks the list's windows, so no
 *  destination is left off a long list. */
export const useWritableProjects = (options?: QueryOpts<ProjectListResponse>) => {
  const communityId = useActiveCommunityId();
  const params = {
    writable: true,
    slim: true,
    page_size: 0,
    ...toolViewParams(Tool.project, "active"),
  };
  return useQuery<ProjectListResponse>({
    queryKey: getListProjectsQueryKey(communityId, params),
    queryFn: () => fetchAllPages(listProjects, communityId, params),
    staleTime: 60 * 1000,
    ...options,
  });
};

export const useFavoriteProjects = (options?: QueryOpts<ProjectRead[]>) => {
  const communityId = useActiveCommunityId();
  return useQuery<ProjectRead[]>({
    queryKey: getFavoriteProjectsQueryKey(communityId),
    queryFn: () => favoriteProjects(communityId),
    staleTime: 30 * 1000,
    ...options,
  });
};

export const useProjectTaskStatuses = (
  projectId: number | null,
  options?: QueryOpts<TaskStatusRead[]>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskStatusRead[]>({
    queryKey: getListTaskStatusesQueryKey(communityId, projectId!),
    queryFn: () => listTaskStatuses(communityId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

// ── Global (cross-community) queries ────────────────────────────────────────────

export const useGlobalProjects = (
  params?: ListMyProjectsParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  return useQuery<ProjectListResponse>({
    ...projects.myListQuery(params),
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useReorderProjects = (options?: MutationOpts<void, number[]>) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (orderedIds: number[]) => {
      await reorderProjects(communityId, { project_ids: orderedIds });
    },
    onSuccess,
    onError,
    onSettled: (...args) => {
      void invalidate(q.allProjects());
      onSettled?.(...args);
    },
  });
};

// ── Favorite / Pin Mutations ────────────────────────────────────────────────

interface ToggleFavoriteArgs {
  projectId: number;
  nextState: boolean;
}

interface ToggleFavoriteResponse {
  project_id: number;
  is_favorited: boolean;
}

const updateProjectListFavorite = (
  prev: ProjectListResponse | undefined,
  response: ToggleFavoriteResponse
): ProjectListResponse | undefined => {
  if (!prev) return prev;
  return {
    ...prev,
    items: prev.items.map((project) =>
      project.id === response.project_id
        ? { ...project, is_favorited: response.is_favorited }
        : project
    ),
  };
};

export const useToggleProjectFavorite = (
  options?: MutationOpts<ToggleFavoriteResponse, ToggleFavoriteArgs>
) => {
  const communityId = useActiveCommunityId();
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, nextState }: ToggleFavoriteArgs) => {
      if (nextState) {
        await favoriteProject(communityId, projectId);
      } else {
        await unfavoriteProject(communityId, projectId);
      }
      return { project_id: projectId, is_favorited: nextState };
    },
    onSuccess: (...args) => {
      const data = args[0];
      // Every cached project list, whatever it was narrowed by — the keys carry
      // an initiative and a page now, so naming them one by one silently misses
      // the list the reader is actually looking at.
      qc.setQueriesData<ProjectListResponse>(
        { queryKey: getListProjectsQueryKey(communityId) },
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectQueryKey(communityId, data.project_id),
        (project) => (project ? { ...project, is_favorited: data.is_favorited } : project)
      );
      void invalidate(q.favoriteProjects());
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

interface TogglePinArgs {
  projectId: number;
  nextState: boolean;
}

const replaceProjectInList = (
  prev: ProjectListResponse | undefined,
  updated: ProjectRead
): ProjectListResponse | undefined => {
  if (!prev) return prev;
  return {
    ...prev,
    items: prev.items.map((project) => (project.id === updated.id ? updated : project)),
  };
};

export const useToggleProjectPin = (options?: MutationOpts<ProjectRead, TogglePinArgs>) => {
  const communityId = useActiveCommunityId();
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, nextState }: TogglePinArgs) => {
      return updateProject(communityId, projectId, {
        pinned: nextState,
      });
    },
    onSuccess: (...args) => {
      const data = args[0];
      // See useToggleProjectFavorite: match the endpoint, not one exact shape.
      qc.setQueriesData<ProjectListResponse>(
        { queryKey: getListProjectsQueryKey(communityId) },
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectRead>(getReadProjectQueryKey(communityId, data.id), () => data);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

// ── Task Status Mutations ───────────────────────────────────────────────────

const invalidateStatusesAndTasks = (projectId: number) =>
  invalidate(q.projectTaskStatuses(projectId), q.allTasks());

export const useCreateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, TaskStatusCreate>
) =>
  useCommunityMutation<TaskStatusRead, TaskStatusCreate>(
    {
      mutationFn: (communityId, data) => createTaskStatus(communityId, projectId, data),
      invalidate: () => invalidateStatusesAndTasks(projectId),
    },
    options
  );

export const useUpdateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, { statusId: number; data: TaskStatusUpdate }>
) =>
  useCommunityMutation<TaskStatusRead, { statusId: number; data: TaskStatusUpdate }>(
    {
      mutationFn: (communityId, { statusId, data }) =>
        updateTaskStatus(communityId, projectId, statusId, data),
      invalidate: () => invalidate(q.projectTaskStatuses(projectId)),
    },
    options
  );

export const useDeleteTaskStatus = (
  projectId: number,
  options?: MutationOpts<void, { statusId: number; data: TaskStatusDeleteRequest }>
) =>
  useCommunityMutation<void, { statusId: number; data: TaskStatusDeleteRequest }>(
    {
      mutationFn: (communityId, { statusId, data }) =>
        deleteTaskStatus(communityId, projectId, statusId, data),
      invalidate: () => invalidateStatusesAndTasks(projectId),
    },
    options
  );

export const useReorderTaskStatuses = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead[], TaskStatusReorderRequest>
) =>
  useCommunityMutation<TaskStatusRead[], TaskStatusReorderRequest>(
    {
      mutationFn: (communityId, data) => reorderTaskStatuses(communityId, projectId, data),
      invalidate: () => invalidate(q.projectTaskStatuses(projectId)),
    },
    options
  );
