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
  listGlobalProjectsApiV1ProjectsGlobalGet,
  getListGlobalProjectsApiV1ProjectsGlobalGetQueryKey,
} from "@/api/generated/projects/projects";
import {
  listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet,
  getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey,
} from "@/api/generated/task-statuses/task-statuses";
import { invalidateAllProjects, invalidateRecentProjects } from "@/api/query-keys";
import { getErrorMessage } from "@/lib/errorMessage";
import type {
  ListProjectsApiV1ProjectsGetParams,
  ListGlobalProjectsApiV1ProjectsGlobalGetParams,
  ProjectActivityResponse,
  ProjectListResponse,
  ProjectRead,
  ProjectRecentViewRead,
  ProjectActivityFeedApiV1ProjectsProjectIdActivityGetParams,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";

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

export const useCreateProject = () => {
  const { t } = useTranslation("projects");

  return useMutation({
    mutationFn: async (data: Parameters<typeof createProjectApiV1ProjectsPost>[0]) => {
      return createProjectApiV1ProjectsPost(data) as unknown as Promise<ProjectRead>;
    },
    onSuccess: () => {
      void invalidateAllProjects();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("createDialog.createError");
      toast.error(message);
    },
  });
};

export const useUpdateProject = () => {
  return useMutation({
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
    onSuccess: () => {
      void invalidateAllProjects();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:settings.details.updateError"));
    },
  });
};

export const useDeleteProject = () => {
  return useMutation({
    mutationFn: async (projectId: number) => {
      await deleteProjectApiV1ProjectsProjectIdDelete(projectId);
    },
    onSuccess: () => {
      void invalidateAllProjects();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:detail.loadError"));
    },
  });
};

export const useArchiveProject = () => {
  return useMutation({
    mutationFn: async (projectId: number) => {
      await archiveProjectApiV1ProjectsProjectIdArchivePost(projectId);
    },
    onSuccess: () => {
      void invalidateAllProjects();
    },
  });
};

export const useUnarchiveProject = () => {
  return useMutation({
    mutationFn: async (projectId: number) => {
      await unarchiveProjectApiV1ProjectsProjectIdUnarchivePost(projectId);
    },
    onSuccess: () => {
      void invalidateAllProjects();
    },
  });
};

export const useDuplicateProject = () => {
  return useMutation({
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
    onSuccess: () => {
      void invalidateAllProjects();
    },
  });
};

export const useReorderProjects = () => {
  return useMutation({
    mutationFn: async (orderedIds: number[]) => {
      await reorderProjectsApiV1ProjectsReorderPost({ project_ids: orderedIds });
    },
    onSettled: () => {
      void invalidateAllProjects();
    },
  });
};

export const useRecordProjectView = () => {
  return useMutation({
    mutationFn: async (projectId: number) => {
      await recordProjectViewApiV1ProjectsProjectIdViewPost(projectId);
    },
    onSuccess: () => {
      void invalidateRecentProjects();
    },
  });
};
