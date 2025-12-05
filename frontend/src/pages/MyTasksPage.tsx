import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Markdown } from "@/components/Markdown";
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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import type {
  Project,
  ProjectTaskStatus,
  Task,
  TaskPriority,
  TaskStatusCategory,
} from "@/types/api";
import { formatDistance } from "date-fns";
import { SortIcon } from "@/components/SortIcon";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

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

const INITIATIVE_FILTER_ALL = "all";
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

export const MyTasksPage = () => {
  const { user } = useAuth();
  const { activeGuildId, switchGuild } = useGuilds();
  const navigate = useNavigate();
  const projectStatusCache = useRef<Map<number, ProjectTaskStatus[]>>(new Map());
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
    mutationFn: async ({ taskId, taskStatusId }: { taskId: number; taskStatusId: number }) => {
      const response = await apiClient.patch<Task>(`/tasks/${taskId}`, {
        task_status_id: taskStatusId,
      });
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
      if (cached && !cached.some((status) => status.id === updatedTask.task_status.id)) {
        cached.push(updatedTask.task_status);
      }
    },
  });

  const [statusFilter, setStatusFilter] = useState<"all" | "incomplete" | TaskStatusCategory>(
    "incomplete"
  );
  const [priorityFilter, setPriorityFilter] = useState<"all" | TaskPriority>("all");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [initiativeFilter, setInitiativeFilter] = useState<string>(INITIATIVE_FILTER_ALL);

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
    tasks.forEach((task) => {
      const cached = projectStatusCache.current.get(task.project_id);
      if (cached) {
        if (!cached.some((status) => status.id === task.task_status.id)) {
          cached.push(task.task_status);
        }
      } else {
        projectStatusCache.current.set(task.project_id, [task.task_status]);
      }
    });
  }, [tasks]);

  const fetchProjectStatuses = useCallback(async (projectId: number) => {
    const cached = projectStatusCache.current.get(projectId);
    if (cached) {
      return cached;
    }
    const response = await apiClient.get<ProjectTaskStatus[]>(
      `/projects/${projectId}/task-statuses/`
    );
    projectStatusCache.current.set(projectId, response.data);
    return response.data;
  }, []);

  const resolveStatusIdForCategory = useCallback(
    async (projectId: number, category: TaskStatusCategory) => {
      const statuses = await fetchProjectStatuses(projectId);
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

  const changeTaskStatus = useCallback(
    async (task: Task, targetCategory: TaskStatusCategory) => {
      const ready = await ensureTaskGuildContext(task);
      if (!ready) {
        return;
      }
      const targetStatusId = await resolveStatusIdForCategory(task.project_id, targetCategory);
      if (!targetStatusId) {
        toast.error("Unable to update task status. No matching status found.");
        return;
      }
      await updateTaskStatusMutate({ taskId: task.id, taskStatusId: targetStatusId });
    },
    [ensureTaskGuildContext, resolveStatusIdForCategory, updateTaskStatusMutate]
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
      return true;
    });
  }, [myTasks, statusFilter, priorityFilter, initiativeFilter, projectsById]);

  const columns: ColumnDef<Task>[] = [
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
            Task
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => column.toggleSorting(isSorted === "asc")}
            >
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
            <div className="flex items-center gap-2">
              <Link
                to={`/tasks/${task.id}`}
                className="text-foreground font-medium hover:underline"
                onClick={(event) => {
                  event.preventDefault();
                  void handleCrossGuildNavigation(task, `/tasks/${task.id}`);
                }}
              >
                {task.title}
              </Link>
              {switchingTaskId === task.id ? (
                <Loader2 className="text-muted-foreground h-4 w-4 animate-spin" aria-hidden />
              ) : null}
            </div>
            {task.description ? (
              <Markdown content={task.description} className="line-clamp-2" />
            ) : null}
            <div className="text-muted-foreground space-y-1 text-xs">
              {recurrenceSummary ? <p>{recurrenceSummary}</p> : null}
            </div>
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
            Start Date
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => column.toggleSorting(isSorted === "asc")}
            >
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        return task.start_date ? (
          <div className="min-w-30">
            {formatDistance(new Date(task.start_date), new Date(), { addSuffix: true })}
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
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
            Due Date
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => column.toggleSorting(isSorted === "asc")}
            >
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const task = row.original;
        return task.due_date ? (
          <div className="min-w-30">
            {formatDistance(new Date(task.due_date), new Date(), { addSuffix: true })}
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
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
            Priority
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => column.toggleSorting(isSorted === "asc")}
            >
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
            <p className="text-muted-foreground text-xs">{task.task_status.name}</p>
            <Select
              value={task.task_status.category}
              onValueChange={(value) => void changeTaskStatus(task, value as TaskStatusCategory)}
              disabled={isUpdatingTaskStatus}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {statusOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      },
    },
  ];

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
                Status
              </Label>
              <Select
                value={statusFilter}
                onValueChange={(value) =>
                  setStatusFilter(value as "all" | "incomplete" | TaskStatusCategory)
                }
              >
                <SelectTrigger id="task-status-filter">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="incomplete">Incomplete</SelectItem>
                  <SelectItem value="all">All statuses</SelectItem>
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
