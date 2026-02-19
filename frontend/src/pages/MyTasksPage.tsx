import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import {
  listTasksApiV1TasksGet,
  getListTasksApiV1TasksGetQueryKey,
  updateTaskApiV1TasksTaskIdPatch,
} from "@/api/generated/tasks/tasks";
import type { ListTasksApiV1TasksGetParams } from "@/api/generated/initiativeAPI.schemas";
import {
  listProjectsApiV1ProjectsGet,
  getListProjectsApiV1ProjectsGetQueryKey,
} from "@/api/generated/projects/projects";
import { listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet } from "@/api/generated/task-statuses/task-statuses";
import { invalidateAllTasks } from "@/api/query-keys";
import { getItem, setItem } from "@/lib/storage";
import { summarizeRecurrence } from "@/lib/recurrence";
import type { TranslateFn } from "@/types/i18n";
import { guildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useGuilds } from "@/hooks/useGuilds";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useGuilds } from "@/hooks/useGuilds";
import { useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { globalTaskColumns } from "@/components/tasks/globalTaskColumns";
import { GlobalTaskFilters } from "@/components/tasks/GlobalTaskFilters";
import { DataTable } from "@/components/ui/data-table";
import { PullToRefresh } from "@/components/PullToRefresh";
import type { TranslateFn } from "@/types/i18n";

export const MyTasksPage = () => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { guilds } = useGuilds();

  const table = useGlobalTasksTable({ scope: "global", storageKeyPrefix: "my-tasks" });

  const handleRefresh = useCallback(async () => {
    await invalidateAllTasks();
  }, []);

  const [statusFilters, setStatusFilters] = useState<TaskStatusCategory[]>(
    () => readStoredFilters().statusFilters
  );
  const [priorityFilters, setPriorityFilters] = useState<TaskPriority[]>(
    () => readStoredFilters().priorityFilters
  );
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [guildFilters, setGuildFilters] = useState<number[]>(
    () => readStoredFilters().guildFilters
  );

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

  const taskListParams: ListTasksApiV1TasksGetParams = {
    scope: "global",
    ...(statusFilters.length > 0 && { status_category: statusFilters }),
    ...(priorityFilters.length > 0 && { priorities: priorityFilters }),
    ...(guildFilters.length > 0 && { guild_ids: guildFilters as unknown as number[] }),
    page,
    page_size: pageSize,
    ...(sortBy && { sort_by: sortBy }),
    ...(sortDir && { sort_dir: sortDir }),
  };

  const tasksQuery = useQuery<TaskListResponse>({
    queryKey: getListTasksApiV1TasksGetQueryKey(taskListParams),
    queryFn: () => listTasksApiV1TasksGet(taskListParams) as unknown as Promise<TaskListResponse>,
    placeholderData: keepPreviousData,
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams: ListTasksApiV1TasksGetParams = {
        scope: "global",
        ...(statusFilters.length > 0 && { status_category: statusFilters }),
        ...(priorityFilters.length > 0 && { priorities: priorityFilters }),
        ...(guildFilters.length > 0 && { guild_ids: guildFilters as unknown as number[] }),
        page: targetPage,
        page_size: pageSize,
        ...(sortBy && { sort_by: sortBy }),
        ...(sortDir && { sort_dir: sortDir }),
      };

      void localQueryClient.prefetchQuery({
        queryKey: getListTasksApiV1TasksGetQueryKey(prefetchParams),
        queryFn: () =>
          listTasksApiV1TasksGet(prefetchParams) as unknown as Promise<TaskListResponse>,
        staleTime: 30_000,
      });
    },
    [statusFilters, priorityFilters, guildFilters, pageSize, sortBy, sortDir, localQueryClient]
  );

  const projectsQuery = useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey(),
    queryFn: () => listProjectsApiV1ProjectsGet() as unknown as Promise<Project[]>,
  });

  const templatesQuery = useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey({ template: true }),
    queryFn: () =>
      listProjectsApiV1ProjectsGet({ template: true }) as unknown as Promise<Project[]>,
  });

  const archivedProjectsQuery = useQuery<Project[]>({
    queryKey: getListProjectsApiV1ProjectsGetQueryKey({ archived: true }),
    queryFn: () =>
      listProjectsApiV1ProjectsGet({ archived: true }) as unknown as Promise<Project[]>,
  });

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
      return await (updateTaskApiV1TasksTaskIdPatch(
        taskId,
        { task_status_id: taskStatusId } as never,
        guildId ? { headers: { "X-Guild-ID": String(guildId) } } : undefined
      ) as unknown as Promise<Task>);
    },
    onSuccess: (updatedTask) => {
      // Invalidate all tasks queries since the query key includes filter params
      void invalidateAllTasks();
      const cached = projectStatusCache.current.get(updatedTask.project_id);
      if (cached && !cached.statuses.some((status) => status.id === updatedTask.task_status.id)) {
        cached.statuses.push(updatedTask.task_status);
      }
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

  useEffect(() => {
    const payload = {
      statusFilters,
      priorityFilters,
      guildFilters,
    };
    setItem(MY_TASKS_FILTERS_KEY, JSON.stringify(payload));
  }, [statusFilters, priorityFilters, guildFilters]);

  const fetchProjectStatuses = useCallback(async (projectId: number, guildId: number | null) => {
    const cached = projectStatusCache.current.get(projectId);
    if (cached?.complete) {
      return cached.statuses;
    }
    if (!guildId) {
      return cached?.statuses ?? [];
    }
    const statuses = await (listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet(projectId, {
      headers: { "X-Guild-ID": String(guildId) },
    }) as unknown as Promise<ProjectTaskStatus[]>);
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
    await table.localQueryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
  }, [table.localQueryClient]);

  const columns = useMemo(
    () =>
      globalTaskColumns({
        activeGuildId: table.activeGuildId,
        isUpdatingTaskStatus: table.isUpdatingTaskStatus,
        changeTaskStatus: table.changeTaskStatus,
        changeTaskStatusById: table.changeTaskStatusById,
        fetchProjectStatuses: table.fetchProjectStatuses,
        projectStatusCache: table.projectStatusCache,
        projectsById: table.projectsById,
        t: t as TranslateFn,
      }),
    [
      table.activeGuildId,
      table.isUpdatingTaskStatus,
      table.changeTaskStatus,
      table.changeTaskStatusById,
      table.fetchProjectStatuses,
      table.projectStatusCache,
      table.projectsById,
      t,
    ]
  );

  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("myTasks.groupByDate") },
      { id: "guild", label: t("myTasks.groupByGuild") },
    ],
    [t]
  );

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("myTasks.title")}</h1>
          <p className="text-muted-foreground">{t("myTasks.subtitle")}</p>
        </div>

        <GlobalTaskFilters
          statusFilters={table.statusFilters}
          setStatusFilters={table.setStatusFilters}
          priorityFilters={table.priorityFilters}
          setPriorityFilters={table.setPriorityFilters}
          guildFilters={table.guildFilters}
          setGuildFilters={table.setGuildFilters}
          filtersOpen={table.filtersOpen}
          setFiltersOpen={table.setFiltersOpen}
          guilds={guilds}
        />

        <div className="relative">
          {table.isRefetching ? (
            <div className="bg-background/60 absolute inset-0 z-10 flex items-start justify-center pt-4">
              <div className="bg-background border-border flex items-center gap-2 rounded-md border px-4 py-2 shadow-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-muted-foreground text-sm">{t("updating")}</span>
              </div>
            </div>
          ) : null}
          {table.isInitialLoad ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : table.hasError ? (
            <p className="text-destructive py-8 text-center text-sm">{t("myTasks.loadError")}</p>
          ) : (
            <DataTable
              columns={columns}
              data={table.displayTasks}
              groupingOptions={groupingOptions}
              initialState={{
                grouping: ["date group"],
                expanded: true,
                columnVisibility: { "date group": false, guild: false },
              }}
              initialSorting={[
                { id: "date group", desc: false },
                { id: "due date", desc: false },
              ]}
              enableFilterInput
              filterInputColumnKey="title"
              filterInputPlaceholder={t("filters.filterPlaceholder")}
              enablePagination
              manualPagination
              pageCount={table.totalPages}
              rowCount={table.totalCount}
              onPaginationChange={(pag) => {
                if (pag.pageSize !== table.pageSize) {
                  table.setPageSize(pag.pageSize);
                  table.setPage(1);
                } else {
                  table.setPage(pag.pageIndex + 1);
                }
              }}
              onPrefetchPage={(pageIndex) => table.prefetchPage(pageIndex + 1)}
              manualSorting
              onSortingChange={table.handleSortingChange}
              enableResetSorting
              enableColumnVisibilityDropdown
            />
          )}
        </div>
      </div>
    </PullToRefresh>
  );
};
