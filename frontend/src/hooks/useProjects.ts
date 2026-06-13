import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  ListMyProjectsApiV1MeProjectsGetParams,
  ListProjectsApiV1GGuildIdProjectsGetParams,
  ProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetParams,
  ProjectActivityResponse,
  ProjectListResponse,
  ProjectPermissionBulkCreate,
  ProjectPermissionBulkDelete,
  ProjectPermissionCreate,
  ProjectPermissionRead,
  ProjectPermissionUpdate,
  ProjectRead,
  ProjectRolePermissionCreate,
  ProjectRolePermissionRead,
  ProjectRolePermissionUpdate,
  TaskStatusCreate,
  TaskStatusDeleteRequest,
  TaskStatusRead,
  TaskStatusReorderRequest,
  TaskStatusUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  addProjectMemberApiV1GGuildIdProjectsProjectIdMembersPost,
  addProjectMembersBulkApiV1GGuildIdProjectsProjectIdMembersBulkPost,
  addProjectRolePermissionApiV1GGuildIdProjectsProjectIdRolePermissionsPost,
  archiveProjectApiV1GGuildIdProjectsProjectIdArchivePost,
  attachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdPost,
  createProjectApiV1GGuildIdProjectsPost,
  deleteProjectApiV1GGuildIdProjectsProjectIdDelete,
  detachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdDelete,
  duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost,
  favoriteProjectApiV1GGuildIdProjectsProjectIdFavoritePost,
  favoriteProjectsApiV1GGuildIdProjectsFavoritesGet,
  getFavoriteProjectsApiV1GGuildIdProjectsFavoritesGetQueryKey,
  getListMyProjectsApiV1MeProjectsGetQueryKey,
  getListProjectsApiV1GGuildIdProjectsGetQueryKey,
  getListWritableProjectsApiV1GGuildIdProjectsWritableGetQueryKey,
  getProjectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGetQueryKey,
  getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  listMyProjectsApiV1MeProjectsGet,
  listProjectsApiV1GGuildIdProjectsGet,
  listWritableProjectsApiV1GGuildIdProjectsWritableGet,
  projectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGet,
  readProjectApiV1GGuildIdProjectsProjectIdGet,
  removeProjectMemberApiV1GGuildIdProjectsProjectIdMembersUserIdDelete,
  removeProjectMembersBulkApiV1GGuildIdProjectsProjectIdMembersBulkDeletePost,
  removeProjectRolePermissionApiV1GGuildIdProjectsProjectIdRolePermissionsRoleIdDelete,
  reorderProjectsApiV1GGuildIdProjectsReorderPost,
  unarchiveProjectApiV1GGuildIdProjectsProjectIdUnarchivePost,
  unfavoriteProjectApiV1GGuildIdProjectsProjectIdFavoriteDelete,
  updateProjectApiV1GGuildIdProjectsProjectIdPatch,
  updateProjectMemberApiV1GGuildIdProjectsProjectIdMembersUserIdPatch,
  updateProjectRolePermissionApiV1GGuildIdProjectsProjectIdRolePermissionsRoleIdPatch,
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
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
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
    queryFn: () =>
      listProjectsApiV1GGuildIdProjectsGet(
        guildId,
        params
      ) as unknown as Promise<ProjectListResponse>,
    ...options,
  });
};

export const useTemplateProjects = () => {
  return useProjects({ template: true });
};

export const useArchivedProjects = () => {
  return useProjects({ archived: true });
};

export const useProject = (projectId: number | null, options?: QueryOpts<ProjectRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<ProjectRead>({
    queryKey: getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(guildId, projectId!),
    queryFn: () =>
      readProjectApiV1GGuildIdProjectsProjectIdGet(
        guildId,
        projectId!
      ) as unknown as Promise<ProjectRead>,
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

export const useWritableProjects = (options?: QueryOpts<ProjectRead[]>) => {
  const guildId = useActiveGuildId();
  return useQuery<ProjectRead[]>({
    queryKey: getListWritableProjectsApiV1GGuildIdProjectsWritableGetQueryKey(guildId),
    queryFn: () =>
      listWritableProjectsApiV1GGuildIdProjectsWritableGet(guildId) as unknown as Promise<
        ProjectRead[]
      >,
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
    queryFn: () =>
      favoriteProjectsApiV1GGuildIdProjectsFavoritesGet(guildId) as unknown as Promise<
        ProjectRead[]
      >,
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
      listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet(
        guildId,
        projectId!
      ) as unknown as Promise<TaskStatusRead[]>,
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
      projectActivityFeedApiV1GGuildIdProjectsProjectIdActivityGet(
        guildId,
        projectId,
        params
      ) as unknown as Promise<ProjectActivityResponse>,
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
    queryFn: () =>
      listMyProjectsApiV1MeProjectsGet(params) as unknown as Promise<ProjectListResponse>,
    ...options,
  });
};

export const usePrefetchGlobalProjects = () => {
  const qc = useQueryClient();
  return (params?: ListMyProjectsApiV1MeProjectsGetParams) => {
    return qc.prefetchQuery({
      queryKey: getListMyProjectsApiV1MeProjectsGetQueryKey(params),
      queryFn: () =>
        listMyProjectsApiV1MeProjectsGet(params) as unknown as Promise<ProjectListResponse>,
      staleTime: 30_000,
    });
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateProject = (
  options?: MutationOpts<ProjectRead, Parameters<typeof createProjectApiV1GGuildIdProjectsPost>[1]>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof createProjectApiV1GGuildIdProjectsPost>[1]) => {
      return createProjectApiV1GGuildIdProjectsPost(
        guildId,
        data
      ) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:createDialog.createError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateProject = (
  options?: MutationOpts<
    ProjectRead,
    {
      projectId: number;
      data: Parameters<typeof updateProjectApiV1GGuildIdProjectsProjectIdPatch>[2];
    }
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      projectId,
      data,
    }: {
      projectId: number;
      data: Parameters<typeof updateProjectApiV1GGuildIdProjectsProjectIdPatch>[2];
    }) => {
      return updateProjectApiV1GGuildIdProjectsProjectIdPatch(
        guildId,
        projectId,
        data
      ) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.details.updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDeleteProject = (options?: MutationOpts<void, number>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await deleteProjectApiV1GGuildIdProjectsProjectIdDelete(guildId, projectId);
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:detail.loadError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useArchiveProject = (options?: MutationOpts<void, number>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await archiveProjectApiV1GGuildIdProjectsProjectIdArchivePost(guildId, projectId);
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUnarchiveProject = (options?: MutationOpts<void, number>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await unarchiveProjectApiV1GGuildIdProjectsProjectIdUnarchivePost(guildId, projectId);
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useDuplicateProject = (
  options?: MutationOpts<
    ProjectRead,
    {
      projectId: number;
      data: Parameters<typeof duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost>[2];
    }
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      projectId,
      data,
    }: {
      projectId: number;
      data: Parameters<typeof duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost>[2];
    }) => {
      return duplicateProjectApiV1GGuildIdProjectsProjectIdDuplicatePost(
        guildId,
        projectId,
        data
      ) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

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
      }) as unknown as Promise<ProjectRead>;
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

// ── Project Member Mutations ────────────────────────────────────────────────

export const useAddProjectMember = (
  projectId: number,
  options?: MutationOpts<ProjectPermissionRead, ProjectPermissionCreate>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectPermissionCreate) => {
      return addProjectMemberApiV1GGuildIdProjectsProjectIdMembersPost(
        guildId,
        projectId,
        data
      ) as unknown as Promise<ProjectPermissionRead>;
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.access.grantError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateProjectMember = (
  projectId: number,
  options?: MutationOpts<ProjectPermissionRead, { userId: number; data: ProjectPermissionUpdate }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ userId, data }: { userId: number; data: ProjectPermissionUpdate }) => {
      return updateProjectMemberApiV1GGuildIdProjectsProjectIdMembersUserIdPatch(
        guildId,
        projectId,
        userId,
        data
      ) as unknown as Promise<ProjectPermissionRead>;
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.access.updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useRemoveProjectMember = (projectId: number, options?: MutationOpts<void, number>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      await removeProjectMemberApiV1GGuildIdProjectsProjectIdMembersUserIdDelete(
        guildId,
        projectId,
        userId
      );
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.access.removeError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useAddProjectMembersBulk = (
  projectId: number,
  options?: MutationOpts<ProjectPermissionRead[], ProjectPermissionBulkCreate>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectPermissionBulkCreate) => {
      return addProjectMembersBulkApiV1GGuildIdProjectsProjectIdMembersBulkPost(
        guildId,
        projectId,
        data
      ) as unknown as Promise<ProjectPermissionRead[]>;
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.access.grantError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useRemoveProjectMembersBulk = (
  projectId: number,
  options?: MutationOpts<void, ProjectPermissionBulkDelete>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectPermissionBulkDelete) => {
      await removeProjectMembersBulkApiV1GGuildIdProjectsProjectIdMembersBulkDeletePost(
        guildId,
        projectId,
        data
      );
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.access.removeError"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Project Role Permission Mutations ───────────────────────────────────────

export const useAddProjectRolePermission = (
  projectId: number,
  options?: MutationOpts<ProjectRolePermissionRead, ProjectRolePermissionCreate>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectRolePermissionCreate) => {
      return addProjectRolePermissionApiV1GGuildIdProjectsProjectIdRolePermissionsPost(
        guildId,
        projectId,
        data
      ) as unknown as Promise<ProjectRolePermissionRead>;
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.roleAccess.grantError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useUpdateProjectRolePermission = (
  projectId: number,
  options?: MutationOpts<
    ProjectRolePermissionRead,
    { roleId: number; data: ProjectRolePermissionUpdate }
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ roleId, data }: { roleId: number; data: ProjectRolePermissionUpdate }) => {
      return updateProjectRolePermissionApiV1GGuildIdProjectsProjectIdRolePermissionsRoleIdPatch(
        guildId,
        projectId,
        roleId,
        data
      ) as unknown as Promise<ProjectRolePermissionRead>;
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.roleAccess.updateError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useRemoveProjectRolePermission = (
  projectId: number,
  options?: MutationOpts<void, number>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (roleId: number) => {
      await removeProjectRolePermissionApiV1GGuildIdProjectsProjectIdRolePermissionsRoleIdDelete(
        guildId,
        projectId,
        roleId
      );
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:settings.roleAccess.removeError"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Project Document Mutations ──────────────────────────────────────────────

export const useAttachProjectDocument = (
  projectId: number,
  options?: MutationOpts<void, number>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentId: number) => {
      await attachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdPost(
        guildId,
        projectId,
        documentId
      );
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:documents.attachError"));
      onError?.(...args);
    },
    onSettled,
  });
};

export const useDetachProjectDocument = (
  projectId: number,
  options?: MutationOpts<void, number>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentId: number) => {
      await detachProjectDocumentApiV1GGuildIdProjectsProjectIdDocumentsDocumentIdDelete(
        guildId,
        projectId,
        documentId
      );
    },
    onSuccess: (...args) => {
      void invalidateProject(projectId);
      void invalidateAllDocuments();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "projects:documents.detachError"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Task Status Mutations ───────────────────────────────────────────────────

export const useCreateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, TaskStatusCreate>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: TaskStatusCreate) => {
      return createTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesPost(
        guildId,
        projectId,
        data
      ) as unknown as Promise<TaskStatusRead>;
    },
    onSuccess: (...args) => {
      void invalidateProjectTaskStatuses(projectId);
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useUpdateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, { statusId: number; data: TaskStatusUpdate }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ statusId, data }: { statusId: number; data: TaskStatusUpdate }) => {
      return updateTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesStatusIdPatch(
        guildId,
        projectId,
        statusId,
        data
      ) as unknown as Promise<TaskStatusRead>;
    },
    onSuccess: (...args) => {
      void invalidateProjectTaskStatuses(projectId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useDeleteTaskStatus = (
  projectId: number,
  options?: MutationOpts<void, { statusId: number; data: TaskStatusDeleteRequest }>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ statusId, data }: { statusId: number; data: TaskStatusDeleteRequest }) => {
      await deleteTaskStatusApiV1GGuildIdProjectsProjectIdTaskStatusesStatusIdDelete(
        guildId,
        projectId,
        statusId,
        data
      );
    },
    onSuccess: (...args) => {
      void invalidateProjectTaskStatuses(projectId);
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useReorderTaskStatuses = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead[], TaskStatusReorderRequest>
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: TaskStatusReorderRequest) => {
      return reorderTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesReorderPost(
        guildId,
        projectId,
        data
      ) as unknown as Promise<TaskStatusRead[]>;
    },
    onSuccess: (...args) => {
      void invalidateProjectTaskStatuses(projectId);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};
