import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, Filter, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { summarizeRecurrence } from "@/lib/recurrence";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelect } from "@/components/ui/multi-select";
import { useGuilds } from "@/hooks/useGuilds";
import { queryClient } from "@/lib/queryClient";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import { PullToRefresh } from "@/components/PullToRefresh";
import type {
  Project,
  ProjectTaskStatus,
  Task,
  TaskPriority,
  TaskStatusCategory,
} from "@/types/api";
import { SortIcon } from "@/components/SortIcon";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { DateCell } from "@/components/tasks/TaskDateCell";

const statusOptions: { value: TaskStatusCategory; label: string }[] = [
  { value: "backlog", label: "Backlog" },
  { value: "todo", label: "To Do" },
  { value: "in_progress", label: "In Progress" },
  { value: "done", label: "Done" },
];

const statusFallbackOrder: Record<TaskStatusCategory, TaskStatusCategory[]> = {
  backlog: ["backlog"],
  todo: ["todo", "backlog"],
  in_progress: ["in_progress", "todo", "backlog"],
  done: ["done", "in_progress", "todo", "backlog"],
};
const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];
const guild_DEFAULT_LABEL = "No Guild";

const MY_TASKS_FILTERS_KEY = "initiative-my-tasks-filters";
const FILTER_DEFAULTS = {
  statusFilters: ["backlog", "todo", "in_progress"] as TaskStatusCategory[],
  priorityFilters: [] as TaskPriority[],
  initiativeFilters: [] as number[],
  guildFilters: [] as number[],
};

const readStoredFilters = () => {
  if (typeof window === "undefined") {
    return FILTER_DEFAULTS;
  }
  try {
    const raw = window.localStorage.getItem(MY_TASKS_FILTERS_KEY);
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
      initiativeFilters: Array.isArray(parsed?.initiativeFilters)
        ? parsed.initiativeFilters
        : FILTER_DEFAULTS.initiativeFilters,
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

const getGuildGroupLabel = (task: Task) => task.guild_name ?? guild_DEFAULT_LABEL;

// Component for task status selector that manages its own state
const TaskStatusSelector = ({
  task,
  activeGuildId,
  isUpdatingTaskStatus,
  changeTaskStatusById,
  fetchProjectStatuses,
  projectStatusCache,
}: {
  task: Task;
  activeGuildId: number | null;
  isUpdatingTaskStatus: boolean;
  changeTaskStatusById: (task: Task, statusId: number) => Promise<void>;
  fetchProjectStatuses: (projectId: number, guildId: number | null) => Promise<ProjectTaskStatus[]>;
  projectStatusCache: React.MutableRefObject<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >;
}) => {
  const [statuses, setStatuses] = useState<ProjectTaskStatus[]>(() => {
    const cached = projectStatusCache.current.get(task.project_id);
    return cached?.statuses ?? [task.task_status];
  });

  const handleOpenChange = useCallback(
    async (open: boolean) => {
      if (open) {
        const guildId = task.guild_id ?? activeGuildId ?? null;
        const fetchedStatuses = await fetchProjectStatuses(task.project_id, guildId);
        setStatuses(fetchedStatuses);
      }
    },
    [task, activeGuildId, fetchProjectStatuses]
  );

  const sortedStatuses = useMemo(
    () => [...statuses].sort((a, b) => a.position - b.position),
    [statuses]
  );

  return (
    <Select
      value={String(task.task_status.id)}
      onValueChange={(value) => {
        const targetId = Number(value);
        if (Number.isNaN(targetId)) {
          toast.error("Invalid status selected.");
          return;
        }
        void changeTaskStatusById(task, targetId);
      }}
      onOpenChange={handleOpenChange}
      disabled={isUpdatingTaskStatus}
    >
      <SelectTrigger className="w-40">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {sortedStatuses.map((status) => (
          <SelectItem key={status.id} value={String(status.id)}>
            {status.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
};

export const MyTasksPage = () => {
  const { guilds, activeGuildId, switchGuild } = useGuilds();
  const navigate = useNavigate();
  const localQueryClient = useQueryClient();
  const projectStatusCache = useRef<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >(new Map());
  const [switchingTaskId, setSwitchingTaskId] = useState<number | null>(null);

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
  const [initiativeFilters, setInitiativeFilters] = useState<number[]>(
    () => readStoredFilters().initiativeFilters
  );
  const [guildFilters, setGuildFilters] = useState<number[]>(
    () => readStoredFilters().guildFilters
  );

  const tasksQuery = useQuery<Task[]>({
    queryKey: ["tasks", "global", statusFilters, priorityFilters, initiativeFilters, guildFilters],
    queryFn: async () => {
      const params: Record<string, string | string[] | number[]> = { scope: "global" };

      if (statusFilters.length > 0) {
        params.status_category = statusFilters;
      }
      if (priorityFilters.length > 0) {
        params.priorities = priorityFilters;
      }
      if (initiativeFilters.length > 0) {
        params.initiative_ids = initiativeFilters;
      }
      if (guildFilters.length > 0) {
        params.guild_ids = guildFilters;
      }

      const response = await apiClient.get<Task[]>("/tasks/", { params });
      return response.data;
    },
  });

  const projectsQuery = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/");
      return response.data;
    },
  });

  const templatesQuery = useQuery<Project[]>({
    queryKey: ["projects", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/", { params: { template: true } });
      return response.data;
    },
  });

  const archivedProjectsQuery = useQuery<Project[]>({
    queryKey: ["projects", "archived"],
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

  const initiativeOptions = useMemo(() => {
    const map = new Map<number, string>();
    const projects = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
    projects.forEach((project) => {
      if (project.initiative_id && project.initiative?.name) {
        map.set(project.initiative_id, project.initiative.name);
      }
    });
    return Array.from(map.entries())
      .map(([id, name]) => ({ id: String(id), name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [projectsQuery.data]);

  const tasks = useMemo(
    () => (Array.isArray(tasksQuery.data) ? tasksQuery.data : []),
    [tasksQuery.data]
  );
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
    if (typeof window === "undefined") {
      return;
    }
    const payload = {
      statusFilters,
      priorityFilters,
      initiativeFilters,
      guildFilters,
    };
    window.localStorage.setItem(MY_TASKS_FILTERS_KEY, JSON.stringify(payload));
  }, [statusFilters, priorityFilters, initiativeFilters, guildFilters]);

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

  const ensureTaskGuildContext = useCallback(
    async (task: Task) => {
      if (!task.guild_id || task.guild_id === activeGuildId) {
        return true;
      }

      setSwitchingTaskId(task.id);
      const toastId = toast.loading(`Switching to ${task.guild_name}...`);
      try {
        await switchGuild(task.guild_id);
        toast.success(`Switched to ${task.guild_name}`, { id: toastId });
        return true;
      } catch (error) {
        console.error(error);
        const message = error instanceof Error ? error.message : "Unable to switch guild";
        toast.error(message, { id: toastId });
        return false;
      } finally {
        setSwitchingTaskId(null);
      }
    },
    [activeGuildId, switchGuild]
  );

  const changeTaskStatusById = useCallback(
    async (task: Task, targetStatusId: number) => {
      const targetGuildId = task.guild_id ?? activeGuildId ?? null;
      if (!targetGuildId) {
        toast.error("Unable to determine guild context for this task.");
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
        const message = error instanceof Error ? error.message : "Unable to update task status.";
        toast.error(message);
      }
    },
    [activeGuildId, updateTaskStatusMutate]
  );

  const changeTaskStatus = useCallback(
    async (task: Task, targetCategory: TaskStatusCategory) => {
      const targetGuildId = task.guild_id ?? activeGuildId ?? null;
      if (!targetGuildId) {
        toast.error("Unable to determine guild context for this task.");
        return;
      }
      const targetStatusId = await resolveStatusIdForCategory(
        task.project_id,
        targetCategory,
        targetGuildId
      );
      if (!targetStatusId) {
        toast.error("Unable to update task status. No matching status found.");
        return;
      }
      await changeTaskStatusById(task, targetStatusId);
    },
    [activeGuildId, changeTaskStatusById, resolveStatusIdForCategory]
  );

  const handleCrossGuildNavigation = useCallback(
    async (task: Task, targetPath: string) => {
      const ready = await ensureTaskGuildContext(task);
      if (ready) {
        navigate(targetPath);
      }
    },
    [ensureTaskGuildContext, navigate]
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
              Date window
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ getValue }) => (
        <span className="text-base font-medium">{getTaskDateStatusLabel(getValue<string>())}</span>
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
              Guild
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
      header: () => <span className="font-medium">Done</span>,
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
                ? "Mark task as in progress"
                : "Mark task as done"
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
              Task
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        const recurrenceSummary = task.recurrence
          ? summarizeRecurrence(task.recurrence, {
              referenceDate: task.start_date || task.due_date,
              strategy: task.recurrence_strategy,
            })
          : null;
        return (
          <div className="flex min-w-60 flex-col text-left">
            <div className="flex">
              <Link
                to={`/tasks/${task.id}`}
                className="text-foreground flex w-full items-center gap-2 font-medium hover:underline"
                onClick={(event) => {
                  event.preventDefault();
                  void handleCrossGuildNavigation(task, `/tasks/${task.id}`);
                }}
              >
                {task.title}
              </Link>
              <TaskDescriptionHoverCard task={task} />
              {switchingTaskId === task.id ? (
                <Loader2 className="text-muted-foreground h-4 w-4 animate-spin" aria-hidden />
              ) : null}
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
              Start Date
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
              Due Date
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
      id: "initiative",
      header: () => <span className="font-medium">Initiative</span>,
      cell: ({ row }) => {
        const task = row.original;
        const project = projectsById[task.project_id];
        const initiativeId = task.initiative_id ?? project?.initiative_id;
        const initiativeName = task.initiative_name ?? project?.initiative?.name;
        const initiativeColor = task.initiative_color ?? project?.initiative?.color;
        if (!initiativeId || !initiativeName) {
          return <span className="text-muted-foreground text-sm">—</span>;
        }
        const initiativePath = `/initiatives/${initiativeId}`;
        return (
          <div className="min-w-40">
            <Link
              to={initiativePath}
              className="text-foreground flex items-center gap-2 text-sm font-medium"
              onClick={(event) => {
                event.preventDefault();
                void handleCrossGuildNavigation(task, initiativePath);
              }}
            >
              <InitiativeColorDot color={initiativeColor ?? undefined} />
              {initiativeName}
            </Link>
          </div>
        );
      },
    },
    {
      id: "project",
      header: () => <span className="font-medium">Project</span>,
      cell: ({ row }) => {
        const task = row.original;
        const project = projectsById[task.project_id];
        const projectLabel = task.project_name ?? project?.name ?? `Project #${task.project_id}`;
        const projectIdentifier = project?.id ?? task.project_id;
        const projectPath = `/projects/${projectIdentifier}`;
        const guildName = task.guild_name;
        return (
          <div className="min-w-30">
            <div className="flex flex-wrap items-center gap-2">
              {guildName ? (
                <>
                  <span className="text-muted-foreground text-xs sm:text-sm">{guildName}</span>
                  <span className="text-muted-foreground text-sm" aria-hidden>
                    {"\u00B7"}
                  </span>
                </>
              ) : null}
              <Link
                to={projectPath}
                className="text-primary text-sm font-medium hover:underline"
                onClick={(event) => {
                  event.preventDefault();
                  void handleCrossGuildNavigation(task, projectPath);
                }}
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
              Priority
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        return (
          <Badge variant={priorityVariant[task.priority]}>{task.priority.replace("_", " ")}</Badge>
        );
      },
      sortingFn: prioritySortingFn,
    },
    {
      id: "status",
      header: () => <span className="font-medium">Status</span>,
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
      { id: "date group", label: "Date" },
      { id: "guild", label: "Guild" },
    ],
    []
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

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">My Tasks</h1>
          <p className="text-muted-foreground">Everything assigned to you across all projects.</p>
        </div>

        <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
          <div className="flex items-center justify-between sm:hidden">
            <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
              <Filter className="h-4 w-4" />
              Filters
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 px-3">
                {filtersOpen ? "Hide" : "Show"}
                <span className="ml-1">filters</span>
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
                  Status category
                </Label>
                <MultiSelect
                  selectedValues={statusFilters}
                  options={statusOptions.map((option) => ({
                    value: option.value,
                    label: option.label,
                  }))}
                  onChange={(values) => setStatusFilters(values as TaskStatusCategory[])}
                  placeholder="All status categories"
                  emptyMessage="No status categories available"
                />
              </div>
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="task-priority-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  Priority
                </Label>
                <MultiSelect
                  selectedValues={priorityFilters}
                  options={priorityOrder.map((priority) => ({
                    value: priority,
                    label: priority.replace("_", " "),
                  }))}
                  onChange={(values) => setPriorityFilters(values as TaskPriority[])}
                  placeholder="All priorities"
                  emptyMessage="No priorities available"
                />
              </div>
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="task-guild-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  Guild
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
                  placeholder="All guilds"
                  emptyMessage="No guilds available"
                />
              </div>
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="task-initiative-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  Initiative
                </Label>
                <MultiSelect
                  selectedValues={initiativeFilters.map(String)}
                  options={initiativeOptions.map((initiative) => ({
                    value: initiative.id,
                    label: initiative.name,
                  }))}
                  onChange={(values) => {
                    const numericValues = values.map(Number).filter(Number.isFinite);
                    setInitiativeFilters(numericValues);
                  }}
                  placeholder="All initiatives"
                  emptyMessage="No initiatives available"
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
                <span className="text-muted-foreground text-sm">Updating…</span>
              </div>
            </div>
          ) : null}
          {isInitialLoad ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : hasError ? (
            <p className="text-destructive py-8 text-center text-sm">Unable to load your tasks.</p>
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
              filterInputPlaceholder="Filter tasks..."
              enablePagination
              enableResetSorting
              enableColumnVisibilityDropdown
            />
          )}
        </div>
      </div>
    </PullToRefresh>
  );
};
