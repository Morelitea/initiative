import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import type { SortingState } from "@tanstack/react-table";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import {
  listTasksApiV1TasksGet,
  getListTasksApiV1TasksGetQueryKey,
} from "@/api/generated/tasks/tasks";
import { listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet } from "@/api/generated/task-statuses/task-statuses";
import { useProjects, useTemplateProjects, useArchivedProjects } from "@/hooks/useProjects";
import { useUpdateTask } from "@/hooks/useTasks";
import type {
  ListTasksApiV1TasksGetParams,
  ProjectRead,
  SortField,
  TaskListRead,
  TaskListResponse,
  TaskPriority,
  TaskStatusCategory,
  TaskStatusRead,
  FilterCondition,
} from "@/api/generated/initiativeAPI.schemas";
import { getItem, setItem } from "@/lib/storage";
import { useGuilds } from "@/hooks/useGuilds";

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

  const projectStatusCache = useRef<Map<number, { statuses: TaskStatusRead[]; complete: boolean }>>(
    new Map()
  );

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
  const [sorting, setSorting] = useState<SortField[]>([
    { field: "date_group", dir: "asc" },
    { field: "due_date", dir: "asc" },
  ]);

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
    (tableSorting: SortingState) => {
      if (tableSorting.length > 0) {
        const fields: SortField[] = tableSorting
          .map((col) => {
            const field = SORT_FIELD_MAP[col.id];
            if (!field) return null;
            return { field, dir: col.desc ? "desc" : "asc" } as SortField;
          })
          .filter((f): f is SortField => f !== null);
        // date_group needs due_date as secondary sort for meaningful ordering
        if (fields.length === 1 && fields[0].field === "date_group") {
          fields.push({ field: "due_date", dir: fields[0].dir ?? "asc" });
        }
        setSorting(fields);
      } else {
        setSorting([]);
      }
      setPage(1);
    },
    [setPage]
  );

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilters, priorityFilters, guildFilters, setPage]);

  // --- User timezone for server-side date_group calculation ---
  const userTimezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    []
  );

  // --- Tasks query ---
  const tasksParams = useMemo((): ListTasksApiV1TasksGetParams => {
    const conditions: FilterCondition[] = [
      ...(statusFilters.length > 0
        ? [{ field: "status_category", op: "in_" as const, value: statusFilters }]
        : []),
      ...(priorityFilters.length > 0
        ? [{ field: "priority", op: "in_" as const, value: priorityFilters }]
        : []),
      ...(guildFilters.length > 0
        ? [{ field: "guild_id", op: "in_" as const, value: guildFilters }]
        : []),
    ];
    return {
      scope: scope as ListTasksApiV1TasksGetParams["scope"],
      conditions: conditions.length > 0 ? conditions : undefined,
      page,
      page_size: pageSize,
      sorting: sorting.length > 0 ? sorting : undefined,
      tz: userTimezone,
    };
  }, [scope, statusFilters, priorityFilters, guildFilters, page, pageSize, sorting, userTimezone]);

  const tasksQuery = useQuery<TaskListResponse>({
    queryKey: getListTasksApiV1TasksGetQueryKey(tasksParams),
    queryFn: () => listTasksApiV1TasksGet(tasksParams) as unknown as Promise<TaskListResponse>,
    placeholderData: keepPreviousData,
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams: ListTasksApiV1TasksGetParams = { ...tasksParams, page: targetPage };

      void localQueryClient.prefetchQuery({
        queryKey: getListTasksApiV1TasksGetQueryKey(prefetchParams),
        queryFn: () =>
          listTasksApiV1TasksGet(prefetchParams) as unknown as Promise<TaskListResponse>,
        staleTime: 30_000,
      });
    },
    [tasksParams, localQueryClient]
  );

  // --- Excluded projects (archived / template) ---
  const projectsQuery = useProjects();
  const templatesQuery = useTemplateProjects();
  const archivedProjectsQuery = useArchivedProjects();

  const projectsById = useMemo(() => {
    const result: Record<number, ProjectRead> = {};
    const projects = projectsQuery.data?.items ?? [];
    projects.forEach((project) => {
      result[project.id] = project;
    });
    return result;
  }, [projectsQuery.data]);

  const excludedProjectIds = useMemo(() => {
    const ids = new Set<number>();
    const projects = projectsQuery.data?.items ?? [];
    const templates = templatesQuery.data?.items ?? [];
    const archived = archivedProjectsQuery.data?.items ?? [];

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
  const { mutateAsync: updateTaskStatusMutate, isPending: isUpdatingTaskStatus } = useUpdateTask({
    onSuccess: (updatedTask) => {
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
    const statuses = (await listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet(projectId, {
      headers: { "X-Guild-ID": String(guildId) },
    })) as unknown as TaskStatusRead[];
    const merged = cached
      ? [
          ...cached.statuses,
          ...statuses.filter((status) => !cached.statuses.some((s) => s.id === status.id)),
        ]
      : statuses;
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
    async (task: TaskListRead, targetStatusId: number) => {
      const targetGuildId = task.guild_id ?? activeGuildId ?? null;
      if (!targetGuildId) {
        toast.error(t("errors.guildContext"));
        return;
      }
      try {
        await updateTaskStatusMutate({
          taskId: task.id,
          data: { task_status_id: targetStatusId },
          requestOptions: { headers: { "X-Guild-ID": String(targetGuildId) } },
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
    async (task: TaskListRead, targetCategory: TaskStatusCategory) => {
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
