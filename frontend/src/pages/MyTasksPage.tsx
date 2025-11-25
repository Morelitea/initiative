import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, Filter } from "lucide-react";

import { apiClient } from "../api/client";
import { summarizeRecurrence } from "../lib/recurrence";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { priorityVariant } from "../components/projects/projectTasksConfig";
import { TasksTableCard } from "../components/tasks/TasksTableCard";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { DataTable } from "../components/ui/data-table";
import type { Project, Task, TaskPriority, TaskStatus } from "../types/api";

const statusOptions: TaskStatus[] = ["backlog", "in_progress", "blocked", "done"];
const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];
const INITIATIVE_FILTER_ALL = "all";
const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

export const MyTasksPage = () => {
  const { user } = useAuth();

  const tasksQuery = useQuery<Task[]>({
    queryKey: ["tasks", "all"],
    queryFn: async () => {
      const response = await apiClient.get<Task[]>("/tasks/");
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

  const updateTaskStatus = useMutation({
    mutationFn: async ({ taskId, status }: { taskId: number; status: TaskStatus }) => {
      const response = await apiClient.patch<Task>(`/tasks/${taskId}`, { status });
      return response.data;
    },
    onSuccess: (updatedTask) => {
      queryClient.setQueryData<Task[] | undefined>(["tasks", "all"], (prev) => {
        if (!prev) {
          return prev;
        }
        return prev.map((task) => (task.id === updatedTask.id ? updatedTask : task));
      });
    },
  });

  const [statusFilter, setStatusFilter] = useState<"all" | "incomplete" | TaskStatus>("incomplete");
  const [priorityFilter, setPriorityFilter] = useState<"all" | TaskPriority>("all");
  const [sortMode, setSortMode] = useState<"due" | "priority" | "alphabetical">("due");
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
    return tasks.filter(
      (task) =>
        !excludedProjectIds.has(task.project_id) &&
        task.assignees.some((assignee) => assignee.id === user.id)
    );
  }, [tasks, user, excludedProjectIds]);

  const filteredTasks = useMemo(() => {
    const selectedInitiativeId =
      initiativeFilter === INITIATIVE_FILTER_ALL ? null : Number(initiativeFilter);
    return myTasks.filter((task) => {
      if (statusFilter === "incomplete") {
        if (task.status === "done") {
          return false;
        }
      } else if (statusFilter !== "all" && task.status !== statusFilter) {
        return false;
      }

      if (priorityFilter !== "all" && task.priority !== priorityFilter) {
        return false;
      }

      if (selectedInitiativeId) {
        const project = projectsById[task.project_id];
        if (!project || project.initiative_id !== selectedInitiativeId) {
          return false;
        }
      }
      return true;
    });
  }, [myTasks, statusFilter, priorityFilter, initiativeFilter, projectsById]);

  const sortedTasks = useMemo(() => {
    const next = [...filteredTasks];
    if (sortMode === "due") {
      next.sort((a, b) => {
        if (!a.due_date) return 1;
        if (!b.due_date) return -1;
        return new Date(a.due_date).getTime() - new Date(b.due_date).getTime();
      });
    } else if (sortMode === "priority") {
      const order = new Map(priorityOrder.map((value, index) => [value, index]));
      next.sort((a, b) => {
        const aRank = order.get(a.priority) ?? 0;
        const bRank = order.get(b.priority) ?? 0;
        return bRank - aRank;
      });
    } else {
      next.sort((a, b) => a.title.localeCompare(b.title));
    }
    return next;
  }, [filteredTasks, sortMode]);

  const columns: ColumnDef<Task>[] = [
    {
      id: "completed",
      header: () => <span className="font-medium">Done</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <Checkbox
            checked={task.status === "done"}
            onCheckedChange={(value) =>
              updateTaskStatus.mutate({
                taskId: task.id,
                status: value ? "done" : "in_progress",
              })
            }
            disabled={updateTaskStatus.isPending}
            aria-label={task.status === "done" ? "Mark task as in progress" : "Mark task as done"}
          />
        );
      },
      enableSorting: false,
      size: 64,
    },
    {
      accessorKey: "title",
      header: () => <span className="font-medium">Task</span>,
      cell: ({ row }) => {
        const task = row.original;
        const recurrenceSummary = task.recurrence
          ? summarizeRecurrence(task.recurrence, {
              referenceDate: task.start_date || task.due_date,
            })
          : null;
        return (
          <div className="flex flex-col text-left">
            <Link
              to={`/tasks/${task.id}/edit`}
              className="font-medium text-foreground hover:underline"
            >
              {task.title}
            </Link>
            {task.description ? (
              <p className="text-sm text-muted-foreground line-clamp-2">{task.description}</p>
            ) : null}
            <div className="space-y-1 text-xs text-muted-foreground">
              {task.start_date || task.due_date ? (
                <p>
                  {task.start_date ? `Starts: ${new Date(task.start_date).toLocaleString()}` : null}
                  {task.start_date && task.due_date ? <span> &mdash; </span> : null}
                  {task.due_date ? `Due: ${new Date(task.due_date).toLocaleString()}` : null}
                </p>
              ) : null}
              {recurrenceSummary ? <p>{recurrenceSummary}</p> : null}
            </div>
          </div>
        );
      },
    },
    {
      id: "initiative",
      header: () => <span className="font-medium">Initiative</span>,
      cell: ({ row }) => {
        const task = row.original;
        const project = projectsById[task.project_id];
        const initiative = project?.initiative;
        if (!initiative) {
          return <span className="text-sm text-muted-foreground">—</span>;
        }
        return (
          <div className="flex items-center gap-2">
            {initiative.color ? (
              <span
                className="h-2.5 w-2.5 rounded-full border border-border/40"
                style={{ backgroundColor: initiative.color }}
              />
            ) : null}
            <span className="text-sm font-medium text-foreground">{initiative.name}</span>
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
        if (!project) {
          return <span className="text-sm text-muted-foreground">Project #{task.project_id}</span>;
        }
        return (
          <Link
            to={`/projects/${project.id}`}
            className="text-sm font-medium text-primary hover:underline"
          >
            {project.name}
          </Link>
        );
      },
    },
    {
      id: "priority",
      header: () => <span className="font-medium">Priority</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <Badge variant={priorityVariant[task.priority]}>{task.priority.replace("_", " ")}</Badge>
        );
      },
    },
    {
      id: "status",
      header: () => <span className="font-medium">Status</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <Select
            value={task.status}
            onValueChange={(value) =>
              updateTaskStatus.mutate({
                taskId: task.id,
                status: value as TaskStatus,
              })
            }
            disabled={updateTaskStatus.isPending}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {statusOptions.map((status) => (
                <SelectItem key={status} value={status}>
                  {status.replace("_", " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
    return <p className="text-sm text-muted-foreground">Loading your tasks…</p>;
  }

  if (
    tasksQuery.isError ||
    projectsQuery.isError ||
    templatesQuery.isError ||
    archivedProjectsQuery.isError
  ) {
    return <p className="text-sm text-destructive">Unable to load your tasks.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">My Tasks</h1>
        <p className="text-muted-foreground">Everything assigned to you across all projects.</p>
      </div>

      <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
        <div className="flex items-center justify-between sm:hidden">
          <div className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground">
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
          <div className="mt-2 flex flex-wrap items-end gap-4 rounded-md border border-muted bg-background/40 p-3 sm:mt-0">
            <div className="w-full sm:w-60 lg:flex-1">
              <Label
                htmlFor="task-status-filter"
                className="text-xs font-medium text-muted-foreground"
              >
                Status
              </Label>
              <Select
                value={statusFilter}
                onValueChange={(value) => setStatusFilter(value as typeof statusFilter)}
              >
                <SelectTrigger id="task-status-filter">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="incomplete">Incomplete</SelectItem>
                  <SelectItem value="all">All statuses</SelectItem>
                  {statusOptions.map((status) => (
                    <SelectItem key={status} value={status}>
                      {status.replace("_", " ")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-full sm:w-60 lg:flex-1">
              <Label
                htmlFor="task-priority-filter"
                className="text-xs font-medium text-muted-foreground"
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
                className="text-xs font-medium text-muted-foreground"
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
            <div className="w-full sm:w-60 lg:flex-1">
              <Label htmlFor="task-sort" className="text-xs font-medium text-muted-foreground">
                Sort
              </Label>
              <Select
                value={sortMode}
                onValueChange={(value) => setSortMode(value as typeof sortMode)}
              >
                <SelectTrigger id="task-sort">
                  <SelectValue placeholder="Sort by" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="due">Due date</SelectItem>
                  <SelectItem value="priority">Priority</SelectItem>
                  <SelectItem value="alphabetical">Alphabetical</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <TasksTableCard
        title="Assigned tasks"
        description="Update status directly from this view."
        isEmpty={sortedTasks.length === 0}
        emptyMessage="No tasks match the current filters."
      >
        <div className="w-full overflow-x-auto">
          <div className="min-w-[900px]">
            <DataTable columns={columns} data={sortedTasks} />
          </div>
        </div>
      </TasksTableCard>
    </div>
  );
};
