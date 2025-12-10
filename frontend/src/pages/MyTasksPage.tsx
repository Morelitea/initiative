import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
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
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { queryClient } from "@/lib/queryClient";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import type {
  Project,
  ProjectTaskStatus,
  Task,
  TaskPriority,
  TaskStatusCategory,
} from "@/types/api";
import { formatDistance, isPast } from "date-fns";
import { SortIcon } from "@/components/SortIcon";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getTaskDateStatus, getTaskDateStatusLabel } from "@/lib/taskDateStatus";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";

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

const INITIATIVE_FILTER_ALL = "all";
const GUILD_FILTER_ALL = "all";
const MY_TASKS_FILTERS_KEY = "initiative-my-tasks-filters";
const STATUS_FILTER_VALUES: Array<"all" | "incomplete" | TaskStatusCategory> = [
  "all",
  "incomplete",
  ...statusOptions.map((option) => option.value),
];
const PRIORITY_FILTER_VALUES: Array<"all" | TaskPriority> = ["all", ...priorityOrder];
const FILTER_DEFAULTS = {
  statusFilter: "incomplete" as "all" | "incomplete" | TaskStatusCategory,
  priorityFilter: "all" as "all" | TaskPriority,
  initiativeFilter: INITIATIVE_FILTER_ALL,
  guildFilter: GUILD_FILTER_ALL,
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
    const statusFilter = STATUS_FILTER_VALUES.includes(parsed?.statusFilter)
      ? parsed.statusFilter
      : FILTER_DEFAULTS.statusFilter;
    const priorityFilter = PRIORITY_FILTER_VALUES.includes(parsed?.priorityFilter)
      ? parsed.priorityFilter
      : FILTER_DEFAULTS.priorityFilter;
    const initiativeFilter =
      typeof parsed?.initiativeFilter === "string"
        ? parsed.initiativeFilter
        : FILTER_DEFAULTS.initiativeFilter;
    const guildFilter =
      typeof parsed?.guildFilter === "string" ? parsed.guildFilter : FILTER_DEFAULTS.guildFilter;
    return {
      statusFilter,
      priorityFilter,
      initiativeFilter,
      guildFilter,
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

const getGuildInitials = (name: string) => {
  const trimmed = name.trim();
  if (!trimmed) {
    return "G";
  }
  return trimmed
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
};

const getGuildGroupLabel = (task: Task) => task.guild?.name ?? guild_DEFAULT_LABEL;

export const MyTasksPage = () => {
  const { user } = useAuth();
  const { guilds, activeGuildId, switchGuild } = useGuilds();
  const navigate = useNavigate();
  const projectStatusCache = useRef<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >(new Map());
  const [switchingTaskId, setSwitchingTaskId] = useState<number | null>(null);

  const tasksQuery = useQuery<Task[]>({
    queryKey: ["tasks", "global"],
    queryFn: async () => {
      const response = await apiClient.get<Task[]>("/tasks/", { params: { scope: "global" } });
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
      queryClient.setQueryData<Task[] | undefined>(["tasks", "global"], (prev) => {
        if (!prev) {
          return prev;
        }
        return prev.map((task) => (task.id === updatedTask.id ? updatedTask : task));
      });
      const cached = projectStatusCache.current.get(updatedTask.project_id);
      if (cached && !cached.statuses.some((status) => status.id === updatedTask.task_status.id)) {
        cached.statuses.push(updatedTask.task_status);
      }
    },
  });

  const [statusFilter, setStatusFilter] = useState<"all" | "incomplete" | TaskStatusCategory>(
    () => readStoredFilters().statusFilter
  );
  const [priorityFilter, setPriorityFilter] = useState<"all" | TaskPriority>(
    () => readStoredFilters().priorityFilter
  );
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    () => readStoredFilters().initiativeFilter
  );
  const [guildFilter, setGuildFilter] = useState<string>(() => readStoredFilters().guildFilter);
  const [statusCacheVersion, setStatusCacheVersion] = useState(0);

  const projectsById = useMemo(() => {
    const result: Record<number, Project> = {};
    projectsQuery.data?.forEach((project) => {
      result[project.id] = project;
    });
    return result;
  }, [projectsQuery.data]);

  const initiativeOptions = useMemo(() => {
    const map = new Map<number, string>();
    projectsQuery.data?.forEach((project) => {
      if (project.initiative_id && project.initiative?.name) {
        map.set(project.initiative_id, project.initiative.name);
      }
    });
    return Array.from(map.entries())
      .map(([id, name]) => ({ id: String(id), name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [projectsQuery.data]);

  const tasks = useMemo(() => tasksQuery.data ?? [], [tasksQuery.data]);
  useEffect(() => {
    let updated = false;
    tasks.forEach((task) => {
      const cached = projectStatusCache.current.get(task.project_id);
      if (cached) {
        if (!cached.statuses.some((status) => status.id === task.task_status.id)) {
          cached.statuses.push(task.task_status);
          updated = true;
        }
      } else {
        projectStatusCache.current.set(task.project_id, {
          statuses: [task.task_status],
          complete: false,
        });
        updated = true;
      }
    });
    if (updated) {
      setStatusCacheVersion((prev) => prev + 1);
    }
  }, [tasks]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const payload = {
      statusFilter,
      priorityFilter,
      initiativeFilter,
      guildFilter,
    };
    window.localStorage.setItem(MY_TASKS_FILTERS_KEY, JSON.stringify(payload));
  }, [statusFilter, priorityFilter, initiativeFilter, guildFilter]);

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
    setStatusCacheVersion((prev) => prev + 1);
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

  const projectStatusesForTask = useCallback(
    (task: Task) => projectStatusCache.current.get(task.project_id)?.statuses ?? [task.task_status],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [statusCacheVersion]
  );

  const ensureTaskGuildContext = useCallback(
    async (task: Task) => {
      if (!task.guild || task.guild.id === activeGuildId) {
        return true;
      }

      setSwitchingTaskId(task.id);
      const toastId = toast.loading(`Switching to ${task.guild.name}...`);
      try {
        await switchGuild(task.guild.id);
        toast.success(`Switched to ${task.guild.name}`, { id: toastId });
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
      const targetGuildId = task.guild?.id ?? activeGuildId ?? null;
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
      const targetGuildId = task.guild?.id ?? activeGuildId ?? null;
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
    projectsQuery.data?.forEach((project) => {
      if (project.is_archived || project.is_template) {
        ids.add(project.id);
      }
    });
    templatesQuery.data?.forEach((project) => ids.add(project.id));
    archivedProjectsQuery.data?.forEach((project) => ids.add(project.id));
    return ids;
  }, [projectsQuery.data, templatesQuery.data, archivedProjectsQuery.data]);

  const myTasks = useMemo(() => {
    if (!user) {
      return [];
    }
    return tasks.filter((task) => {
      if (excludedProjectIds.has(task.project_id)) {
        return false;
      }
      if (task.project?.is_archived || task.project?.is_template) {
        return false;
      }
      return task.assignees.some((assignee) => assignee.id === user.id);
    });
  }, [tasks, user, excludedProjectIds]);

  const filteredTasks = useMemo(() => {
    const selectedInitiativeId =
      initiativeFilter === INITIATIVE_FILTER_ALL ? null : Number(initiativeFilter);
    const selectedGuildId = guildFilter === GUILD_FILTER_ALL ? null : Number(guildFilter);
    return myTasks.filter((task) => {
      if (statusFilter === "incomplete") {
        if (task.task_status.category === "done") {
          return false;
        }
      } else if (statusFilter !== "all" && task.task_status.category !== statusFilter) {
        return false;
      }

      if (priorityFilter !== "all" && task.priority !== priorityFilter) {
        return false;
      }

      if (selectedInitiativeId) {
        const project = projectsById[task.project_id];
        const fallbackInitiativeId = task.project?.initiative_id ?? null;
        const matchesProject = project?.initiative_id === selectedInitiativeId;
        const matchesFallback = fallbackInitiativeId === selectedInitiativeId;
        if (!matchesProject && !matchesFallback) {
          return false;
        }
      }
      if (selectedGuildId) {
        if (task.guild?.id !== selectedGuildId) {
          return false;
        }
      }
      return true;
    });
  }, [myTasks, statusFilter, priorityFilter, initiativeFilter, guildFilter, projectsById]);

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
      cell: ({ row }) => {
        const task = row.original;
        if (!task.start_date) {
          return <span className="text-muted-foreground">—</span>;
        }
        const startDate = new Date(task.start_date);
        const isStartPast = isPast(startDate);
        return (
          <div className={`min-w-30 ${isStartPast ? "text-primary" : "text-muted-foreground"}`}>
            {formatDistance(startDate, new Date(), { addSuffix: true })}
          </div>
        );
      },
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
      cell: ({ row }) => {
        const task = row.original;
        if (!task.due_date) {
          return <span className="text-muted-foreground">—</span>;
        }
        const dueDate = new Date(task.due_date);
        const isDuePast = isPast(dueDate);
        return (
          <div className={`min-w-30 ${isDuePast ? "text-destructive" : ""}`}>
            {formatDistance(dueDate, new Date(), { addSuffix: true })}
          </div>
        );
      },
      sortingFn: dateSortingFn,
    },
    {
      id: "initiative",
      header: () => <span className="font-medium">Initiative</span>,
      cell: ({ row }) => {
        const task = row.original;
        const project = projectsById[task.project_id];
        const fallbackProject = task.project;
        const initiative = project?.initiative ?? fallbackProject?.initiative ?? null;
        if (!initiative) {
          return <span className="text-muted-foreground text-sm">—</span>;
        }
        const initiativePath = `/initiatives/${initiative.id}`;
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
              <InitiativeColorDot color={initiative.color} />
              {initiative.name}
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
        const fallbackProject = task.project;
        const guild = task.guild;
        const projectLabel =
          project?.name ?? fallbackProject?.name ?? `Project #${task.project_id}`;
        const projectIdentifier = project?.id ?? fallbackProject?.id ?? task.project_id;
        const projectPath = `/projects/${projectIdentifier}`;
        return (
          <div className="min-w-30">
            <div className="flex flex-wrap items-center gap-2">
              {guild ? (
                <>
                  <Avatar className="border-border h-6 w-6 border">
                    {guild.icon_base64 ? (
                      <AvatarImage src={guild.icon_base64} alt={guild.name} />
                    ) : null}
                    <AvatarFallback className="text-[10px] font-medium">
                      {getGuildInitials(guild.name)}
                    </AvatarFallback>
                  </Avatar>
                  <span className="text-muted-foreground text-xs sm:text-sm">{guild.name}</span>
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
        const projectStatuses = projectStatusesForTask(task)
          .slice()
          .sort((a, b) => a.position - b.position);
        return (
          <div className="space-y-1">
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
              onOpenChange={(open) => {
                if (open) {
                  const guildId = task.guild?.id ?? activeGuildId ?? null;
                  void fetchProjectStatuses(task.project_id, guildId);
                }
              }}
              disabled={isUpdatingTaskStatus}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {projectStatuses.map((status) => (
                  <SelectItem key={status.id} value={String(status.id)}>
                    {status.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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

  if (
    tasksQuery.isLoading ||
    projectsQuery.isLoading ||
    templatesQuery.isLoading ||
    archivedProjectsQuery.isLoading
  ) {
    return <p className="text-muted-foreground text-sm">Loading your tasks…</p>;
  }

  if (
    tasksQuery.isError ||
    projectsQuery.isError ||
    templatesQuery.isError ||
    archivedProjectsQuery.isError
  ) {
    return <p className="text-destructive text-sm">Unable to load your tasks.</p>;
  }

  return (
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
                className="text-muted-foreground text-xs font-medium"
              >
                Status category
              </Label>
              <Select
                value={statusFilter}
                onValueChange={(value) =>
                  setStatusFilter(value as "all" | "incomplete" | TaskStatusCategory)
                }
              >
                <SelectTrigger id="task-status-filter">
                  <SelectValue placeholder="All status categories" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="incomplete">Incomplete</SelectItem>
                  <SelectItem value="all">All status categories</SelectItem>
                  {statusOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-full sm:w-60 lg:flex-1">
              <Label
                htmlFor="task-priority-filter"
                className="text-muted-foreground text-xs font-medium"
              >
                Priority
              </Label>
              <Select
                value={priorityFilter}
                onValueChange={(value) => setPriorityFilter(value as typeof priorityFilter)}
              >
                <SelectTrigger id="task-priority-filter">
                  <SelectValue placeholder="All priorities" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All priorities</SelectItem>
                  {priorityOrder.map((priority) => (
                    <SelectItem key={priority} value={priority}>
                      {priority.replace("_", " ")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-full sm:w-60 lg:flex-1">
              <Label
                htmlFor="task-guild-filter"
                className="text-muted-foreground text-xs font-medium"
              >
                Guild
              </Label>
              <Select value={guildFilter} onValueChange={setGuildFilter}>
                <SelectTrigger id="task-guild-filter">
                  <SelectValue placeholder="All guilds" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={GUILD_FILTER_ALL}>All guilds</SelectItem>
                  {guilds.map((guild) => (
                    <SelectItem key={guild.id} value={String(guild.id)}>
                      {guild.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-full sm:w-60 lg:flex-1">
              <Label
                htmlFor="task-initiative-filter"
                className="text-muted-foreground text-xs font-medium"
              >
                Initiative
              </Label>
              <Select value={initiativeFilter} onValueChange={setInitiativeFilter}>
                <SelectTrigger id="task-initiative-filter">
                  <SelectValue placeholder="All initiatives" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={INITIATIVE_FILTER_ALL}>All initiatives</SelectItem>
                  {initiativeOptions.map((initiative) => (
                    <SelectItem key={initiative.id} value={initiative.id}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <DataTable
        columns={columns}
        data={filteredTasks}
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
    </div>
  );
};
