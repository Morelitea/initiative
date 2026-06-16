import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearch } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  FilterCondition,
  ListMyTasksApiV1MeTasksGetParams,
  SortField,
  TaskListRead,
  TaskListResponse,
  TaskPriority,
  TaskStatusCategory,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet } from "@/api/generated/task-statuses/task-statuses";
import {
  getListMyCreatedTasksApiV1MeTasksCreatedGetQueryKey,
  getListMyTasksApiV1MeTasksGetQueryKey,
  listMyCreatedTasksApiV1MeTasksCreatedGet,
  listMyTasksApiV1MeTasksGet,
} from "@/api/generated/tasks/tasks";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { useGuilds } from "@/hooks/useGuilds";
import { useUpdateTaskInGuild } from "@/hooks/useTasks";
import { useViewPreference } from "@/hooks/useViewPreference";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

const statusFallbackOrder: Record<TaskStatusCategory, TaskStatusCategory[]> = {
  backlog: ["backlog"],
  todo: ["todo", "backlog"],
  in_progress: ["in_progress", "todo", "backlog"],
  done: ["done", "in_progress", "todo", "backlog"],
};

const SORT_DEFAULTS: SortField[] = [
  { field: "date_group", dir: "asc" },
  { field: "due_date", dir: "asc" },
];

type StoredPrefs = {
  statusFilters: TaskStatusCategory[];
  priorityFilters: TaskPriority[];
  guildFilters: number[];
  propertyFilters: PropertyFilterCondition[];
  sorting: SortField[];
};

const FILTER_DEFAULTS: StoredPrefs = {
  statusFilters: ["backlog", "todo", "in_progress"] as TaskStatusCategory[],
  priorityFilters: [],
  guildFilters: [],
  propertyFilters: [],
  sorting: SORT_DEFAULTS,
};

const sanitizeStoredPrefs = (raw: unknown): StoredPrefs => {
  if (raw === null || typeof raw !== "object") return FILTER_DEFAULTS;
  const v = raw as Partial<StoredPrefs>;
  return {
    statusFilters: Array.isArray(v.statusFilters) ? v.statusFilters : FILTER_DEFAULTS.statusFilters,
    priorityFilters: Array.isArray(v.priorityFilters)
      ? v.priorityFilters
      : FILTER_DEFAULTS.priorityFilters,
    guildFilters: Array.isArray(v.guildFilters) ? v.guildFilters : FILTER_DEFAULTS.guildFilters,
    propertyFilters: Array.isArray(v.propertyFilters)
      ? v.propertyFilters
      : FILTER_DEFAULTS.propertyFilters,
    sorting: Array.isArray(v.sorting) ? v.sorting : FILTER_DEFAULTS.sorting,
  };
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

export type MyTasksView = "assigned" | "created";

interface UseGlobalTasksTableOptions {
  view: MyTasksView;
  storageKeyPrefix: string;
}

export function useGlobalTasksTable({ view, storageKeyPrefix }: UseGlobalTasksTableOptions) {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  // Cross-guild aggregates: /me/tasks (assigned) vs /me/tasks/created (created).
  const isCreated = view === "created";
  const listMyTasks = isCreated
    ? listMyCreatedTasksApiV1MeTasksCreatedGet
    : listMyTasksApiV1MeTasksGet;
  const getMyTasksQueryKey = isCreated
    ? getListMyCreatedTasksApiV1MeTasksCreatedGetQueryKey
    : getListMyTasksApiV1MeTasksGetQueryKey;
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

  // --- Server-persisted filter + sort preferences ---
  const [storedPrefsRaw, setStoredPrefs] = useViewPreference<StoredPrefs>(
    storageKey,
    FILTER_DEFAULTS
  );
  const storedPrefs = useMemo(() => sanitizeStoredPrefs(storedPrefsRaw), [storedPrefsRaw]);
  const { statusFilters, priorityFilters, guildFilters, propertyFilters, sorting } = storedPrefs;

  const makeSetter = useCallback(
    <K extends keyof StoredPrefs>(key: K) =>
      (value: StoredPrefs[K] | ((prev: StoredPrefs[K]) => StoredPrefs[K])) => {
        setStoredPrefs((prev) => {
          const current = sanitizeStoredPrefs(prev);
          const next =
            typeof value === "function"
              ? (value as (p: StoredPrefs[K]) => StoredPrefs[K])(current[key])
              : value;
          return { ...current, [key]: next };
        });
      },
    [setStoredPrefs]
  );
  const setStatusFilters = useMemo(() => makeSetter("statusFilters"), [makeSetter]);
  const setPriorityFilters = useMemo(() => makeSetter("priorityFilters"), [makeSetter]);
  const setGuildFilters = useMemo(() => makeSetter("guildFilters"), [makeSetter]);
  const setPropertyFilters = useMemo(() => makeSetter("propertyFilters"), [makeSetter]);
  const setSorting = useMemo(() => makeSetter("sorting"), [makeSetter]);

  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  // --- Pagination state ---
  const [page, setPageState] = useState(() => searchParams.page ?? 1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

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
    [setPage, setSorting]
  );

  // Reset to page 1 when filters change
  const propertyFiltersKey = JSON.stringify(propertyFilters);
  useEffect(() => {
    setPage(1);
  }, [statusFilters, priorityFilters, guildFilters, propertyFiltersKey, setPage]);

  // --- User timezone for server-side date_group calculation ---
  const userTimezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  // --- Tasks query ---
  const tasksParams = useMemo((): ListMyTasksApiV1MeTasksGetParams => {
    // Build synthesized property-value conditions. The tasks backend exposes
    // ``property_values`` as a virtual field where ``value`` is the shape
    // ``{property_id, value}`` (see backend/app/api/v1/endpoints/tasks.py).
    const propertyConditions: FilterCondition[] = propertyFilters.map((entry) => ({
      field: "property_values",
      op: entry.op as FilterCondition["op"],
      value: { property_id: entry.property_id, value: entry.value },
    }));
    const conditions: FilterCondition[] = [
      ...(statusFilters.length > 0
        ? [{ field: "status_category", op: "in_" as const, value: statusFilters }]
        : []),
      ...(priorityFilters.length > 0
        ? [{ field: "priority", op: "in_" as const, value: priorityFilters }]
        : []),
      // The global tasks endpoint extracts this as ``guild_ids`` (plural,
      // matching ``initiative_ids``); sending the singular ``guild_id``
      // silently no-ops because the extraction looks for the plural key.
      ...(guildFilters.length > 0
        ? [{ field: "guild_ids", op: "in_" as const, value: guildFilters }]
        : []),
      ...propertyConditions,
    ];
    return {
      conditions: conditions.length > 0 ? conditions : undefined,
      page,
      page_size: pageSize,
      sorting: sorting.length > 0 ? sorting : undefined,
      tz: userTimezone,
    };
  }, [
    statusFilters,
    priorityFilters,
    guildFilters,
    propertyFilters,
    page,
    pageSize,
    sorting,
    userTimezone,
  ]);

  const tasksQuery = useQuery<TaskListResponse>({
    queryKey: getMyTasksQueryKey(tasksParams),
    queryFn: () => listMyTasks(tasksParams) as unknown as Promise<TaskListResponse>,
    placeholderData: keepPreviousData,
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams: ListMyTasksApiV1MeTasksGetParams = {
        ...tasksParams,
        page: targetPage,
      };

      void localQueryClient.prefetchQuery({
        queryKey: getMyTasksQueryKey(prefetchParams),
        queryFn: () => listMyTasks(prefetchParams) as unknown as Promise<TaskListResponse>,
        staleTime: 30_000,
      });
    },
    [tasksParams, localQueryClient, getMyTasksQueryKey, listMyTasks]
  );

  // --- Status mutation ---
  const { mutateAsync: updateTaskStatusMutate, isPending: isUpdatingTaskStatus } =
    useUpdateTaskInGuild({
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

  // --- Status helpers ---
  const fetchProjectStatuses = useCallback(async (projectId: number, guildId: number | null) => {
    const cached = projectStatusCache.current.get(projectId);
    if (cached?.complete) {
      return cached.statuses;
    }
    if (!guildId) {
      return cached?.statuses ?? [];
    }
    // Explicit guild address: the project lives in the task's guild, which
    // need not be the user's current context on these cross-guild pages.
    const statuses = (await listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet(
      guildId,
      projectId
    )) as unknown as TaskStatusRead[];
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
          // Cross-guild update from the personal My Tasks table: per-guild task
          // ids collide, so the update must name the task's own guild (path).
          guildId: targetGuildId,
        });
      } catch (error) {
        console.error(error);
        toast.error(getErrorMessage(error, "tasks:errors.statusUpdate"));
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

  // --- Display tasks ---
  // Archived/template projects are excluded server-side by both global
  // scopes, so the rows come back ready to render.
  const displayTasks = tasks;

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
  const isInitialLoad = tasksQuery.isLoading && !tasksQuery.data;

  const isRefetching = tasksQuery.isFetching && !isInitialLoad;

  const hasError = tasksQuery.isError;

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
    propertyFilters,
    setPropertyFilters,
    filtersOpen,
    setFiltersOpen,

    // Query results
    tasksQuery,

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
