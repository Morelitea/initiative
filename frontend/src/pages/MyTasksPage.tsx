import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { ChevronDown, Filter, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { getItem, setItem } from "@/lib/storage";
import { summarizeRecurrence } from "@/lib/recurrence";
import type { TranslateFn } from "@/types/i18n";
import { guildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useGuilds } from "@/hooks/useGuilds";
import { queryClient } from "@/lib/queryClient";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import { PullToRefresh } from "@/components/PullToRefresh";
import type {
  Project,
  ProjectTaskStatus,
  Task,
  TaskListResponse,
  TaskPriority,
  TaskStatusCategory,
} from "@/types/api";
import { SortIcon } from "@/components/SortIcon";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { TaskPrioritySelector } from "@/components/tasks/TaskPrioritySelector";
import { TaskStatusSelector } from "@/components/tasks/TaskStatusSelector";
import { TagBadge } from "@/components/tags/TagBadge";

const statusFallbackOrder: Record<TaskStatusCategory, TaskStatusCategory[]> = {
  backlog: ["backlog"],
  todo: ["todo", "backlog"],
  in_progress: ["in_progress", "todo", "backlog"],
  done: ["done", "in_progress", "todo", "backlog"],
};
const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];

const MY_TASKS_FILTERS_KEY = "initiative-my-tasks-filters";
const FILTER_DEFAULTS = {
  statusFilters: ["backlog", "todo", "in_progress"] as TaskStatusCategory[],
  priorityFilters: [] as TaskPriority[],
  guildFilters: [] as number[],
};

const readStoredFilters = () => {
  try {
    const raw = getItem(MY_TASKS_FILTERS_KEY);
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

export const MyTasksPage = () => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { guilds, activeGuildId } = useGuilds();
  const localQueryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;
  const projectStatusCache = useRef<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >(new Map());

  const statusOptions = useMemo(
    () => [
      { value: "backlog" as TaskStatusCategory, label: t("statusCategory.backlog") },
      { value: "todo" as TaskStatusCategory, label: t("statusCategory.todo") },
      { value: "in_progress" as TaskStatusCategory, label: t("statusCategory.in_progress") },
      { value: "done" as TaskStatusCategory, label: t("statusCategory.done") },
    ],
    [t]
  );

  const guildDefaultLabel = t("myTasks.noGuild");
  const getGuildGroupLabel = useCallback(
    (task: Task) => task.guild_name ?? guildDefaultLabel,
    [guildDefaultLabel]
  );

  // Helper to create guild-scoped paths for a task
  const taskGuildPath = (task: Task, path: string) => {
    const guildId = task.guild_id ?? activeGuildId;
    return guildId ? guildPath(guildId, path) : path;
  };

  const handleRefresh = useCallback(async () => {
    await localQueryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
  }, [localQueryClient]);

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

  const tasksQuery = useQuery<TaskListResponse>({
    queryKey: [
      "tasks",
      "global",
      statusFilters,
      priorityFilters,
      guildFilters,
      page,
      pageSize,
      sortBy,
      sortDir,
    ],
    queryFn: async () => {
      const params: Record<string, string | string[] | number | number[]> = { scope: "global" };

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
      const params: Record<string, string | string[] | number | number[]> = { scope: "global" };
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
    [statusFilters, priorityFilters, guildFilters, pageSize, sortBy, sortDir, localQueryClient]
  );

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
      // Invalidate all tasks queries since the query key includes filter params
      void queryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
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

  const displayTasks = useMemo(() => {
    // Backend already filters by assignee, status, priority, initiative, and guild
    // We only need to exclude archived and template projects on the frontend
    return tasks.filter((task) => !excludedProjectIds.has(task.project_id));
  }, [tasks, excludedProjectIds]);

  const columns: ColumnDef<Task>[] = [
    {
      id: "date group",
      accessorFn: (task) => getTaskDateStatus(task.start_date, task.due_date),
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.dateWindow")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ getValue }) => (
        <span className="text-base font-medium">
          {getTaskDateStatusLabel(getValue<string>(), t as TranslateFn)}
        </span>
      ),
      enableHiding: true,
      enableSorting: true,
      sortingFn: "alphanumeric",
    },
    {
      id: "guild",
      accessorFn: (task) => getGuildGroupLabel(task),
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.guild")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ getValue }) => <span className="text-base font-medium">{getValue<string>()}</span>,
      enableHiding: true,
      enableSorting: true,
      sortingFn: "alphanumeric",
    },
    {
      id: "completed",
      header: () => <span className="font-medium">{t("columns.done")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <Checkbox
            checked={task.task_status.category === "done"}
            onCheckedChange={(value) => {
              if (isUpdatingTaskStatus) {
                return;
              }
              const targetCategory: TaskStatusCategory = value ? "done" : "in_progress";
              void changeTaskStatus(task, targetCategory);
            }}
            className="h-6 w-6"
            disabled={isUpdatingTaskStatus}
            aria-label={
              task.task_status.category === "done"
                ? t("checkbox.markInProgress")
                : t("checkbox.markDone")
            }
          />
        );
      },
      enableSorting: false,
      size: 64,
      enableHiding: false,
    },
    {
      accessorKey: "title",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.task")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        const recurrenceSummary = task.recurrence
          ? summarizeRecurrence(
              task.recurrence,
              {
                referenceDate: task.start_date || task.due_date,
                strategy: task.recurrence_strategy,
              },
              t as TranslateFn
            )
          : null;
        return (
          <div className="flex min-w-60 flex-col text-left">
            <div className="flex">
              <Link
                to={taskGuildPath(task, `/tasks/${task.id}`)}
                className="text-foreground flex w-full items-center gap-2 font-medium hover:underline"
              >
                {task.title}
              </Link>
              <TaskDescriptionHoverCard task={task} />
            </div>
            <div className="text-muted-foreground space-y-1 text-xs">
              {recurrenceSummary ? <p>{recurrenceSummary}</p> : null}
            </div>
            <TaskChecklistProgress
              progress={task.subtask_progress}
              className="mt-2 max-w-[200px]"
            />
          </div>
        );
      },
      sortingFn: "alphanumeric",
      enableHiding: false,
    },
    {
      id: "start date",
      accessorKey: "start_date",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex min-w-30 items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.startDate")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => <DateCell date={row.original.start_date} isPastVariant="primary" />,
      sortingFn: dateSortingFn,
    },
    {
      id: "due date",
      accessorKey: "due_date",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex min-w-30 items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.dueDate")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => (
        <DateCell
          date={row.original.due_date}
          isPastVariant="destructive"
          isDone={row.original.task_status?.category === "done"}
        />
      ),
      sortingFn: dateSortingFn,
    },
    {
      id: "path",
      header: () => <span className="font-medium">{t("columns.projectPath")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        const project = projectsById[task.project_id];
        const projectLabel =
          task.project_name ?? project?.name ?? t("projectFallback", { id: task.project_id });
        const projectIdentifier = project?.id ?? task.project_id;
        const guildName = task.guild_name;
        const initiativeId = task.initiative_id ?? project?.initiative_id;
        const initiativeName = task.initiative_name ?? project?.initiative?.name;
        const initiativeColor = task.initiative_color ?? project?.initiative?.color;
        return (
          <div className="min-w-30">
            <div className="flex flex-wrap items-center gap-2">
              {guildName ? (
                <>
                  <span className="text-muted-foreground text-xs sm:text-sm">{guildName}</span>
                  <span className="text-muted-foreground text-sm" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              {initiativeId && initiativeName ? (
                <>
                  <Link
                    to={taskGuildPath(task, `/initiatives/${initiativeId}`)}
                    className="text-muted-foreground flex items-center gap-2 text-sm"
                  >
                    <InitiativeColorDot color={initiativeColor ?? undefined} />
                    {initiativeName}
                  </Link>

                  <span className="text-muted-foreground text-sm" aria-hidden>
                    &gt;
                  </span>
                </>
              ) : null}
              <Link
                to={taskGuildPath(task, `/projects/${projectIdentifier}`)}
                className="text-primary text-sm font-medium hover:underline"
              >
                {projectLabel}
              </Link>
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: "priority",
      id: "priority",
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("columns.priority")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        return (
          <TaskPrioritySelector
            task={task}
            guildId={task.guild_id ?? activeGuildId}
            disabled={isUpdatingTaskStatus}
          />
        );
      },
      sortingFn: prioritySortingFn,
    },
    {
      id: "tags",
      header: () => <span className="font-medium">{t("columns.tags")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        const taskTags = task.tags ?? [];
        if (taskTags.length === 0) {
          return <span className="text-muted-foreground text-sm">—</span>;
        }
        return (
          <div className="flex flex-wrap gap-1">
            {taskTags.slice(0, 3).map((tag) => (
              <TagBadge
                key={tag.id}
                tag={tag}
                size="sm"
                to={taskGuildPath(task, `/tags/${tag.id}`)}
              />
            ))}
            {taskTags.length > 3 && (
              <span className="text-muted-foreground text-xs">+{taskTags.length - 3}</span>
            )}
          </div>
        );
      },
      size: 150,
    },
    {
      id: "status",
      header: () => <span className="font-medium">{t("columns.status")}</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <div className="space-y-1">
            <TaskStatusSelector
              task={task}
              activeGuildId={activeGuildId}
              isUpdatingTaskStatus={isUpdatingTaskStatus}
              changeTaskStatusById={changeTaskStatusById}
              fetchProjectStatuses={fetchProjectStatuses}
              projectStatusCache={projectStatusCache}
            />
          </div>
        );
      },
    },
  ];
  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("myTasks.groupByDate") },
      { id: "guild", label: t("myTasks.groupByGuild") },
    ],
    [t]
  );

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

  // Check if this is the true initial load (no data exists yet)
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

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("myTasks.title")}</h1>
          <p className="text-muted-foreground">{t("myTasks.subtitle")}</p>
        </div>

        <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
          <div className="flex items-center justify-between sm:hidden">
            <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
              <Filter className="h-4 w-4" />
              {t("filters.heading")}
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 px-3">
                {filtersOpen ? t("filters.hide") : t("filters.show")}
                <ChevronDown
                  className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
                />
              </Button>
            </CollapsibleTrigger>
          </div>
          <CollapsibleContent forceMount className="data-[state=closed]:hidden">
            <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="task-status-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  {t("filters.filterByStatusCategory")}
                </Label>
                <MultiSelect
                  selectedValues={statusFilters}
                  options={statusOptions.map((option) => ({
                    value: option.value,
                    label: option.label,
                  }))}
                  onChange={(values) => setStatusFilters(values as TaskStatusCategory[])}
                  placeholder={t("filters.allStatusCategories")}
                  emptyMessage={t("filters.noStatusCategories")}
                />
              </div>
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="task-priority-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  {t("filters.filterByPriority")}
                </Label>
                <MultiSelect
                  selectedValues={priorityFilters}
                  options={priorityOrder.map((priority) => ({
                    value: priority,
                    label: t(`priority.${priority}` as never),
                  }))}
                  onChange={(values) => setPriorityFilters(values as TaskPriority[])}
                  placeholder={t("filters.allPriorities")}
                  emptyMessage={t("filters.noPriorities")}
                />
              </div>
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="task-guild-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  {t("filters.filterByGuild")}
                </Label>
                <MultiSelect
                  selectedValues={guildFilters.map(String)}
                  options={guilds.map((guild) => ({
                    value: String(guild.id),
                    label: guild.name,
                  }))}
                  onChange={(values) => {
                    const numericValues = values.map(Number).filter(Number.isFinite);
                    setGuildFilters(numericValues);
                  }}
                  placeholder={t("filters.allGuilds")}
                  emptyMessage={t("filters.noGuilds")}
                />
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        <div className="relative">
          {isRefetching ? (
            <div className="bg-background/60 absolute inset-0 z-10 flex items-start justify-center pt-4">
              <div className="bg-background border-border flex items-center gap-2 rounded-md border px-4 py-2 shadow-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-muted-foreground text-sm">{t("updating")}</span>
              </div>
            </div>
          ) : null}
          {isInitialLoad ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : hasError ? (
            <p className="text-destructive py-8 text-center text-sm">{t("myTasks.loadError")}</p>
          ) : (
            <DataTable
              columns={columns}
              data={displayTasks}
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
              pageCount={totalPages}
              rowCount={totalCount}
              onPaginationChange={(pag) => {
                if (pag.pageSize !== pageSize) {
                  setPageSize(pag.pageSize);
                  setPage(1);
                } else {
                  setPage(pag.pageIndex + 1);
                }
              }}
              onPrefetchPage={(pageIndex) => prefetchPage(pageIndex + 1)}
              manualSorting
              onSortingChange={handleSortingChange}
              enableResetSorting
              enableColumnVisibilityDropdown
            />
          )}
        </div>
      </div>
    </PullToRefresh>
  );
};
