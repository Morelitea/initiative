import {
  CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  closestCenter,
  closestCorners,
  DndContext,
  DragOverlay,
  DragEndEvent,
  DragStartEvent,
  DragOverEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

import { apiClient } from "../api/client";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Markdown } from "../components/Markdown";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
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
import {
  InitiativeColorDot,
  resolveInitiativeColor,
  INITIATIVE_COLOR_FALLBACK,
} from "../lib/initiativeColors";
import {
  Project,
  Task,
  TaskPriority,
  TaskReorderPayload,
  TaskStatus,
  User,
} from "../types/api";
import { toast } from "sonner";
import { ProjectTaskComposer } from "../components/projects/ProjectTaskComposer";
import { KanbanColumn } from "../components/projects/KanbanColumn";
import { SortableTaskRow } from "../components/projects/SortableTaskRow";
import { FavoriteProjectButton } from "../components/projects/FavoriteProjectButton";
import { Kanban, List } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../components/ui/tooltip";

const taskStatusOrder: TaskStatus[] = [
  "backlog",
  "in_progress",
  "blocked",
  "done",
];

type DueFilterOption = "all" | "today" | "7_days" | "30_days" | "overdue";

type StoredFilters = {
  viewMode: "kanban" | "list";
  assigneeFilter: string;
  dueFilter: DueFilterOption;
  listStatusFilter: "all" | "incomplete" | TaskStatus;
};

const priorityVariant: Record<
  TaskPriority,
  "default" | "secondary" | "destructive"
> = {
  low: "secondary",
  medium: "default",
  high: "default",
  urgent: "destructive",
};

export const ProjectDetailPage = () => {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const parsedProjectId = Number(projectId);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [dueDate, setDueDate] = useState<string>("");
  const [viewMode, setViewMode] = useState<"kanban" | "list">("kanban");
  const [assigneeFilter, setAssigneeFilter] = useState<"all" | string>("all");
  const [dueFilter, setDueFilter] = useState<DueFilterOption>("all");
  const [listStatusFilter, setListStatusFilter] = useState<
    "all" | "incomplete" | TaskStatus
  >("all");
  const [orderedTasks, setOrderedTasks] = useState<Task[]>([]);
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const lastKanbanOverRef = useRef<DragOverEvent["over"] | null>(null);
  const { user } = useAuth();
  const [filtersLoaded, setFiltersLoaded] = useState(false);

  const projectQuery = useQuery<Project>({
    queryKey: ["projects", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(
        `/projects/${parsedProjectId}`
      );
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const viewedProjectId = projectQuery.data?.id;
  const activeTask =
    orderedTasks.find((task) => task.id === activeTaskId) ?? null;

  useEffect(() => {
    if (!viewedProjectId) {
      return;
    }
    const recordView = async () => {
      try {
        await apiClient.post(`/projects/${viewedProjectId}/view`);
        await queryClient.invalidateQueries({
          queryKey: ["projects", "recent"],
        });
      } catch (error) {
        console.error("Failed to record project view", error);
      }
    };
    void recordView();
  }, [viewedProjectId]);

  const tasksQuery = useQuery<Task[]>({
    queryKey: ["tasks", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Task[]>("/tasks/", {
        params: { project_id: parsedProjectId },
      });
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const usersQuery = useQuery<User[]>({
    queryKey: ["users"],
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
  });
  const userOptions = useMemo(() => {
    const project = projectQuery.data;
    const allUsers = usersQuery.data ?? [];
    if (!project) {
      return allUsers.map((user) => ({
        id: user.id,
        label: user.full_name ?? user.email,
      }));
    }

    const allowed = new Set<number>();
    allowed.add(project.owner_id);
    project.members.forEach((member) => allowed.add(member.user_id));
    project.initiative?.members?.forEach((member) => allowed.add(member.id));

    return allUsers
      .filter((user) => allowed.has(user.id))
      .map((user) => ({
        id: user.id,
        label: user.full_name ?? user.email,
      }));
  }, [usersQuery.data, projectQuery.data]);
  useEffect(() => {
    if (tasksQuery.data) {
      setOrderedTasks(tasksQuery.data);
    }
  }, [tasksQuery.data]);

  const filterStorageKey = useMemo(
    () =>
      Number.isFinite(parsedProjectId)
        ? `project:${parsedProjectId}:view-filters`
        : null,
    [parsedProjectId]
  );

  useEffect(() => {
    if (!filterStorageKey || filtersLoaded) {
      return;
    }
    try {
      const raw = localStorage.getItem(filterStorageKey);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<StoredFilters>;
        if (parsed.viewMode === "kanban" || parsed.viewMode === "list") {
          setViewMode(parsed.viewMode);
        }
        if (parsed.assigneeFilter) {
          setAssigneeFilter(parsed.assigneeFilter);
        }
        if (parsed.dueFilter) {
          setDueFilter(parsed.dueFilter);
        }
        if (parsed.listStatusFilter) {
          setListStatusFilter(parsed.listStatusFilter);
        }
      }
    } catch {
      // ignore parse errors
    } finally {
      setFiltersLoaded(true);
    }
  }, [filterStorageKey, filtersLoaded]);

  useEffect(() => {
    if (!filterStorageKey || !filtersLoaded) {
      return;
    }
    const payload = {
      viewMode,
      assigneeFilter,
      dueFilter,
      listStatusFilter,
    };
    localStorage.setItem(filterStorageKey, JSON.stringify(payload));
  }, [
    filterStorageKey,
    filtersLoaded,
    viewMode,
    assigneeFilter,
    dueFilter,
    listStatusFilter,
  ]);

  const createTask = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = {
        project_id: parsedProjectId,
        title,
        description,
        priority,
        assignee_ids: assigneeIds,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
      };
      const response = await apiClient.post<Task>("/tasks/", payload);
      return response.data;
    },
    onSuccess: (newTask) => {
      setTitle("");
      setDescription("");
      setPriority("medium");
      setAssigneeIds([]);
      setDueDate("");
      setIsComposerOpen(false);
      setOrderedTasks((prev) => [...prev, newTask]);
      void queryClient.invalidateQueries({
        queryKey: ["tasks", parsedProjectId],
      });
      toast.success("Task created");
    },
  });

  const updateTaskStatus = useMutation({
    mutationFn: async ({
      taskId,
      status,
    }: {
      taskId: number;
      status: TaskStatus;
    }) => {
      const response = await apiClient.patch<Task>(`/tasks/${taskId}`, {
        status,
      });
      return response.data;
    },
    onSuccess: (updatedTask) => {
      setOrderedTasks((prev) => {
        if (!prev.length) {
          return prev;
        }
        const next = prev.map((task) =>
          task.id === updatedTask.id ? updatedTask : task
        );
        return [...next].sort(
          (a, b) => a.sort_order - b.sort_order || a.id - b.id
        );
      });
      void queryClient.invalidateQueries({
        queryKey: ["tasks", parsedProjectId],
      });
      toast.success("Task updated");
    },
  });

  const { mutate: persistTaskOrderMutate, isPending: isPersistingOrder } =
    useMutation({
      mutationFn: async (payload: TaskReorderPayload) => {
        const response = await apiClient.post<Task[]>(
          "/tasks/reorder",
          payload
        );
        return response.data;
      },
      onSuccess: (data) => {
        setOrderedTasks(data);
        void queryClient.invalidateQueries({
          queryKey: ["tasks", parsedProjectId],
        });
      },
    });

  const project = projectQuery.data;
  const initiativeColor = resolveInitiativeColor(project?.initiative?.color);
  const detailCardStyle = useMemo(
    () => buildProjectDetailBackground(initiativeColor),
    [initiativeColor]
  );
  const membershipRole = project?.members.find(
    (member) => member.user_id === user?.id
  )?.role;
  const userProjectRole =
    (user?.role as "admin" | "project_manager" | "member" | undefined) ??
    undefined;
  const projectWriteRoles = project?.write_roles ?? [];
  const canManageSettings =
    user?.role === "admin" ||
    membershipRole === "admin" ||
    membershipRole === "project_manager";
  const canWriteProject =
    user?.role === "admin" ||
    (membershipRole ? projectWriteRoles.includes(membershipRole) : false) ||
    (userProjectRole ? projectWriteRoles.includes(userProjectRole) : false);
  const projectIsArchived = project?.is_archived ?? false;
  const canEditTaskDetails = Boolean(
    project && canWriteProject && !projectIsArchived
  );
  const canReorderTasks = canEditTaskDetails && !isPersistingOrder;
  const taskActionsDisabled = updateTaskStatus.isPending || isPersistingOrder;

  const fetchedTasks = useMemo(() => tasksQuery.data ?? [], [tasksQuery.data]);
  const tasks = orderedTasks.length > 0 ? orderedTasks : fetchedTasks;

  const filteredTasks = useMemo(() => {
    if (assigneeFilter === "all" && dueFilter === "all") {
      return tasks;
    }
    const now = new Date();
    return tasks.filter((task) => {
      if (assigneeFilter !== "all") {
        const targetId = Number(assigneeFilter);
        if (!task.assignees.some((assignee) => assignee.id === targetId)) {
          return false;
        }
      }
      if (dueFilter !== "all") {
        if (!task.due_date) {
          return false;
        }
        const dueDate = new Date(task.due_date);
        if (Number.isNaN(dueDate.getTime())) {
          return false;
        }
        if (dueFilter === "overdue") {
          if (dueDate >= now) {
            return false;
          }
        } else if (dueFilter === "today") {
          if (
            dueDate.getFullYear() !== now.getFullYear() ||
            dueDate.getMonth() !== now.getMonth() ||
            dueDate.getDate() !== now.getDate()
          ) {
            return false;
          }
        } else {
          const days = dueFilter === "7_days" ? 7 : 30;
          const windowEnd = new Date(now.getTime());
          windowEnd.setDate(windowEnd.getDate() + days);
          if (dueDate < now || dueDate > windowEnd) {
            return false;
          }
        }
      }
      return true;
    });
  }, [tasks, assigneeFilter, dueFilter]);

  const groupedTasks = useMemo(() => {
    const groups: Record<TaskStatus, Task[]> = {
      backlog: [],
      in_progress: [],
      blocked: [],
      done: [],
    };
    filteredTasks.forEach((task) => {
      groups[task.status].push(task);
    });
    return groups;
  }, [filteredTasks]);

  const listTasks = useMemo(() => {
    if (listStatusFilter === "all") {
      return filteredTasks;
    }
    if (listStatusFilter === "incomplete") {
      return filteredTasks.filter((task) => task.status !== "done");
    }
    return filteredTasks.filter((task) => task.status === listStatusFilter);
  }, [filteredTasks, listStatusFilter]);

  const persistOrder = useCallback(
    (nextTasks: Task[]) => {
      if (!Number.isFinite(parsedProjectId) || nextTasks.length === 0) {
        return;
      }
      const payload: TaskReorderPayload = {
        project_id: parsedProjectId,
        items: nextTasks.map((task, index) => ({
          id: task.id,
          status: task.status,
          sort_order: index + 1,
        })),
      };
      if (isPersistingOrder) {
        return;
      }
      persistTaskOrderMutate(payload);
    },
    [parsedProjectId, persistTaskOrderMutate, isPersistingOrder]
  );

  useEffect(() => {
    if (!canEditTaskDetails) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || isComposerOpen) {
        return;
      }
      const target = event.target as HTMLElement | null;
      if (target) {
        const tagName = target.tagName;
        if (
          target.isContentEditable ||
          tagName === "INPUT" ||
          tagName === "TEXTAREA" ||
          tagName === "SELECT" ||
          tagName === "BUTTON"
        ) {
          return;
        }
      }
      event.preventDefault();
      setIsComposerOpen(true);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canEditTaskDetails, isComposerOpen]);

  const moveTaskInOrder = useCallback(
    (taskId: number, targetStatus: TaskStatus, overTaskId: number | null) => {
      let nextState: Task[] | null = null;
      setOrderedTasks((prev) => {
        const currentTask = prev.find((task) => task.id === taskId);
        if (!currentTask) {
          return prev;
        }
        const updatedTask: Task = { ...currentTask, status: targetStatus };
        const withoutActive = prev.filter((task) => task.id !== taskId);
        const next = [...withoutActive];

        if (overTaskId !== null) {
          const insertIndex = next.findIndex((task) => task.id === overTaskId);
          if (insertIndex >= 0) {
            next.splice(insertIndex, 0, updatedTask);
            nextState = next;
            return next;
          }
        }

        let lastIndex = -1;
        next.forEach((task, index) => {
          if (task.status === targetStatus) {
            lastIndex = index;
          }
        });
        next.splice(lastIndex + 1, 0, updatedTask);
        nextState = next;
        return next;
      });
      if (nextState) {
        persistOrder(nextState);
      }
    },
    [persistOrder]
  );

  const reorderListTasks = useCallback(
    (activeId: number, overId: number) => {
      let nextState: Task[] | null = null;
      setOrderedTasks((prev) => {
        const oldIndex = prev.findIndex((task) => task.id === activeId);
        const newIndex = prev.findIndex((task) => task.id === overId);
        if (oldIndex === -1 || newIndex === -1) {
          return prev;
        }
        nextState = arrayMove(prev, oldIndex, newIndex);
        return nextState;
      });
      if (nextState) {
        persistOrder(nextState);
      }
    },
    [persistOrder]
  );

  const kanbanSensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 8,
      },
    })
  ); // Touch holds prevent accidental scroll drags.
  const listSensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 8,
      },
    })
  );

  if (!Number.isFinite(parsedProjectId)) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Invalid project id.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  if (projectQuery.isLoading || tasksQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading project…</p>;
  }

  if (projectQuery.isError || tasksQuery.isError || !project) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  const handleTaskClick = (taskId: number) => {
    if (!canEditTaskDetails) {
      return;
    }
    navigate(`/tasks/${taskId}/edit`);
  };

  const handleTaskDragStart = (event: DragStartEvent) => {
    const taskType = event.active.data.current?.type;
    if (taskType !== "task" && taskType !== "list-task") {
      return;
    }
    const id = Number(event.active.id);
    if (Number.isFinite(id)) {
      setActiveTaskId(id);
    }
    lastKanbanOverRef.current = null;
  };

  const handleKanbanDragEnd = (event: DragEndEvent) => {
    if (!canReorderTasks) {
      setActiveTaskId(null);
      lastKanbanOverRef.current = null;
      return;
    }
    const { active, over } = event;
    const finalOver = over ?? lastKanbanOverRef.current;
    if (!finalOver) {
      setActiveTaskId(null);
      lastKanbanOverRef.current = null;
      return;
    }
    const activeId = Number(active.id);
    if (!Number.isFinite(activeId)) {
      return;
    }

    const activeTask = tasks.find((task) => task.id === activeId);
    if (!activeTask) {
      return;
    }

    const overData = finalOver.data.current as
      | { type?: string; status?: TaskStatus }
      | undefined;
    let targetStatus = activeTask.status;
    let overTaskId: number | null = null;

    if (overData?.type === "task") {
      targetStatus = overData.status ?? targetStatus;
      const parsed = Number(finalOver.id);
      overTaskId = Number.isFinite(parsed) ? parsed : null;
    } else if (overData?.type === "column") {
      targetStatus = overData.status ?? targetStatus;
    }

    if (targetStatus === activeTask.status && overTaskId === activeTask.id) {
      return;
    }

    moveTaskInOrder(activeId, targetStatus, overTaskId);
    setActiveTaskId(null);
    lastKanbanOverRef.current = null;
  };

  const handleKanbanDragOver = (event: DragOverEvent) => {
    if (event.over) {
      lastKanbanOverRef.current = event.over;
    }
  };

  const handleListDragEnd = (event: DragEndEvent) => {
    if (!canReorderTasks) {
      setActiveTaskId(null);
      return;
    }
    const { active, over } = event;
    if (!over) {
      setActiveTaskId(null);
      return;
    }
    const activeId = Number(active.id);
    const overId = Number(over.id);
    if (
      !Number.isFinite(activeId) ||
      !Number.isFinite(overId) ||
      activeId === overId
    ) {
      return;
    }
    reorderListTasks(activeId, overId);
    setActiveTaskId(null);
  };

  return (
    <div className="space-y-6">
      <Button asChild variant="link" className="px-0">
        <Link to="/">← Back to projects</Link>
      </Button>
      <div
        className="space-y-4 rounded-2xl border bg-card/90 p-6 shadow-sm"
        style={detailCardStyle}
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-3">
            {project.icon ? (
              <span className="text-4xl leading-none">{project.icon}</span>
            ) : null}
            <h1 className="text-3xl font-semibold tracking-tight">
              {project.name}
            </h1>
          </div>
          <FavoriteProjectButton
            projectId={project.id}
            isFavorited={project.is_favorited ?? false}
          />
          <Badge variant={projectIsArchived ? "destructive" : "secondary"}>
            {projectIsArchived ? "Archived" : "Active"}
          </Badge>
          {project.is_template ? (
            <Badge variant="outline">Template</Badge>
          ) : null}
        </div>
        {project.initiative ? (
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <InitiativeColorDot color={project.initiative.color} />
            <span>{project.initiative.name}</span>
          </div>
        ) : null}
        {project.is_template ? (
          <p className="rounded-md border border-muted/70 bg-muted/30 px-4 py-2 text-sm text-muted-foreground">
            This project is a template. Use it to create new projects from the
            Templates tab.
          </p>
        ) : null}
        {project.description ? (
          <Markdown content={project.description} />
        ) : null}
        {canManageSettings ? (
          <Button asChild variant="outline" className="w-fit">
            <Link to={`/projects/${project.id}/settings`}>
              Open project settings
            </Link>
          </Button>
        ) : null}
        {projectIsArchived ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            This project is archived. Unarchive it from settings to add or
            update tasks.
          </p>
        ) : null}
      </div>

      <div className="space-y-4">
        <Tabs
          value={viewMode}
          onValueChange={(value) => setViewMode(value as "kanban" | "list")}
          className="space-y-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">Project tasks</h2>
              <p className="text-sm text-muted-foreground">
                Switch between Kanban and List views to track progress.
              </p>
            </div>
            <TabsList>
              <TabsTrigger
                value="kanban"
                className="inline-flex items-center gap-2"
              >
                <Kanban className="h-4 w-4" />
                Kanban
              </TabsTrigger>
              <TabsTrigger
                value="list"
                className="inline-flex items-center gap-2"
              >
                <List className="h-4 w-4" />
                List
              </TabsTrigger>
            </TabsList>
          </div>
          <div className="flex flex-wrap items-end gap-4 rounded-md border border-muted bg-background/40 p-3">
            <div className="w-48">
              <Label
                htmlFor="assignee-filter"
                className="text-xs font-medium text-muted-foreground"
              >
                Filter by assignee
              </Label>
              <Select value={assigneeFilter} onValueChange={setAssigneeFilter}>
                <SelectTrigger id="assignee-filter">
                  <SelectValue placeholder="All assignees" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All assignees</SelectItem>
                  {userOptions.map((option) => (
                    <SelectItem key={option.id} value={String(option.id)}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-48">
              <Label
                htmlFor="due-filter"
                className="text-xs font-medium text-muted-foreground"
              >
                Due filter
              </Label>
              <Select
                value={dueFilter}
                onValueChange={(value) =>
                  setDueFilter(value as DueFilterOption)
                }
              >
                <SelectTrigger id="due-filter">
                  <SelectValue placeholder="All due dates" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All due dates</SelectItem>
                  <SelectItem value="overdue">Overdue</SelectItem>
                  <SelectItem value="today">Due today</SelectItem>
                  <SelectItem value="7_days">Due next 7 days</SelectItem>
                  <SelectItem value="30_days">Due next 30 days</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {viewMode === "list" ? (
              <div className="w-44">
                <Label
                  htmlFor="status-filter"
                  className="text-xs font-medium text-muted-foreground"
                >
                  Filter by status
                </Label>
                <Select
                  value={listStatusFilter}
                  onValueChange={(value) =>
                    setListStatusFilter(
                      value as "all" | "incomplete" | TaskStatus
                    )
                  }
                >
                  <SelectTrigger id="status-filter">
                    <SelectValue placeholder="All statuses" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All statuses</SelectItem>
                    <SelectItem value="incomplete">Incomplete</SelectItem>
                    {taskStatusOrder.map((status) => (
                      <SelectItem key={status} value={status}>
                        {status.replace("_", " ")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
          </div>

          <TabsContent value="kanban">
            <DndContext
              sensors={kanbanSensors}
              collisionDetection={closestCorners}
              onDragStart={handleTaskDragStart}
              onDragOver={handleKanbanDragOver}
              onDragEnd={handleKanbanDragEnd}
              onDragCancel={() => {
                setActiveTaskId(null);
                lastKanbanOverRef.current = null;
              }}
            >
              <div className="overflow-x-auto pb-4">
                <div className="flex gap-4">
                  {taskStatusOrder.map((status) => (
                    <div key={status} className="w-80 shrink-0">
                      <KanbanColumn
                        status={status}
                        tasks={groupedTasks[status]}
                        canWrite={canReorderTasks}
                        canOpenTask={canEditTaskDetails}
                        priorityVariant={priorityVariant}
                        onTaskClick={handleTaskClick}
                      />
                    </div>
                  ))}
                </div>
              </div>
              <DragOverlay>
                {activeTask ? (
                  <TaskDragOverlay
                    task={activeTask}
                    priorityVariant={priorityVariant}
                  />
                ) : null}
              </DragOverlay>
            </DndContext>
          </TabsContent>

          <TabsContent value="list">
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>Task list</CardTitle>
                <CardDescription>
                  View every task at once and update their status inline.
                </CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                {listTasks.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No tasks yet.</p>
                ) : (
                  <DndContext
                    sensors={listSensors}
                    collisionDetection={closestCenter}
                    onDragStart={handleTaskDragStart}
                    onDragEnd={handleListDragEnd}
                    onDragCancel={() => setActiveTaskId(null)}
                  >
                    <SortableContext
                      items={listTasks.map((task) => task.id.toString())}
                      strategy={verticalListSortingStrategy}
                    >
                      <table className="w-full min-w-[720px] text-sm">
                        <thead>
                          <tr className="text-left text-muted-foreground">
                            <th className="pb-2 pl-3 font-medium">Done</th>
                            <th className="pb-2 font-medium">Task</th>
                            <th className="pb-2 font-medium">Priority</th>
                            <th className="pb-2 font-medium">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y">
                          {listTasks.map((task) => (
                            <SortableTaskRow
                              key={task.id}
                              task={task}
                              dragDisabled={!canReorderTasks}
                              statusDisabled={
                                !canEditTaskDetails || taskActionsDisabled
                              }
                              canOpenTask={canEditTaskDetails}
                              statusOrder={taskStatusOrder}
                              priorityVariant={priorityVariant}
                              onStatusChange={(taskId, value) =>
                                updateTaskStatus.mutate({
                                  taskId,
                                  status: value,
                                })
                              }
                              onTaskClick={handleTaskClick}
                            />
                          ))}
                        </tbody>
                      </table>
                    </SortableContext>
                  </DndContext>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
      {canEditTaskDetails ? (
        <>
          <TooltipProvider>
            <Tooltip delayDuration={400}>
              <TooltipTrigger asChild>
                <Button
                  className="fixed bottom-6 right-6 z-40 h-12 rounded-full px-6 shadow-lg shadow-primary/40"
                  onClick={() => setIsComposerOpen(true)}
                >
                  Add Task
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top" sideOffset={32}>
                Hit &lsquo;enter&rsquo; to create a new task
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          {isComposerOpen ? (
            <div className="fixed inset-0 z-50 flex items-end justify-center bg-background/70 p-4 backdrop-blur-sm sm:items-center">
              <div
                className="absolute inset-0 -z-10"
                role="presentation"
                onClick={() => setIsComposerOpen(false)}
              />
              <div className="w-full max-w-lg rounded-2xl border bg-card shadow-2xl">
                <ProjectTaskComposer
                  title={title}
                  description={description}
                  priority={priority}
                  assigneeIds={assigneeIds}
                  dueDate={dueDate}
                  canWrite={canWriteProject}
                  isArchived={projectIsArchived}
                  isSubmitting={createTask.isPending}
                  hasError={Boolean(createTask.isError)}
                  users={userOptions}
                  onTitleChange={setTitle}
                  onDescriptionChange={setDescription}
                  onPriorityChange={setPriority}
                  onAssigneesChange={setAssigneeIds}
                  onDueDateChange={setDueDate}
                  onSubmit={() => createTask.mutate()}
                  onCancel={() => setIsComposerOpen(false)}
                  autoFocusTitle
                />
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
};

const TaskDragOverlay = ({
  task,
  priorityVariant,
}: {
  task: Task;
  priorityVariant: Record<
    TaskPriority,
    "default" | "secondary" | "destructive"
  >;
}) => (
  <div className="w-64 space-y-3 rounded-lg border bg-card p-3 shadow-lg">
    <div className="space-y-1">
      <p className="font-medium">{task.title}</p>
      {task.description ? (
        <Markdown content={task.description} className="text-xs [&>*]:my-1" />
      ) : null}
    </div>
    <div className="text-xs text-muted-foreground space-y-1">
      {task.assignees.length > 0 ? (
        <p>
          Assigned:{" "}
          {task.assignees
            .map((assignee) => assignee.full_name ?? assignee.email)
            .join(", ")}
        </p>
      ) : null}
      {task.due_date ? (
        <p>Due: {new Date(task.due_date).toLocaleString()}</p>
      ) : null}
    </div>
    <Badge variant={priorityVariant[task.priority]}>
      Priority: {task.priority.replace("_", " ")}
    </Badge>
  </div>
);

const hexToRgba = (hex: string, alpha: number): string => {
  const sanitized = hex.replace("#", "");
  const expanded =
    sanitized.length === 3
      ? sanitized
          .split("")
          .map((char) => char + char)
          .join("")
      : sanitized.padEnd(6, "0");
  const r = parseInt(expanded.slice(0, 2), 16);
  const g = parseInt(expanded.slice(2, 4), 16);
  const b = parseInt(expanded.slice(4, 6), 16);

  if ([r, g, b].some((value) => Number.isNaN(value))) {
    return hexToRgba(INITIATIVE_COLOR_FALLBACK, alpha);
  }

  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const buildProjectDetailBackground = (hexColor: string): CSSProperties => {
  return {
    borderColor: hexToRgba(hexColor, 0.35),
    backgroundImage: `linear-gradient(135deg, ${hexToRgba(
      hexColor,
      0.18
    )} 0%, ${hexToRgba(hexColor, 0.06)} 45%, transparent 100%)`,
  };
};
