import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { unarchiveEntity } from "@/api/generated/archive/archive";
import type {
  ListMyProjectsParams,
  ListProjectsParams,
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
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { toolViewParams } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard five ───────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires. A project's list hook and
// update are its own, and are written out below — the list's query still comes
// from the table, so the key is named in one place.

const projects = TOOL_HOOKS[Tool.project];
export const useProject = projects.useDetail;
export const useCreateProject = projects.useCreate;
export const useDeleteProject = projects.useDelete;
export const useSetProjectGrants = projects.useSetGrants;

// ── Queries ─────────────────────────────────────────────────────────────────

/**
 * One page of the guild's projects. The rows stay on screen while a changed
 * page, search or order is in flight, like every other tool's list.
 */
export const useProjects = (
  params?: ListProjectsParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<ProjectListResponse>({
    ...projects.listQuery(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/** Templates in one initiative, or across every one the caller can see — the
 *  create dialog's "start from a template" picker. The projects list reads its
 *  own templates through `useProjects`, since the status filter picks which of
 *  the three states the same query returns. */
export const useTemplateProjects = (initiativeId?: number | null) => {
  return useProjects({
    is_template: true,
    ...(initiativeId ? { initiative_id: initiativeId } : {}),
  });
};

/** Every live project the reader may edit — where a task can be moved to; a
 *  template takes no tasks moved into it. Walks the list's windows, so no
 *  destination is left off a long list. */
export const useWritableProjects = (options?: QueryOpts<ProjectListResponse>) => {
  const guildId = useActiveGuildId();
  const params = {
    writable: true,
    slim: true,
    page_size: 0,
    ...toolViewParams(Tool.project, "active"),
  };
  return useQuery<ProjectListResponse>({
    queryKey: getListProjectsQueryKey(guildId, params),
    queryFn: () => fetchAllPages(listProjects, guildId, params),
    staleTime: 60 * 1000,
    ...options,
  });
};

// ``useRecentProjects`` was removed when the projects-only ``/projects/recent``
// endpoint was retired. Use ``useRecents`` from ``@/hooks/useRecents`` for the
// mixed-type bar instead.

export const useFavoriteProjects = (options?: QueryOpts<ProjectRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<ProjectRead[]>({
    queryKey: getFavoriteProjectsQueryKey(guildId),
    queryFn: () => favoriteProjects(guildId),
    staleTime: 30 * 1000,
    ...options,
  });
};

export const useProjectTaskStatuses = (
  projectId: number | null,
  options?: QueryOpts<TaskStatusRead[]>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskStatusRead[]>({
    queryKey: getListTaskStatusesQueryKey(guildId, projectId!),
    queryFn: () => listTaskStatuses(guildId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

// ── Global (cross-guild) queries ────────────────────────────────────────────

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

type ProjectPatch = Parameters<typeof updateProject>[2];

export const useUpdateProject = (
  projectId: number,
  options?: MutationOpts<ProjectRead, ProjectPatch>
) =>
  useGuildMutation<ProjectRead, ProjectPatch>(
    {
      mutationFn: (guildId, data) => updateProject(guildId, projectId, data),
      invalidate: () => invalidate(q.allProjects()),
      errorKey: "projects:settings.details.updateError",
    },
    options
  );

/**
 * Row-level template removal from the projects list, where the id varies per
 * row so the curried {@link useUpdateProject} doesn't fit.
 */
export const useRemoveProjectTemplate = (options?: MutationOpts<ProjectRead, number>) =>
  useGuildMutation<ProjectRead, number>(
    {
      mutationFn: (guildId, projectId) =>
        updateProject(guildId, projectId, {
          is_template: false,
        }),
      invalidate: () => invalidate(q.allProjects()),
      errorKey: "projects:settings.details.updateError",
    },
    options
  );

export const useUnarchiveProject = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: async (guildId, projectId) => {
        await unarchiveEntity(guildId, "project", projectId);
      },
      invalidate: () => invalidate(q.allProjects()),
    },
    options
  );

export const useReorderProjects = (options?: MutationOpts<void, number[]>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (orderedIds: number[]) => {
      await reorderProjects(guildId, { project_ids: orderedIds });
    },
    onSuccess,
    onError,
    onSettled: (...args) => {
      void invalidate(q.allProjects());
      onSettled?.(...args);
    },
  });
};

// ``useRecordProjectView`` / ``useClearProjectView`` were replaced by the
// polymorphic ``useRecordRecentView`` / ``useClearRecentView`` in
// ``@/hooks/useRecents``.

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
  const guildId = useActiveGuildId();
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, nextState }: ToggleFavoriteArgs) => {
      if (nextState) {
        await favoriteProject(guildId, projectId);
      } else {
        await unfavoriteProject(guildId, projectId);
      }
      return { project_id: projectId, is_favorited: nextState };
    },
    onSuccess: (...args) => {
      const data = args[0];
      // Every cached project list, whatever it was narrowed by — the keys carry
      // an initiative and a page now, so naming them one by one silently misses
      // the list the reader is actually looking at.
      qc.setQueriesData<ProjectListResponse>(
        { queryKey: getListProjectsQueryKey(guildId) },
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectQueryKey(guildId, data.project_id) as unknown as string[],
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
  const guildId = useActiveGuildId();
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, nextState }: TogglePinArgs) => {
      return updateProject(guildId, projectId, {
        pinned: nextState,
      });
    },
    onSuccess: (...args) => {
      const data = args[0];
      // See useToggleProjectFavorite: match the endpoint, not one exact shape.
      qc.setQueriesData<ProjectListResponse>(
        { queryKey: getListProjectsQueryKey(guildId) },
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectQueryKey(guildId, data.id) as unknown as string[],
        () => data
      );
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

// ── Project Document Mutations ──────────────────────────────────────────────

const _invalidateProjectAndDocuments = (projectId: number) =>
  invalidate(q.project(projectId), q.allDocuments());

// ── Task Status Mutations ───────────────────────────────────────────────────

const invalidateStatusesAndTasks = (projectId: number) =>
  invalidate(q.projectTaskStatuses(projectId), q.allTasks());

export const useCreateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, TaskStatusCreate>
) =>
  useGuildMutation<TaskStatusRead, TaskStatusCreate>(
    {
      mutationFn: (guildId, data) => createTaskStatus(guildId, projectId, data),
      invalidate: () => invalidateStatusesAndTasks(projectId),
    },
    options
  );

export const useUpdateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, { statusId: number; data: TaskStatusUpdate }>
) =>
  useGuildMutation<TaskStatusRead, { statusId: number; data: TaskStatusUpdate }>(
    {
      mutationFn: (guildId, { statusId, data }) =>
        updateTaskStatus(guildId, projectId, statusId, data),
      invalidate: () => invalidate(q.projectTaskStatuses(projectId)),
    },
    options
  );

export const useDeleteTaskStatus = (
  projectId: number,
  options?: MutationOpts<void, { statusId: number; data: TaskStatusDeleteRequest }>
) =>
  useGuildMutation<void, { statusId: number; data: TaskStatusDeleteRequest }>(
    {
      mutationFn: (guildId, { statusId, data }) =>
        deleteTaskStatus(guildId, projectId, statusId, data),
      invalidate: () => invalidateStatusesAndTasks(projectId),
    },
    options
  );

export const useReorderTaskStatuses = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead[], TaskStatusReorderRequest>
) =>
  useGuildMutation<TaskStatusRead[], TaskStatusReorderRequest>(
    {
      mutationFn: (guildId, data) => reorderTaskStatuses(guildId, projectId, data),
      invalidate: () => invalidate(q.projectTaskStatuses(projectId)),
    },
    options
  );
