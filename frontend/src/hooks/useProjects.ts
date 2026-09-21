import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { unarchiveEntityApiV1GGuildIdUnarchiveEntityTypeEntityIdPost } from "@/api/generated/archive/archive";
import type {
  ListMyProjectsApiV1MeProjectsGetParams,
  ListProjectsApiV1GGuildIdProjectsGetParams,
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
  duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost,
  favoriteProjectApiV1GGuildIdProjectsProjectIdFavoritePost,
  favoriteProjectsApiV1GGuildIdProjectsFavoritesGet,
  getFavoriteProjectsApiV1GGuildIdProjectsFavoritesGetQueryKey,
  getListProjectsApiV1GGuildIdProjectsGetQueryKey,
  getListWritableProjectsApiV1GGuildIdProjectsWritableGetQueryKey,
  getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  listWritableProjectsApiV1GGuildIdProjectsWritableGet,
  reorderProjectsApiV1GGuildIdProjectsReorderPost,
  unfavoriteProjectApiV1GGuildIdProjectsProjectIdFavoriteDelete,
  updateProjectApiV1GGuildIdProjectsProjectIdPatch,
} from "@/api/generated/projects/projects";
import {
  createTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesPost,
  deleteTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesStatusIdDelete,
  getListTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGetQueryKey,
  listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet,
  reorderTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesReorderPost,
  updateTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesStatusIdPatch,
} from "@/api/generated/task-statuses/task-statuses";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
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
 * One page of the guild's projects.
 *
 * Read straight, without the placeholder rows every other tool's list keeps:
 * the status-count queries below read only `total_count`, and holding the
 * previous count on screen would show the wrong badge while a filter changes.
 */
export const useProjects = (
  params?: ListProjectsApiV1GGuildIdProjectsGetParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<ProjectListResponse>({
    ...projects.listQuery(guildId, params),
    ...options,
  });
};

/** Templates in one initiative, or across every one the caller can see — the
 *  create dialog's "start from a template" picker. The projects list reads its
 *  own templates through `useProjects`, since the status filter picks which of
 *  the three states the same query returns. */
/** Row counts for the three list states, for the status filter's badges. The
 *  smallest possible page of the slim projection: only `total_count` is read,
 *  so a state advertises how much it holds without loading any of it. */
export const useProjectStatusCounts = (initiativeId?: number | null) => {
  const base = {
    slim: true,
    page_size: 1,
    ...(initiativeId ? { initiative_id: initiativeId } : {}),
  };
  const active = useProjects(base);
  const templates = useProjects({ ...base, template: true });
  const archived = useProjects({ ...base, archived: true });
  return {
    active: active.data?.total_count,
    templates: templates.data?.total_count,
    archived: archived.data?.total_count,
  };
};

export const useTemplateProjects = (initiativeId?: number | null) => {
  return useProjects({ template: true, ...(initiativeId ? { initiative_id: initiativeId } : {}) });
};

export const useWritableProjects = (options?: QueryOpts<ProjectRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<ProjectRead[]>({
    queryKey: getListWritableProjectsApiV1GGuildIdProjectsWritableGetQueryKey(guildId),
    queryFn: () => listWritableProjectsApiV1GGuildIdProjectsWritableGet(guildId),
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
    queryKey: getFavoriteProjectsApiV1GGuildIdProjectsFavoritesGetQueryKey(guildId),
    queryFn: () => favoriteProjectsApiV1GGuildIdProjectsFavoritesGet(guildId),
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
    queryKey: getListTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGetQueryKey(
      guildId,
      projectId!
    ),
    queryFn: () =>
      listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet(guildId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

// ── Global (cross-guild) queries ────────────────────────────────────────────

export const useGlobalProjects = (
  params?: ListMyProjectsApiV1MeProjectsGetParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  return useQuery<ProjectListResponse>({
    ...projects.myListQuery(params),
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

type ProjectPatch = Parameters<typeof updateProjectApiV1GGuildIdProjectsProjectIdPatch>[2];

export const useUpdateProject = (
  projectId: number,
  options?: MutationOpts<ProjectRead, ProjectPatch>
) =>
  useGuildMutation<ProjectRead, ProjectPatch>(
    {
      mutationFn: (guildId, data) =>
        updateProjectApiV1GGuildIdProjectsProjectIdPatch(guildId, projectId, data),
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
        updateProjectApiV1GGuildIdProjectsProjectIdPatch(guildId, projectId, {
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
        await unarchiveEntityApiV1GGuildIdUnarchiveEntityTypeEntityIdPost(
          guildId,
          "project",
          projectId
        );
      },
      invalidate: () => invalidate(q.allProjects()),
    },
    options
  );

export const useDuplicateProject = (
  options?: MutationOpts<
    ProjectRead,
    {
      projectId: number;
      data: Parameters<typeof duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost>[2];
    }
  >
) =>
  useGuildMutation<
    ProjectRead,
    {
      projectId: number;
      data: Parameters<typeof duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost>[2];
    }
  >(
    {
      mutationFn: (guildId, { projectId, data }) =>
        duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost(guildId, projectId, data),
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
      await reorderProjectsApiV1GGuildIdProjectsReorderPost(guildId, { project_ids: orderedIds });
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
        await favoriteProjectApiV1GGuildIdProjectsProjectIdFavoritePost(guildId, projectId);
      } else {
        await unfavoriteProjectApiV1GGuildIdProjectsProjectIdFavoriteDelete(guildId, projectId);
      }
      return { project_id: projectId, is_favorited: nextState };
    },
    onSuccess: (...args) => {
      const data = args[0];
      // Every cached project list, whatever it was narrowed by — the keys carry
      // an initiative and a page now, so naming them one by one silently misses
      // the list the reader is actually looking at.
      qc.setQueriesData<ProjectListResponse>(
        { queryKey: getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId) },
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(
          guildId,
          data.project_id
        ) as unknown as string[],
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
      return updateProjectApiV1GGuildIdProjectsProjectIdPatch(guildId, projectId, {
        pinned: nextState,
      });
    },
    onSuccess: (...args) => {
      const data = args[0];
      // See useToggleProjectFavorite: match the endpoint, not one exact shape.
      qc.setQueriesData<ProjectListResponse>(
        { queryKey: getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId) },
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(
          guildId,
          data.id
        ) as unknown as string[],
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
      mutationFn: (guildId, data) =>
        createTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesPost(guildId, projectId, data),
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
        updateTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesStatusIdPatch(
          guildId,
          projectId,
          statusId,
          data
        ),
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
        deleteTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesStatusIdDelete(
          guildId,
          projectId,
          statusId,
          data
        ),
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
      mutationFn: (guildId, data) =>
        reorderTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesReorderPost(
          guildId,
          projectId,
          data
        ),
      invalidate: () => invalidate(q.projectTaskStatuses(projectId)),
    },
    options
  );
