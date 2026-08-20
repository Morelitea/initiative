import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  InitiativeGroupedCountsResponse,
  ListMyProjectsApiV1MeProjectsGetParams,
  ListProjectsApiV1GGuildIdProjectsGetParams,
  ProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetParams,
  ProjectActivityResponse,
  ProjectListResponse,
  ProjectRead,
  ResourceGrantSchema,
  TaskStatusCreate,
  TaskStatusDeleteRequest,
  TaskStatusRead,
  TaskStatusReorderRequest,
  TaskStatusUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  archiveProjectApiV1GGuildIdProjectsProjectIdArchivePost,
  attachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdPost,
  createProjectApiV1GGuildIdProjectsPost,
  deleteProjectApiV1GGuildIdProjectsProjectIdDelete,
  detachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdDelete,
  duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost,
  favoriteProjectApiV1GGuildIdProjectsProjectIdFavoritePost,
  favoriteProjectsApiV1GGuildIdProjectsFavoritesGet,
  getFavoriteProjectsApiV1GGuildIdProjectsFavoritesGetQueryKey,
  getGetProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGetQueryKey,
  getListMyProjectsApiV1MeProjectsGetQueryKey,
  getListProjectsApiV1GGuildIdProjectsGetQueryKey,
  getListWritableProjectsApiV1GGuildIdProjectsWritableGetQueryKey,
  getProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetQueryKey,
  getProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGet,
  getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  listMyProjectsApiV1MeProjectsGet,
  listProjectsApiV1GGuildIdProjectsGet,
  listWritableProjectsApiV1GGuildIdProjectsWritableGet,
  projectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGet,
  readProjectApiV1GGuildIdProjectsProjectIdGet,
  reorderProjectsApiV1GGuildIdProjectsReorderPost,
  setProjectGrantsApiV1GGuildIdProjectsProjectIdGrantsPut,
  unarchiveProjectApiV1GGuildIdProjectsProjectIdUnarchivePost,
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
import {
  invalidateAllDocuments,
  invalidateAllProjects,
  invalidateAllTasks,
  invalidateFavoriteProjects,
  invalidateProject,
  invalidateProjectTaskStatuses,
} from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useProjects = (
  params?: ListProjectsApiV1GGuildIdProjectsGetParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<ProjectListResponse>({
    queryKey: getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId, params),
    queryFn: () => listProjectsApiV1GGuildIdProjectsGet(guildId, params),
    ...options,
  });
};

export const useProjectCountsByInitiative = (
  options?: QueryOpts<InitiativeGroupedCountsResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeGroupedCountsResponse>({
    queryKey:
      getGetProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGetQueryKey(guildId),
    queryFn: () => getProjectCountsByInitiativeApiV1GGuildIdProjectsCountsByInitiativeGet(guildId),
    ...options,
  });
};

/** Templates in one initiative, or across every one the caller can see. The
 *  Templates and Archive tabs sit on an initiative-scoped page, so they narrow
 *  the same way the active list does. */
export const useTemplateProjects = (initiativeId?: number | null) => {
  return useProjects({ template: true, ...(initiativeId ? { initiative_id: initiativeId } : {}) });
};

export const useArchivedProjects = (initiativeId?: number | null) => {
  return useProjects({ archived: true, ...(initiativeId ? { initiative_id: initiativeId } : {}) });
};

export const useProject = (projectId: number | null, options?: QueryOpts<ProjectRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<ProjectRead>({
    queryKey: getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(guildId, projectId!),
    queryFn: () => readProjectApiV1GGuildIdProjectsProjectIdGet(guildId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
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

export const useProjectActivity = (
  projectId: number,
  params?: ProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetParams,
  options?: QueryOpts<ProjectActivityResponse>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<ProjectActivityResponse>({
    queryKey: getProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetQueryKey(
      guildId,
      projectId,
      params
    ),
    queryFn: () =>
      projectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGet(guildId, projectId, params),
    enabled: Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

// ── Global (cross-guild) queries ────────────────────────────────────────────

export const useGlobalProjects = (
  params?: ListMyProjectsApiV1MeProjectsGetParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  return useQuery<ProjectListResponse>({
    queryKey: getListMyProjectsApiV1MeProjectsGetQueryKey(params),
    queryFn: () => listMyProjectsApiV1MeProjectsGet(params),
    ...options,
  });
};

export const usePrefetchGlobalProjects = () => {
  const qc = useQueryClient();
  return (params?: ListMyProjectsApiV1MeProjectsGetParams) => {
    return qc.prefetchQuery({
      queryKey: getListMyProjectsApiV1MeProjectsGetQueryKey(params),
      queryFn: () => listMyProjectsApiV1MeProjectsGet(params),
      staleTime: 30_000,
    });
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateProject = (
  options?: MutationOpts<ProjectRead, Parameters<typeof createProjectApiV1GGuildIdProjectsPost>[1]>
) =>
  useGuildMutation<ProjectRead, Parameters<typeof createProjectApiV1GGuildIdProjectsPost>[1]>(
    {
      mutationFn: (guildId, data) => createProjectApiV1GGuildIdProjectsPost(guildId, data),
      invalidate: () => invalidateAllProjects(),
      errorKey: "projects:createDialog.createError",
    },
    options
  );

type ProjectPatch = Parameters<typeof updateProjectApiV1GGuildIdProjectsProjectIdPatch>[2];

export const useUpdateProject = (
  projectId: number,
  options?: MutationOpts<ProjectRead, ProjectPatch>
) =>
  useGuildMutation<ProjectRead, ProjectPatch>(
    {
      mutationFn: (guildId, data) =>
        updateProjectApiV1GGuildIdProjectsProjectIdPatch(guildId, projectId, data),
      invalidate: () => invalidateAllProjects(),
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
      invalidate: () => invalidateAllProjects(),
      errorKey: "projects:settings.details.updateError",
    },
    options
  );

export const useDeleteProject = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, projectId) =>
        deleteProjectApiV1GGuildIdProjectsProjectIdDelete(guildId, projectId),
      invalidate: () => invalidateAllProjects(),
      errorKey: "projects:detail.loadError",
    },
    options
  );

export const useArchiveProject = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: async (guildId, projectId) => {
        await archiveProjectApiV1GGuildIdProjectsProjectIdArchivePost(guildId, projectId);
      },
      invalidate: () => invalidateAllProjects(),
    },
    options
  );

export const useUnarchiveProject = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: async (guildId, projectId) => {
        await unarchiveProjectApiV1GGuildIdProjectsProjectIdUnarchivePost(guildId, projectId);
      },
      invalidate: () => invalidateAllProjects(),
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
      invalidate: () => invalidateAllProjects(),
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
      void invalidateAllProjects();
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
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId),
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId, { template: true }),
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId, { archived: true }),
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(
          guildId,
          data.project_id
        ) as unknown as string[],
        (project) => (project ? { ...project, is_favorited: data.is_favorited } : project)
      );
      void invalidateFavoriteProjects();
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
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId),
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId, { template: true }),
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1GGuildIdProjectsGetQueryKey(guildId, { archived: true }),
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

// ── Project Grants Mutation (unified resource sharing) ──────────────────────

export const useSetProjectGrants = (
  projectId: number,
  options?: MutationOpts<ProjectRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<ProjectRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setProjectGrantsApiV1GGuildIdProjectsProjectIdGrantsPut(guildId, projectId, grants),
      invalidate: () => Promise.all([invalidateProject(projectId), invalidateAllProjects()]),
      errorKey: "projects:settings.access.updateError",
    },
    options
  );

// ── Project Document Mutations ──────────────────────────────────────────────

const invalidateProjectAndDocuments = (projectId: number) =>
  Promise.all([invalidateProject(projectId), invalidateAllDocuments()]);

export const useAttachProjectDocument = (projectId: number, options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: async (guildId, documentId) => {
        await attachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdPost(
          guildId,
          projectId,
          documentId
        );
      },
      invalidate: () => invalidateProjectAndDocuments(projectId),
      errorKey: "projects:documents.attachError",
    },
    options
  );

export const useDetachProjectDocument = (projectId: number, options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: async (guildId, documentId) => {
        await detachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdDelete(
          guildId,
          projectId,
          documentId
        );
      },
      invalidate: () => invalidateProjectAndDocuments(projectId),
      errorKey: "projects:documents.detachError",
    },
    options
  );

// ── Task Status Mutations ───────────────────────────────────────────────────

const invalidateStatusesAndTasks = (projectId: number) =>
  Promise.all([invalidateProjectTaskStatuses(projectId), invalidateAllTasks()]);

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
      invalidate: () => invalidateProjectTaskStatuses(projectId),
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
      invalidate: () => invalidateProjectTaskStatuses(projectId),
    },
    options
  );
