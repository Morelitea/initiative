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
} from "@/api/generated/projects/projects";
import {
  listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet,
  getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey,
} from "@/api/generated/task-statuses/task-statuses";
import { invalidateAllProjects, invalidateRecentProjects } from "@/api/query-keys";
import { getErrorMessage } from "@/lib/errorMessage";
import type { Project, ProjectTaskStatus } from "@/types/api";
import type {
  ListProjectsApiV1ProjectsGetParams,
  ProjectActivityResponse,
  ProjectRecentViewRead,
  ProjectActivityFeedApiV1ProjectsProjectIdActivityGetParams,
} from "@/api/generated/initiativeAPI.schemas";

type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

// ── Queries ─────────────────────────────────────────────────────────────────

export const useProjects = (
  params?: ListProjectsApiV1ProjectsGetParams,
  options?: QueryOpts<Project[]>
) => {
  return useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey(params),
    queryFn: () => listProjectsApiV1ProjectsGet(params) as unknown as Promise<Project[]>,
    ...options,
  });
};

export const useTemplateProjects = () => {
  return useProjects({ template: true });
};

export const useArchivedProjects = () => {
  return useProjects({ archived: true });
};

export const useProject = (projectId: number | null, options?: QueryOpts<Project>) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<Project>({
    queryKey: getReadProjectApiV1ProjectsProjectIdGetQueryKey(projectId!),
    queryFn: () => readProjectApiV1ProjectsProjectIdGet(projectId!) as unknown as Promise<Project>,
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

export const useWritableProjects = (options?: QueryOpts<Project[]>) => {
  return useQuery<Project[]>({
    queryKey: getListWritableProjectsApiV1ProjectsWritableGetQueryKey(),
    queryFn: () => listWritableProjectsApiV1ProjectsWritableGet() as unknown as Promise<Project[]>,
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

export const useFavoriteProjects = (options?: QueryOpts<Project[]>) => {
  return useQuery<Project[]>({
    queryKey: getFavoriteProjectsApiV1ProjectsFavoritesGetQueryKey(),
    queryFn: () => favoriteProjectsApiV1ProjectsFavoritesGet() as unknown as Promise<Project[]>,
    staleTime: 30 * 1000,
    ...options,
  });
};

export const useProjectTaskStatuses = (
  projectId: number | null,
  options?: QueryOpts<ProjectTaskStatus[]>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<ProjectTaskStatus[]>({
    queryKey: getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey(projectId!),
    queryFn: () =>
      listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet(projectId!) as unknown as Promise<
        ProjectTaskStatus[]
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

import { apiClient } from "@/api/client";
import type { ProjectListResponse } from "@/types/api";

export const GLOBAL_PROJECTS_QUERY_KEY = "/api/v1/projects/global" as const;

export const globalProjectsQueryFn = async (
  params: Record<string, string | string[] | number | number[]>
) => {
  const response = await apiClient.get<ProjectListResponse>("/projects/global", { params });
  return response.data;
};

export const useGlobalProjects = (
  params: Record<string, string | string[] | number | number[]>,
  options?: QueryOpts<ProjectListResponse>
) => {
  return useQuery<ProjectListResponse>({
    queryKey: [GLOBAL_PROJECTS_QUERY_KEY, params],
    queryFn: () => globalProjectsQueryFn(params),
    ...options,
  });
};

export const usePrefetchGlobalProjects = () => {
  const qc = useQueryClient();
  return (params: Record<string, string | string[] | number | number[]>) => {
    return qc.prefetchQuery({
      queryKey: [GLOBAL_PROJECTS_QUERY_KEY, params],
      queryFn: () => globalProjectsQueryFn(params),
      staleTime: 30_000,
    });
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateProject = () => {
  const { t } = useTranslation("projects");

  return useMutation({
    mutationFn: async (data: Parameters<typeof createProjectApiV1ProjectsPost>[0]) => {
      return createProjectApiV1ProjectsPost(data) as unknown as Promise<Project>;
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
      ) as unknown as Promise<Project>;
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
      ) as unknown as Promise<Project>;
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
