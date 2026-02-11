import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { ChevronDown, Filter, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { useGuildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import { useGuilds } from "@/hooks/useGuilds";
import { queryClient } from "@/lib/queryClient";
import { TaskDescriptionHoverCard } from "@/components/projects/TaskDescriptionHoverCard";
import type {
  ProjectTaskStatus,
  Task,
  TaskListResponse,
  TaskPriority,
  TaskStatusCategory,
} from "@/types/api";
import { SortIcon } from "@/components/SortIcon";
import { dateSortingFn, prioritySortingFn } from "@/lib/sorting";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { TaskPrioritySelector } from "@/components/tasks/TaskPrioritySelector";
import { TaskStatusSelector } from "@/components/tasks/TaskStatusSelector";

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

const DEFAULT_STATUS_FILTERS: TaskStatusCategory[] = ["backlog", "todo", "in_progress"];

const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

type TagTasksTableProps = {
  tagId: number;
};

const TAG_TASKS_PAGE_SIZE = 20;

const SORT_FIELD_MAP: Record<string, string> = {
  title: "title",
  "due date": "due_date",
  "start date": "start_date",
  priority: "priority",
};

export const TagTasksTable = ({ tagId }: TagTasksTableProps) => {
  const { activeGuildId } = useGuilds();
  const gp = useGuildPath();
  const router = useRouter();
  const localQueryClient = useQueryClient();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;
  const projectStatusCache = useRef<
    Map<number, { statuses: ProjectTaskStatus[]; complete: boolean }>
  >(new Map());

  const [statusFilters, setStatusFilters] = useState<TaskStatusCategory[]>(DEFAULT_STATUS_FILTERS);
  const [priorityFilters, setPriorityFilters] = useState<TaskPriority[]>([]);
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  const [page, setPageState] = useState(() => searchParams.page ?? 1);
  const [pageSize, setPageSize] = useState(TAG_TASKS_PAGE_SIZE);
  const [sortBy, setSortBy] = useState<string | undefined>("due_date");
  const [sortDir, setSortDir] = useState<string | undefined>("asc");

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
        const col = sorting[0];
        const field = SORT_FIELD_MAP[col.id];
        if (field) {
          setSortBy(field);
          setSortDir(col.desc ? "desc" : "asc");
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
  }, [statusFilters, priorityFilters, setPage]);

  const tasksQuery = useQuery<TaskListResponse>({
    queryKey: [
      "tasks",
      "tag",
      tagId,
      statusFilters,
      priorityFilters,
      page,
      pageSize,
      sortBy,
      sortDir,
    ],
    queryFn: async () => {
      const params: Record<string, string | string[] | number | number[]> = {
        tag_ids: [tagId],
      };
      if (statusFilters.length > 0) {
        params.status_category = statusFilters;
      }
      if (priorityFilters.length > 0) {
        params.priorities = priorityFilters;
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
      const params: Record<string, string | string[] | number | number[]> = {
        tag_ids: [tagId],
      };
      if (statusFilters.length > 0) params.status_category = statusFilters;
      if (priorityFilters.length > 0) params.priorities = priorityFilters;
      params.page = targetPage;
      params.page_size = pageSize;
      if (sortBy) params.sort_by = sortBy;
      if (sortDir) params.sort_dir = sortDir;

      void localQueryClient.prefetchQuery({
        queryKey: [
          "tasks",
          "tag",
          tagId,
          statusFilters,
          priorityFilters,
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
    [tagId, statusFilters, priorityFilters, pageSize, sortBy, sortDir, localQueryClient]
  );

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
        { task_status_id: taskStatusId },
        guildId ? { headers: { "X-Guild-ID": String(guildId) } } : undefined
      );
      return response.data;
    },
    onSuccess: (updatedTask) => {
      void queryClient.invalidateQueries({ queryKey: ["tasks", "tag", tagId] });
      void queryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
      const cached = projectStatusCache.current.get(updatedTask.project_id);
      if (cached && !cached.statuses.some((status) => status.id === updatedTask.task_status.id)) {
        cached.statuses.push(updatedTask.task_status);
      }
    },
  });

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
      { headers: { "X-Guild-ID": String(guildId) } }
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
              if (isUpdatingTaskStatus) return;
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
        return (
          <div className="flex min-w-60 flex-col text-left">
            <div className="flex">
              <Link
                to={gp(`/tasks/${task.id}`)}
                className="text-foreground flex w-full items-center gap-2 font-medium hover:underline"
              >
                {task.title}
              </Link>
              <TaskDescriptionHoverCard task={task} />
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
      id: "project",
      header: () => <span className="font-medium">Project</span>,
      cell: ({ row }) => {
        const task = row.original;
        return (
          <div className="min-w-30">
            <Link
              to={gp(`/projects/${task.project_id}`)}
              className="text-primary text-sm font-medium hover:underline"
            >
              {task.project_name ?? `Project #${task.project_id}`}
            </Link>
          </div>
        );
      },
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

  useEffect(() => {
    if (typeof window === "undefined") return;
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

  const isInitialLoad = tasksQuery.isLoading && !tasksQuery.data;

  const isRefetching = tasksQuery.isFetching && !isInitialLoad;

  const hasError = tasksQuery.isError;

  const totalCount = tasksQuery.data?.total_count ?? 0;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

  return (
    <div className="space-y-4">
      <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
        <div className="flex items-center justify-between sm:hidden">
          <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
            <Filter className="h-4 w-4" />
            Filters
          </div>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-8 px-3">
              {filtersOpen ? "Hide" : "Show"} filters
              <ChevronDown
                className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
              />
            </Button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
            <div className="w-full sm:w-60 lg:flex-1">
              <Label className="text-muted-foreground mb-2 block text-xs font-medium">
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
              <Label className="text-muted-foreground mb-2 block text-xs font-medium">
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
          <p className="text-destructive py-8 text-center text-sm">Unable to load tasks.</p>
        ) : (
          <DataTable
            columns={columns}
            data={tasks}
            initialSorting={[{ id: "due date", desc: false }]}
            enableFilterInput
            filterInputColumnKey="title"
            filterInputPlaceholder="Filter tasks..."
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
  );
};
