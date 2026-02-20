import { useMutation, useQuery } from "@tanstack/react-query";
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
  ProjectFavoriteStatus,
  ProjectActivityFeedApiV1ProjectsProjectIdActivityGetParams,
} from "@/api/generated/initiativeAPI.schemas";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useProjects = (
  params?: ListProjectsApiV1ProjectsGetParams,
  options?: { enabled?: boolean; staleTime?: number }
) => {
  return useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey(params),
    queryFn: () => listProjectsApiV1ProjectsGet(params) as unknown as Promise<Project[]>,
    enabled: options?.enabled,
    staleTime: options?.staleTime,
  });
};

export const useTemplateProjects = () => {
  return useProjects({ template: true });
};

export const useArchivedProjects = () => {
  return useProjects({ archived: true });
};

export const useProject = (projectId: number | null) => {
  return useQuery<Project>({
    queryKey: getReadProjectApiV1ProjectsProjectIdGetQueryKey(projectId!),
    queryFn: () => readProjectApiV1ProjectsProjectIdGet(projectId!) as unknown as Promise<Project>,
    enabled: projectId !== null && Number.isFinite(projectId),
  });
};

export const useWritableProjects = (options?: { enabled?: boolean }) => {
  return useQuery<Project[]>({
    queryKey: getListWritableProjectsApiV1ProjectsWritableGetQueryKey(),
    queryFn: () => listWritableProjectsApiV1ProjectsWritableGet() as unknown as Promise<Project[]>,
    enabled: options?.enabled,
    staleTime: 60 * 1000,
  });
};

export const useRecentProjects = () => {
  return useQuery<ProjectRecentViewRead[]>({
    queryKey: getRecentProjectsApiV1ProjectsRecentGetQueryKey(),
    queryFn: () =>
      recentProjectsApiV1ProjectsRecentGet() as unknown as Promise<ProjectRecentViewRead[]>,
    staleTime: 30 * 1000,
  });
};

export const useFavoriteProjects = () => {
  return useQuery<ProjectFavoriteStatus[]>({
    queryKey: getFavoriteProjectsApiV1ProjectsFavoritesGetQueryKey(),
    queryFn: () =>
      favoriteProjectsApiV1ProjectsFavoritesGet() as unknown as Promise<ProjectFavoriteStatus[]>,
    staleTime: 30 * 1000,
  });
};

export const useProjectTaskStatuses = (projectId: number | null) => {
  return useQuery<ProjectTaskStatus[]>({
    queryKey: getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey(projectId!),
    queryFn: () =>
      listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet(projectId!) as unknown as Promise<
        ProjectTaskStatus[]
      >,
    enabled: projectId !== null && Number.isFinite(projectId),
  });
};

export const useProjectActivity = (
  projectId: number,
  params?: ProjectActivityFeedApiV1ProjectsProjectIdActivityGetParams
) => {
  return useQuery<ProjectActivityResponse>({
    queryKey: getProjectActivityFeedApiV1ProjectsProjectIdActivityGetQueryKey(projectId, params),
    queryFn: () =>
      projectActivityFeedApiV1ProjectsProjectIdActivityGet(
        projectId,
        params
      ) as unknown as Promise<ProjectActivityResponse>,
    enabled: Number.isFinite(projectId),
  });
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
