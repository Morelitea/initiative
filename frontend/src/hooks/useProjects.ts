import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  listProjectsApiV1ProjectsGet,
  getListProjectsApiV1ProjectsGetQueryKey,
  readProjectApiV1ProjectsProjectIdGet,
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
  listWritableProjectsApiV1ProjectsWritableGet,
  getListWritableProjectsApiV1ProjectsWritableGetQueryKey,
  recentProjectsApiV1ProjectsRecentGet,
  getRecentProjectsApiV1ProjectsRecentGetQueryKey,
  favoriteProjectsApiV1ProjectsFavoritesGet,
  getFavoriteProjectsApiV1ProjectsFavoritesGetQueryKey,
  projectActivityFeedApiV1ProjectsProjectIdActivityGet,
  getProjectActivityFeedApiV1ProjectsProjectIdActivityGetQueryKey,
  createProjectApiV1ProjectsPost,
  updateProjectApiV1ProjectsProjectIdPatch,
  deleteProjectApiV1ProjectsProjectIdDelete,
  archiveProjectApiV1ProjectsProjectIdArchivePost,
  unarchiveProjectApiV1ProjectsProjectIdUnarchivePost,
  duplicateProjectApiV1ProjectsProjectIdDuplicatePost,
  reorderProjectsApiV1ProjectsReorderPost,
  recordProjectViewApiV1ProjectsProjectIdViewPost,
  clearProjectViewApiV1ProjectsProjectIdViewDelete,
  listGlobalProjectsApiV1ProjectsGlobalGet,
  getListGlobalProjectsApiV1ProjectsGlobalGetQueryKey,
  favoriteProjectApiV1ProjectsProjectIdFavoritePost,
  unfavoriteProjectApiV1ProjectsProjectIdFavoriteDelete,
  addProjectMemberApiV1ProjectsProjectIdMembersPost,
  addProjectMembersBulkApiV1ProjectsProjectIdMembersBulkPost,
  updateProjectMemberApiV1ProjectsProjectIdMembersUserIdPatch,
  removeProjectMemberApiV1ProjectsProjectIdMembersUserIdDelete,
  removeProjectMembersBulkApiV1ProjectsProjectIdMembersBulkDeletePost,
  addProjectRolePermissionApiV1ProjectsProjectIdRolePermissionsPost,
  updateProjectRolePermissionApiV1ProjectsProjectIdRolePermissionsRoleIdPatch,
  removeProjectRolePermissionApiV1ProjectsProjectIdRolePermissionsRoleIdDelete,
  attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost,
  detachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdDelete,
} from "@/api/generated/projects/projects";
import {
  listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet,
  getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey,
  createTaskStatusApiV1ProjectsProjectIdTaskStatusesPost,
  updateTaskStatusApiV1ProjectsProjectIdTaskStatusesStatusIdPatch,
  deleteTaskStatusApiV1ProjectsProjectIdTaskStatusesStatusIdDelete,
  reorderTaskStatusesApiV1ProjectsProjectIdTaskStatusesReorderPost,
} from "@/api/generated/task-statuses/task-statuses";
import {
  invalidateAllDocuments,
  invalidateAllProjects,
  invalidateAllTasks,
  invalidateProject,
  invalidateFavoriteProjects,
  invalidateProjectTaskStatuses,
  invalidateRecentProjects,
} from "@/api/query-keys";
import { getErrorMessage } from "@/lib/errorMessage";
import type {
  ListProjectsApiV1ProjectsGetParams,
  ListGlobalProjectsApiV1ProjectsGlobalGetParams,
  ProjectActivityResponse,
  ProjectListResponse,
  ProjectPermissionBulkCreate,
  ProjectPermissionBulkDelete,
  ProjectPermissionCreate,
  ProjectPermissionRead,
  ProjectPermissionUpdate,
  ProjectRead,
  ProjectRecentViewRead,
  ProjectRolePermissionCreate,
  ProjectRolePermissionRead,
  ProjectRolePermissionUpdate,
  ProjectActivityFeedApiV1ProjectsProjectIdActivityGetParams,
  TaskStatusRead,
  TaskStatusCreate,
  TaskStatusUpdate,
  TaskStatusReorderRequest,
  TaskStatusDeleteRequest,
} from "@/api/generated/initiativeAPI.schemas";
import type { MutationOpts } from "@/types/mutation";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useProjects = (
  params?: ListProjectsApiV1ProjectsGetParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  return useQuery<ProjectListResponse>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey(params),
    queryFn: () => listProjectsApiV1ProjectsGet(params) as unknown as Promise<ProjectListResponse>,
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
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<ProjectRead>({
    queryKey: getReadProjectApiV1ProjectsProjectIdGetQueryKey(projectId!),
    queryFn: () =>
      readProjectApiV1ProjectsProjectIdGet(projectId!) as unknown as Promise<ProjectRead>,
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

export const useWritableProjects = (options?: QueryOpts<ProjectRead[]>) => {
  return useQuery<ProjectRead[]>({
    queryKey: getListWritableProjectsApiV1ProjectsWritableGetQueryKey(),
    queryFn: () =>
      listWritableProjectsApiV1ProjectsWritableGet() as unknown as Promise<ProjectRead[]>,
    staleTime: 60 * 1000,
    ...options,
  });
};

export const useRecentProjects = (options?: QueryOpts<ProjectRecentViewRead[]>) => {
  return useQuery<ProjectRecentViewRead[]>({
    queryKey: getRecentProjectsApiV1ProjectsRecentGetQueryKey(),
    queryFn: () =>
      recentProjectsApiV1ProjectsRecentGet() as unknown as Promise<ProjectRecentViewRead[]>,
    staleTime: 30 * 1000,
    ...options,
  });
};

export const useFavoriteProjects = (options?: QueryOpts<ProjectRead[]>) => {
  return useQuery<ProjectRead[]>({
    queryKey: getFavoriteProjectsApiV1ProjectsFavoritesGetQueryKey(),
    queryFn: () => favoriteProjectsApiV1ProjectsFavoritesGet() as unknown as Promise<ProjectRead[]>,
    staleTime: 30 * 1000,
    ...options,
  });
};

export const useProjectTaskStatuses = (
  projectId: number | null,
  options?: QueryOpts<TaskStatusRead[]>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskStatusRead[]>({
    queryKey: getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey(projectId!),
    queryFn: () =>
      listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet(projectId!) as unknown as Promise<
        TaskStatusRead[]
      >,
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

export const useProjectActivity = (
  projectId: number,
  params?: ProjectActivityFeedApiV1ProjectsProjectIdActivityGetParams,
  options?: QueryOpts<ProjectActivityResponse>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<ProjectActivityResponse>({
    queryKey: getProjectActivityFeedApiV1ProjectsProjectIdActivityGetQueryKey(projectId, params),
    queryFn: () =>
      projectActivityFeedApiV1ProjectsProjectIdActivityGet(
        projectId,
        params
      ) as unknown as Promise<ProjectActivityResponse>,
    enabled: Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

// ── Global (cross-guild) queries ────────────────────────────────────────────

export const useGlobalProjects = (
  params?: ListGlobalProjectsApiV1ProjectsGlobalGetParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  return useQuery<ProjectListResponse>({
    queryKey: getListGlobalProjectsApiV1ProjectsGlobalGetQueryKey(params),
    queryFn: () =>
      listGlobalProjectsApiV1ProjectsGlobalGet(params) as unknown as Promise<ProjectListResponse>,
    ...options,
  });
};

export const usePrefetchGlobalProjects = () => {
  const qc = useQueryClient();
  return (params?: ListGlobalProjectsApiV1ProjectsGlobalGetParams) => {
    return qc.prefetchQuery({
      queryKey: getListGlobalProjectsApiV1ProjectsGlobalGetQueryKey(params),
      queryFn: () =>
        listGlobalProjectsApiV1ProjectsGlobalGet(params) as unknown as Promise<ProjectListResponse>,
      staleTime: 30_000,
    });
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateProject = (
  options?: MutationOpts<ProjectRead, Parameters<typeof createProjectApiV1ProjectsPost>[0]>
) => {
  const { t } = useTranslation("projects");
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof createProjectApiV1ProjectsPost>[0]) => {
      return createProjectApiV1ProjectsPost(data) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (...args) => {
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      const message = args[0] instanceof Error ? args[0].message : t("createDialog.createError");
      toast.error(message);
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
      data: Parameters<typeof updateProjectApiV1ProjectsProjectIdPatch>[1];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      projectId,
      data,
    }: {
      projectId: number;
      data: Parameters<typeof updateProjectApiV1ProjectsProjectIdPatch>[1];
    }) => {
      return updateProjectApiV1ProjectsProjectIdPatch(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await deleteProjectApiV1ProjectsProjectIdDelete(projectId);
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await archiveProjectApiV1ProjectsProjectIdArchivePost(projectId);
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await unarchiveProjectApiV1ProjectsProjectIdUnarchivePost(projectId);
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
      data: Parameters<typeof duplicateProjectApiV1ProjectsProjectIdDuplicatePost>[1];
    }
  >
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({
      projectId,
      data,
    }: {
      projectId: number;
      data: Parameters<typeof duplicateProjectApiV1ProjectsProjectIdDuplicatePost>[1];
    }) => {
      return duplicateProjectApiV1ProjectsProjectIdDuplicatePost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (orderedIds: number[]) => {
      await reorderProjectsApiV1ProjectsReorderPost({ project_ids: orderedIds });
    },
    onSuccess,
    onError,
    onSettled: (...args) => {
      void invalidateAllProjects();
      onSettled?.(...args);
    },
  });
};

export const useRecordProjectView = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await recordProjectViewApiV1ProjectsProjectIdViewPost(projectId);
    },
    onSuccess: (...args) => {
      void invalidateRecentProjects();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

export const useClearProjectView = (options?: MutationOpts<void, number>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (projectId: number) => {
      await clearProjectViewApiV1ProjectsProjectIdViewDelete(projectId);
    },
    onSuccess: (...args) => {
      void invalidateRecentProjects();
      onSuccess?.(...args);
    },
    onError,
    onSettled,
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
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, nextState }: ToggleFavoriteArgs) => {
      if (nextState) {
        await favoriteProjectApiV1ProjectsProjectIdFavoritePost(projectId);
      } else {
        await unfavoriteProjectApiV1ProjectsProjectIdFavoriteDelete(projectId);
      }
      return { project_id: projectId, is_favorited: nextState };
    },
    onSuccess: (...args) => {
      const data = args[0];
      qc.setQueryData<ProjectListResponse>(getListProjectsApiV1ProjectsGetQueryKey(), (prev) =>
        updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
        (prev) => updateProjectListFavorite(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectApiV1ProjectsProjectIdGetQueryKey(data.project_id) as unknown as string[],
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
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, nextState }: TogglePinArgs) => {
      return updateProjectApiV1ProjectsProjectIdPatch(projectId, {
        pinned: nextState,
      }) as unknown as Promise<ProjectRead>;
    },
    onSuccess: (...args) => {
      const data = args[0];
      qc.setQueryData<ProjectListResponse>(getListProjectsApiV1ProjectsGetQueryKey(), (prev) =>
        replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectListResponse>(
        getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectRead>(
        getReadProjectApiV1ProjectsProjectIdGetQueryKey(data.id) as unknown as string[],
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectPermissionCreate) => {
      return addProjectMemberApiV1ProjectsProjectIdMembersPost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ userId, data }: { userId: number; data: ProjectPermissionUpdate }) => {
      return updateProjectMemberApiV1ProjectsProjectIdMembersUserIdPatch(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (userId: number) => {
      await removeProjectMemberApiV1ProjectsProjectIdMembersUserIdDelete(projectId, userId);
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectPermissionBulkCreate) => {
      return addProjectMembersBulkApiV1ProjectsProjectIdMembersBulkPost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectPermissionBulkDelete) => {
      await removeProjectMembersBulkApiV1ProjectsProjectIdMembersBulkDeletePost(projectId, data);
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: ProjectRolePermissionCreate) => {
      return addProjectRolePermissionApiV1ProjectsProjectIdRolePermissionsPost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ roleId, data }: { roleId: number; data: ProjectRolePermissionUpdate }) => {
      return updateProjectRolePermissionApiV1ProjectsProjectIdRolePermissionsRoleIdPatch(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (roleId: number) => {
      await removeProjectRolePermissionApiV1ProjectsProjectIdRolePermissionsRoleIdDelete(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentId: number) => {
      await attachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdPost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (documentId: number) => {
      await detachProjectDocumentApiV1ProjectsProjectIdDocumentsDocumentIdDelete(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: TaskStatusCreate) => {
      return createTaskStatusApiV1ProjectsProjectIdTaskStatusesPost(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ statusId, data }: { statusId: number; data: TaskStatusUpdate }) => {
      return updateTaskStatusApiV1ProjectsProjectIdTaskStatusesStatusIdPatch(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ statusId, data }: { statusId: number; data: TaskStatusDeleteRequest }) => {
      await deleteTaskStatusApiV1ProjectsProjectIdTaskStatusesStatusIdDelete(
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: TaskStatusReorderRequest) => {
      return reorderTaskStatusesApiV1ProjectsProjectIdTaskStatusesReorderPost(
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
