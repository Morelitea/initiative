import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { SortingState } from "@tanstack/react-table";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { getItem, setItem } from "@/lib/storage";
import { queryClient } from "@/lib/queryClient";
import { useGuilds } from "@/hooks/useGuilds";
import type {
  Project,
  ProjectTaskStatus,
  Task,
  TaskListResponse,
  TaskPriority,
  TaskStatusCategory,
} from "@/types/api";

const statusFallbackOrder: Record<TaskStatusCategory, TaskStatusCategory[]> = {
  backlog: ["backlog"],
  todo: ["todo", "backlog"],
  in_progress: ["in_progress", "todo", "backlog"],
  done: ["done", "in_progress", "todo", "backlog"],
};

const FILTER_DEFAULTS = {
  statusFilters: ["backlog", "todo", "in_progress"] as TaskStatusCategory[],
  priorityFilters: [] as TaskPriority[],
  guildFilters: [] as number[],
};

const readStoredFilters = (storageKey: string) => {
  try {
    const raw = getItem(storageKey);
    if (!raw) {
      return FILTER_DEFAULTS;
    }
    const parsed = JSON.parse(raw);
    return {
      statusFilters: Array.isArray(parsed?.statusFilters)
        ? parsed.statusFilters
        : FILTER_DEFAULTS.statusFilters,
      priorityFilters: Array.isArray(parsed?.priorityFilters)
        ? parsed.priorityFilters
        : FILTER_DEFAULTS.priorityFilters,
      guildFilters: Array.isArray(parsed?.guildFilters)
        ? parsed.guildFilters
        : FILTER_DEFAULTS.guildFilters,
    };
  } catch {
    return FILTER_DEFAULTS;
  }
};

const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

const PAGE_SIZE = 20;

/** Map DataTable column IDs to backend sort field names */
const SORT_FIELD_MAP: Record<string, string> = {
  title: "title",
  "due date": "due_date",
  "start date": "start_date",
  "date group": "date_group",
  priority: "priority",
};

export type GlobalTaskScope = "global" | "global_created";

interface UseGlobalTasksTableOptions {
  scope: GlobalTaskScope;
  storageKeyPrefix: string;
}

export function useGlobalTasksTable({ scope, storageKeyPrefix }: UseGlobalTasksTableOptions) {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { activeGuildId } = useGuilds();
  const localQueryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  const storageKey = `initiative-${storageKeyPrefix}-filters`;

  const projectStatusCache = useRef<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >(new Map());

  // --- Filter state ---
  const [statusFilters, setStatusFilters] = useState<TaskStatusCategory[]>(
    () => readStoredFilters(storageKey).statusFilters
  );
  const [priorityFilters, setPriorityFilters] = useState<TaskPriority[]>(
    () => readStoredFilters(storageKey).priorityFilters
  );
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [guildFilters, setGuildFilters] = useState<number[]>(
    () => readStoredFilters(storageKey).guildFilters
  );

  // --- Pagination state ---
  const [page, setPageState] = useState(() => searchParams.page ?? 1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [sortBy, setSortBy] = useState<string | undefined>("date_group,due_date");
  const [sortDir, setSortDir] = useState<string | undefined>("asc,asc");

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setPageState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        void router.navigate({
          to: ".",
          search: {
            ...searchParamsRef.current,
            page: next <= 1 ? undefined : next,
          },
          replace: true,
        });
        return next;
      });
    },
    [router]
  );

  const handleSortingChange = useCallback(
    (sorting: SortingState) => {
      if (sorting.length > 0) {
        const fields = sorting.map((s) => SORT_FIELD_MAP[s.id]).filter(Boolean);
        const dirs = sorting
          .filter((s) => SORT_FIELD_MAP[s.id])
          .map((s) => (s.desc ? "desc" : "asc"));
        if (fields.length > 0) {
          setSortBy(fields.join(","));
          setSortDir(dirs.join(","));
        } else {
          setSortBy(undefined);
          setSortDir(undefined);
        }
      } else {
        setSortBy(undefined);
        setSortDir(undefined);
      }
      setPage(1);
    },
    [setPage]
  );

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilters, priorityFilters, guildFilters, setPage]);

  // --- Tasks query ---
  const tasksQuery = useQuery<TaskListResponse>({
    queryKey: [
      "tasks",
      "global",
      scope,
      statusFilters,
      priorityFilters,
      guildFilters,
      page,
      pageSize,
      sortBy,
      sortDir,
    ],
    queryFn: async () => {
      const params: Record<string, string | string[] | number | number[]> = { scope };

      if (statusFilters.length > 0) {
        params.status_category = statusFilters;
      }
      if (priorityFilters.length > 0) {
        params.priorities = priorityFilters;
      }
      if (guildFilters.length > 0) {
        params.guild_ids = guildFilters;
      }

      params.page = page;
      params.page_size = pageSize;

      if (sortBy) params.sort_by = sortBy;
      if (sortDir) params.sort_dir = sortDir;

      const response = await apiClient.get<TaskListResponse>("/tasks/", { params });
      return response.data;
    },
    placeholderData: keepPreviousData,
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const params: Record<string, string | string[] | number | number[]> = { scope };
      if (statusFilters.length > 0) params.status_category = statusFilters;
      if (priorityFilters.length > 0) params.priorities = priorityFilters;
      if (guildFilters.length > 0) params.guild_ids = guildFilters;
      params.page = targetPage;
      params.page_size = pageSize;
      if (sortBy) params.sort_by = sortBy;
      if (sortDir) params.sort_dir = sortDir;

      void localQueryClient.prefetchQuery({
        queryKey: [
          "tasks",
          "global",
          scope,
          statusFilters,
          priorityFilters,
          guildFilters,
          targetPage,
          pageSize,
          sortBy,
          sortDir,
        ],
        queryFn: async () => {
          const response = await apiClient.get<TaskListResponse>("/tasks/", { params });
          return response.data;
        },
        staleTime: 30_000,
      });
    },
    [
      scope,
      statusFilters,
      priorityFilters,
      guildFilters,
      pageSize,
      sortBy,
      sortDir,
      localQueryClient,
    ]
  );

  // --- Excluded projects (archived / template) ---
  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects", { guildId: activeGuildId }],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
  });

  const templatesQuery = useQuery<Project[]>({
    queryKey: ["projects", "templates", { guildId: activeGuildId }],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/", { params: { template: true } });
      return response.data;
    },
  });

  const archivedProjectsQuery = useQuery<Project[]>({
    queryKey: ["projects", "archived", { guildId: activeGuildId }],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/", { params: { archived: true } });
      return response.data;
    },
  });

  const projectsById = useMemo(() => {
    const result: Record<number, Project> = {};
    const projects = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
    projects.forEach((project) => {
      result[project.id] = project;
    });
    return result;
  }, [projectsQuery.data]);

  const excludedProjectIds = useMemo(() => {
    const ids = new Set<number>();
    const projects = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
    const templates = Array.isArray(templatesQuery.data) ? templatesQuery.data : [];
    const archived = Array.isArray(archivedProjectsQuery.data) ? archivedProjectsQuery.data : [];

    projects.forEach((project) => {
      if (project.is_archived || project.is_template) {
        ids.add(project.id);
      }
    });
    templates.forEach((project) => ids.add(project.id));
    archived.forEach((project) => ids.add(project.id));
    return ids;
  }, [projectsQuery.data, templatesQuery.data, archivedProjectsQuery.data]);

  // --- Status mutation ---
  const { mutateAsync: updateTaskStatusMutate, isPending: isUpdatingTaskStatus } = useMutation({
    mutationFn: async ({
      taskId,
      taskStatusId,
      guildId,
    }: {
      taskId: number;
      taskStatusId: number;
      guildId: number | null;
    }) => {
      const response = await apiClient.patch<Task>(
        `/tasks/${taskId}`,
        {
          task_status_id: taskStatusId,
        },
        guildId
          ? {
              headers: {
                "X-Guild-ID": String(guildId),
              },
            }
          : undefined
      );
      return response.data;
    },
    onSuccess: (updatedTask) => {
      void queryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
      const cached = projectStatusCache.current.get(updatedTask.project_id);
      if (cached && !cached.statuses.some((status) => status.id === updatedTask.task_status.id)) {
        cached.statuses.push(updatedTask.task_status);
      }
    },
  });

  // --- Task items + status cache hydration ---
  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);

  useEffect(() => {
    tasks.forEach((task) => {
      const cached = projectStatusCache.current.get(task.project_id);
      if (cached) {
        if (!cached.statuses.some((status) => status.id === task.task_status.id)) {
          cached.statuses.push(task.task_status);
        }
      } else {
        projectStatusCache.current.set(task.project_id, {
          statuses: [task.task_status],
          complete: false,
        });
      }
    });
  }, [tasks]);

  // --- Persist filters ---
  useEffect(() => {
    const payload = {
      statusFilters,
      priorityFilters,
      guildFilters,
    };
    setItem(storageKey, JSON.stringify(payload));
  }, [statusFilters, priorityFilters, guildFilters, storageKey]);

  // --- Status helpers ---
  const fetchProjectStatuses = useCallback(async (projectId: number, guildId: number | null) => {
    const cached = projectStatusCache.current.get(projectId);
    if (cached?.complete) {
      return cached.statuses;
    }
    if (!guildId) {
      return cached?.statuses ?? [];
    }
    const response = await apiClient.get<ProjectTaskStatus[]>(
      `/projects/${projectId}/task-statuses/`,
      {
        headers: {
          "X-Guild-ID": String(guildId),
        },
      }
    );
    const merged = cached
      ? [
          ...cached.statuses,
          ...response.data.filter((status) => !cached.statuses.some((s) => s.id === status.id)),
        ]
      : response.data;
    projectStatusCache.current.set(projectId, { statuses: merged, complete: true });
    return merged;
  }, []);

  const resolveStatusIdForCategory = useCallback(
    async (projectId: number, category: TaskStatusCategory, guildId: number | null) => {
      const statuses = await fetchProjectStatuses(projectId, guildId);
      const fallback = statusFallbackOrder[category] ?? [category];
      for (const candidate of fallback) {
        const match = statuses.find((status) => status.category === candidate);
        if (match) {
          return match.id;
        }
      }
      return null;
    },
    [fetchProjectStatuses]
  );

  const changeTaskStatusById = useCallback(
    async (task: Task, targetStatusId: number) => {
      const targetGuildId = task.guild_id ?? activeGuildId ?? null;
      if (!targetGuildId) {
        toast.error(t("errors.guildContext"));
        return;
      }
      try {
        await updateTaskStatusMutate({
          taskId: task.id,
          taskStatusId: targetStatusId,
          guildId: targetGuildId,
        });
      } catch (error) {
        console.error(error);
        const message = error instanceof Error ? error.message : t("errors.statusUpdate");
        toast.error(message);
      }
    },
    [activeGuildId, updateTaskStatusMutate, t]
  );

  const changeTaskStatus = useCallback(
    async (task: Task, targetCategory: TaskStatusCategory) => {
      const targetGuildId = task.guild_id ?? activeGuildId ?? null;
      if (!targetGuildId) {
        toast.error(t("errors.guildContext"));
        return;
      }
      const targetStatusId = await resolveStatusIdForCategory(
        task.project_id,
        targetCategory,
        targetGuildId
      );
      if (!targetStatusId) {
        toast.error(t("errors.statusNoMatch"));
        return;
      }
      await changeTaskStatusById(task, targetStatusId);
    },
    [activeGuildId, changeTaskStatusById, resolveStatusIdForCategory, t]
  );

  // --- Display tasks (exclude archived/template projects) ---
  const displayTasks = useMemo(() => {
    return tasks.filter((task) => !excludedProjectIds.has(task.project_id));
  }, [tasks, excludedProjectIds]);

  // --- Responsive filter visibility ---
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia("(min-width: 640px)");
    const handleChange = (event: MediaQueryListEvent) => {
      setFiltersOpen(event.matches);
    };
    setFiltersOpen(mediaQuery.matches);
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }
    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  // --- Derived loading / error states ---
  const isInitialLoad =
    (tasksQuery.isLoading && !tasksQuery.data) ||
    (projectsQuery.isLoading && !projectsQuery.data) ||
    (templatesQuery.isLoading && !templatesQuery.data) ||
    (archivedProjectsQuery.isLoading && !archivedProjectsQuery.data);

  const isRefetching = tasksQuery.isFetching && !isInitialLoad;

  const hasError =
    tasksQuery.isError ||
    projectsQuery.isError ||
    templatesQuery.isError ||
    archivedProjectsQuery.isError;

  const totalCount = tasksQuery.data?.total_count ?? 0;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

  return {
    // Filter state
    statusFilters,
    setStatusFilters,
    priorityFilters,
    setPriorityFilters,
    guildFilters,
    setGuildFilters,
    filtersOpen,
    setFiltersOpen,

    // Query results
    tasksQuery,
    projectsById,

    // Pagination
    page,
    setPage,
    pageSize,
    setPageSize,
    totalPages,
    totalCount,

    // Sorting
    handleSortingChange,

    // Prefetching
    prefetchPage,

    // Status mutations
    changeTaskStatus,
    changeTaskStatusById,
    fetchProjectStatuses,
    resolveStatusIdForCategory,
    projectStatusCache,
    isUpdatingTaskStatus,

    // Display data
    displayTasks,

    // Loading states
    isInitialLoad,
    isRefetching,
    hasError,

    // Context
    activeGuildId,
    localQueryClient,
    t,
  };
}
