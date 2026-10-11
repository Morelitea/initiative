import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearch } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ListMyTasksParams,
  SortField,
  TaskListRead,
  TaskListResponse,
  TaskStatusCategory,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { listTaskStatuses } from "@/api/generated/task-statuses/task-statuses";
import { getListMyTasksQueryKey, listMyTasks } from "@/api/generated/tasks/tasks";
import { useCommunities } from "@/hooks/useCommunities";
import { deviceJSON, LIST, type ListViewSpec, useListView, viewKey } from "@/hooks/useListView";
import { useUpdateTaskInCommunity } from "@/hooks/useTasks";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  EMPTY_TASK_FILTERS,
  type StoredTaskFilters,
  specFromStored,
  type TaskFilterSpec,
  taskFilterCount,
  taskSortFields,
  taskSpecConditions,
  taskTableSorting,
} from "@/lib/filters/taskFilters";
import { toast } from "@/lib/mascotToast";
import { statusForCategory } from "@/lib/taskStatusDefaults";
import { browserTimezone } from "@/lib/timezones";

const SORT_DEFAULTS: SortField[] = [
  { field: "date_group", dir: "asc" },
  { field: "due_date", dir: "asc" },
];

/** What someone who has narrowed nothing sees: their tasks that are not
 *  done. */
const FILTER_DEFAULTS: TaskFilterSpec = {
  ...EMPTY_TASK_FILTERS,
  status_categories: ["backlog", "todo", "in_progress"],
};

const readMyTasksFilters = (raw: unknown) => specFromStored(raw as StoredTaskFilters);

/** What an older release kept: My Tasks' own filter names. */
const fromOldNames = (old: Record<string, unknown>): StoredTaskFilters => ({
  ...(old.statusFilters !== undefined ? { status_categories: old.statusFilters } : {}),
  ...(old.priorityFilters !== undefined ? { priorities: old.priorityFilters } : {}),
  ...(old.communityFilters !== undefined ? { community_ids: old.communityFilters } : {}),
  ...(old.propertyFilters !== undefined ? { properties: old.propertyFilters } : {}),
});

/** Order-insensitive comparison of two selections. */
const sameMembers = <T>(a: T[], b: T[]): boolean =>
  a.length === b.length && new Set(a).size === new Set([...a, ...b]).size;

/**
 * Where one person's view of My Tasks is kept: table or calendar, the
 * calendar's month or week, their filters, and the table's sort, grouping and
 * columns (date window and community hidden, grouped by date window, until
 * they change them). What an older release kept (filters and sort as one
 * preference, grouping and columns on the device, the month or week every
 * calendar shared) is carried over.
 */
export const MY_TASKS_VIEW: ListViewSpec<TaskFilterSpec> = {
  key: viewKey("me", "tasks"),
  read: readMyTasksFilters,
  defaults: {
    filters: FILTER_DEFAULTS,
    sorting: taskTableSorting(SORT_DEFAULTS),
    grouping: ["date group"],
    columns: { "date group": false, guild: false },
  },
  carryOver: (items) => {
    const old = items["initiative-my-tasks-filters"] as
      | (Record<string, unknown> & { sorting?: SortField[] })
      | undefined;
    const table = deviceJSON("initiative-my-tasks-table") as { grouping?: unknown } | null;
    const columns = deviceJSON("initiative-my-tasks-columns");
    const mode = items["calendar:view-mode"];
    if (!old && !table && !columns && typeof mode !== "string") return null;
    const sorting = old?.sorting;
    const filters = old ? fromOldNames(old) : {};
    return {
      mode: typeof mode === "string" ? mode : null,
      parts: {
        [LIST]: {
          ...(old ? { filters } : {}),
          ...(Array.isArray(sorting) ? { sorting: taskTableSorting(sorting) } : {}),
          ...(Array.isArray(table?.grouping) ? { grouping: table.grouping } : {}),
          ...(columns && typeof columns === "object" ? { columns } : {}),
        },
      },
    };
  },
};

const PAGE_SIZE = 20;

/**
 * Prefix shared by every `/me/tasks` cache entry — the table's page, the focus
 * summary's rule and pin queries. A status change patches all of them at once,
 * so the row it touched updates wherever it is on screen without waiting for
 * three cross-community aggregates to come back.
 */
const MY_TASKS_QUERY_PREFIX = getListMyTasksQueryKey();

/** Task ids repeat across communities, so an in-flight row is addressed by both. */
const taskKey = (task: Pick<TaskListRead, "id" | "community_id">) =>
  `${task.community_id ?? "none"}:${task.id}`;

export function useGlobalTasksTable() {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { activeCommunityId } = useCommunities();
  const localQueryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  const projectStatusCache = useRef<Map<number, { statuses: TaskStatusRead[]; complete: boolean }>>(
    new Map()
  );

  // --- This person's view of My Tasks: their filters and the table's sort ---
  const view = useListView(MY_TASKS_VIEW);
  const preferencesLoaded = view.loaded;
  const filters = view.filters;
  const sorting = useMemo(() => taskSortFields(view.sorting), [view.sorting]);
  const { setFilters: keepFilters, setSorting: keepSorting } = view;
  const setFilters = useCallback((next: TaskFilterSpec) => keepFilters(next), [keepFilters]);

  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // This page starts on a status selection rather than an empty one, so status
  // counts as "set" only once it differs from that baseline — otherwise the
  // button would badge a list nobody has touched.
  const activeFilterCount = taskFilterCount({
    ...filters,
    status_categories: sameMembers(filters.status_categories, FILTER_DEFAULTS.status_categories)
      ? []
      : filters.status_categories,
  });

  /** Back to what someone who narrowed nothing sees. */
  const clearFilters = useCallback(() => keepFilters(null), [keepFilters]);

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

  // The table captures its seed at mount, which is why the caller holds the
  // table back until `preferencesLoaded` — mounting first would freeze the
  // headers on the default sort while the rows came back in the saved one.
  const initialSorting = view.sorting;

  const handleSortingChange = useCallback(
    (tableSorting: SortingState) => {
      keepSorting(tableSorting);
      setPage(1);
    },
    [setPage, keepSorting]
  );

  // Reset to page 1 when filters change
  const filtersKey = JSON.stringify(filters);
  useEffect(() => {
    void filtersKey;
    setPage(1);
  }, [filtersKey, setPage]);

  // --- User timezone for server-side date_group calculation ---
  const userTimezone = useMemo(browserTimezone, []);

  // --- Tasks query ---
  const tasksParams = useMemo((): ListMyTasksParams => {
    const conditions = taskSpecConditions(filters);
    return {
      conditions: conditions.length > 0 ? conditions : undefined,
      page,
      page_size: pageSize,
      sorting: sorting.length > 0 ? sorting : undefined,
      tz: userTimezone,
    };
  }, [filters, page, pageSize, sorting, userTimezone]);

  const tasksQuery = useQuery<TaskListResponse>({
    queryKey: getListMyTasksQueryKey(tasksParams),
    queryFn: () => listMyTasks(tasksParams),
    placeholderData: keepPreviousData,
    // Nothing is worth asking for until the saved filters and sort are in
    // hand: a request built on the defaults would be thrown away the moment
    // they arrive, and its rows would sit under the saved sort's headers in
    // the meantime.
    enabled: preferencesLoaded,
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams: ListMyTasksParams = {
        ...tasksParams,
        page: targetPage,
      };

      void localQueryClient.prefetchQuery({
        queryKey: getListMyTasksQueryKey(prefetchParams),
        queryFn: () => listMyTasks(prefetchParams),
        staleTime: 30_000,
      });
    },
    [tasksParams, localQueryClient]
  );

  // --- Status mutation ---
  const { mutateAsync: updateTaskStatusMutate } = useUpdateTaskInCommunity({
    onSuccess: (updatedTask) => {
      const cached = projectStatusCache.current.get(updatedTask.project_id);
      if (cached && !cached.statuses.some((status) => status.id === updatedTask.task_status.id)) {
        cached.statuses.push(updatedTask.task_status);
      }
    },
  });

  // Which rows have a status change in flight. Per task rather than one flag for
  // the mutation, because the shared `isPending` disabled every row on the page
  // — and the focus summary's rows with them — while a single checkbox was
  // saving.
  const [updatingTasks, setUpdatingTasks] = useState<ReadonlySet<string>>(() => new Set());
  const isUpdatingTask = useCallback(
    (task: Pick<TaskListRead, "id" | "community_id">) => updatingTasks.has(taskKey(task)),
    [updatingTasks]
  );

  /**
   * Rewrite one row's status in every `/me/tasks` page the cache holds.
   *
   * Only that row is touched — not a snapshot of the whole page — so two rows
   * changed at once don't undo each other when one of them fails.
   */
  const writeStatusToCache = useCallback(
    (task: Pick<TaskListRead, "id" | "community_id">, status: TaskStatusRead) => {
      const key = taskKey(task);
      localQueryClient.setQueriesData<TaskListResponse>(
        { queryKey: MY_TASKS_QUERY_PREFIX },
        (old) => {
          if (!old?.items?.some((item) => taskKey(item) === key)) return old;
          return {
            ...old,
            items: old.items.map((item) =>
              taskKey(item) === key
                ? { ...item, task_status_id: status.id, task_status: status }
                : item
            ),
          };
        }
      );
    },
    [localQueryClient]
  );

  /**
   * Show the new status now, and hand back the undo.
   *
   * The check lands the moment it is clicked instead of after the refetch the
   * mutation's invalidation kicks off. A task that has just moved out of the
   * filtered set stays put until that refetch drops it, which reads as
   * completing work rather than as the row vanishing mid-click.
   */
  const applyStatusLocally = useCallback(
    (task: TaskListRead, status: TaskStatusRead) => {
      const previous = task.task_status;
      writeStatusToCache(task, status);
      return () => writeStatusToCache(task, previous);
    },
    [writeStatusToCache]
  );

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
  const fetchProjectStatuses = useCallback(
    async (projectId: number, communityId: number | null) => {
      const cached = projectStatusCache.current.get(projectId);
      if (cached?.complete) {
        return cached.statuses;
      }
      if (!communityId) {
        return cached?.statuses ?? [];
      }
      // Explicit community address: the project lives in the task's community, which
      // need not be the user's current context on these cross-community pages.
      const statuses = await listTaskStatuses(communityId, projectId);
      const merged = cached
        ? [
            ...cached.statuses,
            ...statuses.filter((status) => !cached.statuses.some((s) => s.id === status.id)),
          ]
        : statuses;
      projectStatusCache.current.set(projectId, { statuses: merged, complete: true });
      return merged;
    },
    []
  );

  const resolveStatusIdForCategory = useCallback(
    async (projectId: number, category: TaskStatusCategory, communityId: number | null) => {
      const statuses = await fetchProjectStatuses(projectId, communityId);
      return statusForCategory(statuses, category)?.id ?? null;
    },
    [fetchProjectStatuses]
  );

  const changeTaskStatusById = useCallback(
    async (task: TaskListRead, targetStatusId: number) => {
      const targetCommunityId = task.community_id ?? activeCommunityId ?? null;
      if (!targetCommunityId) {
        toast.error(t("errors.communityContext"));
        return;
      }
      // The status the row is moving to is already in hand whenever the caller
      // resolved it through this project's statuses, which is every path that
      // reaches here; without it the row simply waits for the refetch.
      const target = projectStatusCache.current
        .get(task.project_id)
        ?.statuses.find((status) => status.id === targetStatusId);
      const rollback = target ? applyStatusLocally(task, target) : null;
      const key = taskKey(task);
      setUpdatingTasks((prev) => new Set(prev).add(key));
      try {
        await updateTaskStatusMutate({
          taskId: task.id,
          data: { task_status_id: targetStatusId },
          // Cross-community update from the personal My Tasks table: per-community task
          // ids collide, so the update must name the task's own community (path).
          communityId: targetCommunityId,
        });
      } catch (error) {
        rollback?.();
        console.error(error);
        toast.error(getErrorMessage(error, "tasks:errors.statusUpdate"));
      } finally {
        setUpdatingTasks((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [activeCommunityId, applyStatusLocally, updateTaskStatusMutate, t]
  );

  const changeTaskStatus = useCallback(
    async (task: TaskListRead, targetCategory: TaskStatusCategory) => {
      const targetCommunityId = task.community_id ?? activeCommunityId ?? null;
      if (!targetCommunityId) {
        toast.error(t("errors.communityContext"));
        return;
      }
      const targetStatusId = await resolveStatusIdForCategory(
        task.project_id,
        targetCategory,
        targetCommunityId
      );
      if (!targetStatusId) {
        toast.error(t("errors.statusNoMatch"));
        return;
      }
      await changeTaskStatusById(task, targetStatusId);
    },
    [activeCommunityId, changeTaskStatusById, resolveStatusIdForCategory, t]
  );

  // --- Display tasks ---
  // Archived/template projects are excluded server-side, so the rows come
  // back ready to render.
  const displayTasks = tasks;

  // --- Derived loading / error states ---
  const isInitialLoad = tasksQuery.isLoading && !tasksQuery.data;

  const isRefetching = tasksQuery.isFetching && !isInitialLoad;

  const hasError = tasksQuery.isError;

  const totalCount = tasksQuery.data?.total_count ?? 0;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

  return {
    // Filter state
    filters,
    setFilters,
    filtersOpen,
    setFiltersOpen,
    activeFilterCount,
    clearFilters,

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
    initialSorting,
    handleSortingChange,

    // False until the saved filters and sort have resolved.
    preferencesLoaded,

    // Prefetching
    prefetchPage,

    // Status mutations
    changeTaskStatus,
    changeTaskStatusById,
    fetchProjectStatuses,
    resolveStatusIdForCategory,
    projectStatusCache,
    isUpdatingTask,

    // Display data
    displayTasks,

    // Loading states
    isInitialLoad,
    isRefetching,
    hasError,

    // Context
    activeCommunityId,
    localQueryClient,
    t,
  };
}
