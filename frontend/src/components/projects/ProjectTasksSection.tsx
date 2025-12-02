import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  DragEndEvent,
  DragOverEvent,
  DragStartEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { arrayMove } from "@dnd-kit/sortable";
import { Calendar, Kanban, Table, GanttChart, Filter, ChevronDown, Plus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { queryClient } from "@/lib/queryClient";
import type {
  TaskRecurrenceStrategy,
  ProjectTaskStatus,
  Task,
  TaskPriority,
  TaskRecurrence,
  TaskReorderPayload,
} from "@/types/api";
import { ProjectCalendarView } from "@/components/projects/ProjectCalendarView";
import { ProjectGanttView } from "@/components/projects/ProjectGanttView";
import { ProjectTaskComposer } from "@/components/projects/ProjectTaskComposer";
import {
  ProjectTasksFilters,
  type ListStatusFilter,
} from "@/components/projects/ProjectTasksFilters";
import {
  priorityVariant,
  type DueFilterOption,
  type UserOption,
} from "@/components/projects/projectTasksConfig";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Dialog } from "@/components/ui/dialog";

type ViewMode = "table" | "kanban" | "calendar" | "gantt";

type StoredFilters = {
  viewMode: ViewMode;
  assigneeFilter: string;
  dueFilter: DueFilterOption;
  listStatusFilter: ListStatusFilter;
};

const TASK_VIEW_OPTIONS: { value: ViewMode; label: string; icon: LucideIcon }[] = [
  { value: "table", label: "Table", icon: Table },
  { value: "kanban", label: "Kanban", icon: Kanban },
  { value: "calendar", label: "Calendar", icon: Calendar },
  { value: "gantt", label: "Gantt", icon: GanttChart },
];

const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

type ProjectTasksSectionProps = {
  projectId: number;
  tasks: Task[];
  taskStatuses: ProjectTaskStatus[];
  userOptions: UserOption[];
  canEditTaskDetails: boolean;
  canWriteProject: boolean;
  projectIsArchived: boolean;
  canViewTaskDetails: boolean;
  onTaskClick: (taskId: number) => void;
};

export const ProjectTasksSection = ({
  projectId,
  tasks: projectTasks,
  taskStatuses,
  userOptions,
  canEditTaskDetails,
  canWriteProject,
  projectIsArchived,
  canViewTaskDetails,
  onTaskClick,
}: ProjectTasksSectionProps) => {
  const sortedTaskStatuses = useMemo(() => {
    return [...taskStatuses].sort((a, b) => {
      if (a.position === b.position) {
        return a.id - b.id;
      }
      return a.position - b.position;
    });
  }, [taskStatuses]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [startDate, setStartDate] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>("");
  const [recurrence, setRecurrence] = useState<TaskRecurrence | null>(null);
  const [recurrenceStrategy, setRecurrenceStrategy] = useState<TaskRecurrenceStrategy>("fixed");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [assigneeFilter, setAssigneeFilter] = useState<"all" | string>("all");
  const [dueFilter, setDueFilter] = useState<DueFilterOption>("all");
  const [listStatusFilter, setListStatusFilter] = useState<ListStatusFilter>("all");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [orderedTasks, setOrderedTasks] = useState<Task[]>([]);
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [filtersLoaded, setFiltersLoaded] = useState(false);
  const lastKanbanOverRef = useRef<DragOverEvent["over"] | null>(null);
  const collapsedStorageKey = useMemo(
    () => (Number.isFinite(projectId) ? `project:${projectId}:kanban-collapsed` : null),
    [projectId]
  );
  const [collapsedStatuses, setCollapsedStatuses] = useState<Set<number>>(new Set());

  const statusLookup = useMemo(() => {
    const map = new Map<number, ProjectTaskStatus>();
    sortedTaskStatuses.forEach((status) => {
      map.set(status.id, status);
    });
    return map;
  }, [sortedTaskStatuses]);

  const defaultStatusId = useMemo(() => {
    if (sortedTaskStatuses.length === 0) {
      return null;
    }
    const explicit = sortedTaskStatuses.find((status) => status.is_default);
    return explicit?.id ?? sortedTaskStatuses[0]?.id ?? null;
  }, [sortedTaskStatuses]);

  const filterStorageKey = useMemo(
    () => (Number.isFinite(projectId) ? `project:${projectId}:view-filters` : null),
    [projectId]
  );

  const handleViewModeChange = (value: string) => {
    if (value === "table" || value === "kanban" || value === "calendar" || value === "gantt") {
      setViewMode(value);
    }
  };

  useEffect(() => {
    setOrderedTasks(projectTasks);
  }, [projectTasks]);

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

  useEffect(() => {
    if (!filterStorageKey || filtersLoaded) {
      return;
    }
    try {
      const raw = localStorage.getItem(filterStorageKey);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<StoredFilters>;
        if (
          parsed.viewMode === "table" ||
          parsed.viewMode === "kanban" ||
          parsed.viewMode === "calendar" ||
          parsed.viewMode === "gantt"
        ) {
          setViewMode(parsed.viewMode);
        }
        if (parsed.assigneeFilter) {
          setAssigneeFilter(parsed.assigneeFilter);
        }
        if (parsed.dueFilter) {
          setDueFilter(parsed.dueFilter);
        }
        const parsedListFilter = parsed.listStatusFilter;
        if (parsedListFilter === "all" || parsedListFilter === "incomplete") {
          setListStatusFilter(parsedListFilter);
        } else if (typeof parsedListFilter === "number" && Number.isFinite(parsedListFilter)) {
          setListStatusFilter(parsedListFilter);
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
  }, [filterStorageKey, filtersLoaded, viewMode, assigneeFilter, dueFilter, listStatusFilter]);

  useEffect(() => {
    if (!collapsedStorageKey || typeof window === "undefined") {
      return;
    }
    try {
      const raw = localStorage.getItem(collapsedStorageKey);
      if (raw) {
        const parsed: number[] = JSON.parse(raw);
        setCollapsedStatuses(new Set(parsed));
      }
    } catch {
      setCollapsedStatuses(new Set());
    }
  }, [collapsedStorageKey]);

  const persistCollapsedStatuses = useCallback(
    (next: Set<number>) => {
      if (!collapsedStorageKey || typeof window === "undefined") {
        return;
      }
      localStorage.setItem(collapsedStorageKey, JSON.stringify(Array.from(next)));
    },
    [collapsedStorageKey]
  );

  const toggleStatusCollapse = useCallback(
    (statusId: number) => {
      setCollapsedStatuses((prev) => {
        const next = new Set(prev);
        if (next.has(statusId)) {
          next.delete(statusId);
        } else {
          next.add(statusId);
        }
        persistCollapsedStatuses(next);
        return next;
      });
    },
    [persistCollapsedStatuses]
  );

  const createTask = useMutation({
    mutationFn: async () => {
      if (!defaultStatusId) {
        throw new Error("No default task status configured");
      }
      const payload: Record<string, unknown> = {
        project_id: projectId,
        title,
        description,
        priority,
        assignee_ids: assigneeIds,
        start_date: startDate ? new Date(startDate).toISOString() : null,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
        recurrence,
        recurrence_strategy: recurrenceStrategy,
        task_status_id: defaultStatusId,
      };
      const response = await apiClient.post<Task>("/tasks/", payload);
      return response.data;
    },
    onSuccess: (newTask) => {
      setTitle("");
      setDescription("");
      setPriority("medium");
      setAssigneeIds([]);
      setStartDate("");
      setDueDate("");
      setRecurrence(null);
      setRecurrenceStrategy("fixed");
      setIsComposerOpen(false);
      setOrderedTasks((prev) => [...prev, newTask]);
      void queryClient.invalidateQueries({
        queryKey: ["tasks", projectId],
      });
      toast.success("Task created");
    },
    onError: () => {
      toast.error("Unable to create task. Please try again once statuses load.");
    },
  });

  const updateTaskStatus = useMutation({
    mutationFn: async ({ taskId, taskStatusId }: { taskId: number; taskStatusId: number }) => {
      const response = await apiClient.patch<Task>(`/tasks/${taskId}`, {
        task_status_id: taskStatusId,
      });
      return response.data;
    },
    onSuccess: (updatedTask) => {
      let nextState: Task[] | null = null;
      setOrderedTasks((prev) => {
        if (!prev.length) {
          return prev;
        }
        nextState = prev.map((task) => (task.id === updatedTask.id ? updatedTask : task));
        return nextState;
      });
      if (nextState) {
        persistOrder(nextState);
      }
      void queryClient.invalidateQueries({
        queryKey: ["tasks", projectId],
      });
      toast.success("Task updated");
    },
  });

  const { mutate: persistTaskOrderMutate, isPending: isPersistingOrder } = useMutation({
    mutationFn: async (payload: TaskReorderPayload) => {
      const response = await apiClient.post<Task[]>("/tasks/reorder", payload);
      return response.data;
    },
    onSuccess: (data) => {
      setOrderedTasks(data);
      void queryClient.invalidateQueries({
        queryKey: ["tasks", projectId],
      });
    },
  });

  const taskActionsDisabled = updateTaskStatus.isPending || isPersistingOrder;
  const canReorderTasks = canEditTaskDetails && !isPersistingOrder;

  const fetchedTasks = useMemo(() => projectTasks ?? [], [projectTasks]);
  const tasks = orderedTasks.length > 0 ? orderedTasks : fetchedTasks;
  const activeTask = orderedTasks.find((task) => task.id === activeTaskId) ?? null;

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
        const taskDueDate = new Date(task.due_date);
        if (Number.isNaN(taskDueDate.getTime())) {
          return false;
        }
        if (dueFilter === "overdue") {
          if (taskDueDate >= now) {
            return false;
          }
        } else if (dueFilter === "today") {
          if (
            taskDueDate.getFullYear() !== now.getFullYear() ||
            taskDueDate.getMonth() !== now.getMonth() ||
            taskDueDate.getDate() !== now.getDate()
          ) {
            return false;
          }
        } else {
          const days = dueFilter === "7_days" ? 7 : 30;
          const windowEnd = new Date(now.getTime());
          windowEnd.setDate(windowEnd.getDate() + days);
          if (taskDueDate < now || taskDueDate > windowEnd) {
            return false;
          }
        }
      }
      return true;
    });
  }, [tasks, assigneeFilter, dueFilter]);

  const groupedTasks = useMemo(() => {
    const groups: Record<number, Task[]> = {};
    sortedTaskStatuses.forEach((status) => {
      groups[status.id] = [];
    });
    filteredTasks.forEach((task) => {
      if (!groups[task.task_status_id]) {
        groups[task.task_status_id] = [];
      }
      groups[task.task_status_id].push(task);
    });
    return groups;
  }, [filteredTasks, sortedTaskStatuses]);

  const tableTasks = useMemo(() => {
    if (listStatusFilter === "all") {
      return filteredTasks;
    }
    if (listStatusFilter === "incomplete") {
      return filteredTasks.filter((task) => task.task_status.category !== "done");
    }
    return filteredTasks.filter((task) => task.task_status_id === listStatusFilter);
  }, [filteredTasks, listStatusFilter]);

  const persistOrder = useCallback(
    (nextTasks: Task[]) => {
      if (!Number.isFinite(projectId) || nextTasks.length === 0) {
        return;
      }
      const payload: TaskReorderPayload = {
        project_id: projectId,
        items: nextTasks.map((task, index) => ({
          id: task.id,
          task_status_id: task.task_status_id,
          sort_order: index + 1,
        })),
      };
      if (isPersistingOrder) {
        return;
      }
      persistTaskOrderMutate(payload);
    },
    [projectId, persistTaskOrderMutate, isPersistingOrder]
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
    (taskId: number, targetStatusId: number, overTaskId: number | null) => {
      const targetStatus = statusLookup.get(targetStatusId);
      if (!targetStatus) {
        return;
      }
      let nextState: Task[] | null = null;
      setOrderedTasks((prev) => {
        const currentTask = prev.find((task) => task.id === taskId);
        if (!currentTask) {
          return prev;
        }
        const updatedTask: Task = {
          ...currentTask,
          task_status_id: targetStatus.id,
          task_status: targetStatus,
        };
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
          if (task.task_status_id === targetStatusId) {
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
    [persistOrder, statusLookup]
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
  );
  const listSensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 8,
      },
    })
  );

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

    const currentTask = tasks.find((task) => task.id === activeId);
    if (!currentTask) {
      return;
    }

    const overData = finalOver.data.current as { type?: string; statusId?: number } | undefined;
    let targetStatusId = currentTask.task_status_id;
    let overTaskId: number | null = null;

    if (overData?.type === "task") {
      targetStatusId = overData.statusId ?? targetStatusId;
      const parsed = Number(finalOver.id);
      overTaskId = Number.isFinite(parsed) ? parsed : null;
    } else if (overData?.type === "column") {
      targetStatusId = overData.statusId ?? targetStatusId;
    }

    if (targetStatusId === currentTask.task_status_id && overTaskId === currentTask.id) {
      return;
    }

    moveTaskInOrder(activeId, targetStatusId, overTaskId);
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
    if (!Number.isFinite(activeId) || !Number.isFinite(overId) || activeId === overId) {
      return;
    }
    reorderListTasks(activeId, overId);
    setActiveTaskId(null);
  };

  const handleKanbanDragCancel = () => {
    setActiveTaskId(null);
    lastKanbanOverRef.current = null;
  };

  const handleListDragCancel = () => {
    setActiveTaskId(null);
  };

  return (
    <div className="space-y-4">
      <Tabs value={viewMode} onValueChange={handleViewModeChange} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">Project tasks</h2>
          </div>
          <div className="w-full sm:flex sm:w-auto sm:items-center sm:justify-end sm:gap-3">
            <div className="w-full sm:hidden">
              <Select value={viewMode} onValueChange={handleViewModeChange}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select view" />
                </SelectTrigger>
                <SelectContent>
                  {TASK_VIEW_OPTIONS.map(({ value, label, icon: Icon }) => (
                    <SelectItem key={value} value={value}>
                      <Icon className="mr-2 inline h-4 w-4" />
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="hidden sm:block">
              <TabsList>
                {TASK_VIEW_OPTIONS.map(({ value, label, icon: Icon }) => (
                  <TabsTrigger key={value} value={value} className="gap-2">
                    <Icon className="h-4 w-4" />
                    {label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
          </div>
        </div>

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
          <CollapsibleContent forceMount className="mt-2 data-[state=closed]:hidden sm:mt-0">
            <ProjectTasksFilters
              viewMode={viewMode}
              taskStatuses={sortedTaskStatuses}
              userOptions={userOptions}
              assigneeFilter={assigneeFilter}
              dueFilter={dueFilter}
              listStatusFilter={listStatusFilter}
              onAssigneeFilterChange={setAssigneeFilter}
              onDueFilterChange={setDueFilter}
              onListStatusFilterChange={setListStatusFilter}
            />
          </CollapsibleContent>
        </Collapsible>

        <TabsContent value="kanban">
          <ProjectTasksKanbanView
            taskStatuses={sortedTaskStatuses}
            groupedTasks={groupedTasks}
            collapsedStatusIds={collapsedStatuses}
            canReorderTasks={canReorderTasks}
            canOpenTask={canViewTaskDetails}
            onTaskClick={onTaskClick}
            priorityVariant={priorityVariant}
            sensors={kanbanSensors}
            activeTask={activeTask}
            onDragStart={handleTaskDragStart}
            onDragOver={handleKanbanDragOver}
            onDragEnd={handleKanbanDragEnd}
            onDragCancel={handleKanbanDragCancel}
            onToggleCollapse={toggleStatusCollapse}
          />
        </TabsContent>

        <TabsContent value="table">
          <ProjectTasksTableView
            tasks={tableTasks}
            taskStatuses={sortedTaskStatuses}
            sensors={listSensors}
            canReorderTasks={canReorderTasks}
            canEditTaskDetails={canEditTaskDetails}
            canOpenTask={canViewTaskDetails}
            taskActionsDisabled={taskActionsDisabled}
            priorityVariant={priorityVariant}
            onDragStart={handleTaskDragStart}
            onDragEnd={handleListDragEnd}
            onDragCancel={handleListDragCancel}
            onStatusChange={(taskId, taskStatusId) =>
              updateTaskStatus.mutate({
                taskId,
                taskStatusId,
              })
            }
            onTaskClick={onTaskClick}
          />
        </TabsContent>
        <TabsContent value="calendar">
          <ProjectCalendarView
            tasks={filteredTasks}
            canOpenTask={canViewTaskDetails}
            onTaskClick={onTaskClick}
          />
        </TabsContent>
        <TabsContent value="gantt">
          <ProjectGanttView
            tasks={filteredTasks}
            canOpenTask={canViewTaskDetails}
            onTaskClick={onTaskClick}
          />
        </TabsContent>
      </Tabs>

      {canEditTaskDetails ? (
        <>
          <TooltipProvider>
            <Tooltip delayDuration={400}>
              <TooltipTrigger asChild>
                <Button
                  className="shadow-primary/40 fixed right-6 bottom-6 z-40 h-12 rounded-full px-6 shadow-lg"
                  onClick={() => setIsComposerOpen(true)}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Add Task
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top" sideOffset={12}>
                Hit &lsquo;enter&rsquo; to create a new task
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Dialog open={isComposerOpen} onOpenChange={setIsComposerOpen}>
            <ProjectTaskComposer
              title={title}
              description={description}
              priority={priority}
              assigneeIds={assigneeIds}
              startDate={startDate}
              dueDate={dueDate}
              recurrence={recurrence}
              recurrenceStrategy={recurrenceStrategy}
              canWrite={canWriteProject}
              isArchived={projectIsArchived}
              isSubmitting={createTask.isPending}
              hasError={Boolean(createTask.isError)}
              users={userOptions}
              onTitleChange={setTitle}
              onDescriptionChange={setDescription}
              onPriorityChange={setPriority}
              onAssigneesChange={setAssigneeIds}
              onStartDateChange={setStartDate}
              onDueDateChange={setDueDate}
              onRecurrenceChange={setRecurrence}
              onRecurrenceStrategyChange={setRecurrenceStrategy}
              onSubmit={() => createTask.mutate()}
              onCancel={() => setIsComposerOpen(false)}
              autoFocusTitle
            />
          </Dialog>
        </>
      ) : null}
    </div>
  );
};
