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
import { Calendar, Kanban, List, GanttChart } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { queryClient } from "@/lib/queryClient";
import {
  type Task,
  type TaskPriority,
  type TaskRecurrence,
  type TaskReorderPayload,
  type TaskStatus,
} from "@/types/api";
import { ProjectCalendarView } from "./ProjectCalendarView";
import { ProjectGanttView } from "./ProjectGanttView";
import { ProjectTaskComposer } from "./ProjectTaskComposer";
import { ProjectTasksFilters } from "./ProjectTasksFilters";
import { priorityVariant, type DueFilterOption, type UserOption } from "./projectTasksConfig";
import { ProjectTasksKanbanView } from "./ProjectTasksKanbanView";
import { ProjectTasksListView } from "./ProjectTasksListView";
import { Button } from "../ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../ui/tooltip";
type StoredFilters = {
  viewMode: "list" | "kanban" | "calendar" | "gantt";
  assigneeFilter: string;
  dueFilter: DueFilterOption;
  listStatusFilter: "all" | "incomplete" | TaskStatus;
};

type ProjectTasksSectionProps = {
  projectId: number;
  tasks: Task[];
  userOptions: UserOption[];
  canEditTaskDetails: boolean;
  canWriteProject: boolean;
  projectIsArchived: boolean;
  onTaskClick: (taskId: number) => void;
};

export const ProjectTasksSection = ({
  projectId,
  tasks: projectTasks,
  userOptions,
  canEditTaskDetails,
  canWriteProject,
  projectIsArchived,
  onTaskClick,
}: ProjectTasksSectionProps) => {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [startDate, setStartDate] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>("");
  const [recurrence, setRecurrence] = useState<TaskRecurrence | null>(null);
  const [viewMode, setViewMode] = useState<"list" | "kanban" | "calendar" | "gantt">("list");
  const [assigneeFilter, setAssigneeFilter] = useState<"all" | string>("all");
  const [dueFilter, setDueFilter] = useState<DueFilterOption>("all");
  const [listStatusFilter, setListStatusFilter] = useState<"all" | "incomplete" | TaskStatus>(
    "all"
  );
  const [orderedTasks, setOrderedTasks] = useState<Task[]>([]);
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [filtersLoaded, setFiltersLoaded] = useState(false);
  const lastKanbanOverRef = useRef<DragOverEvent["over"] | null>(null);

  const filterStorageKey = useMemo(
    () => (Number.isFinite(projectId) ? `project:${projectId}:view-filters` : null),
    [projectId]
  );

  useEffect(() => {
    setOrderedTasks(projectTasks);
  }, [projectTasks]);

  useEffect(() => {
    if (!filterStorageKey || filtersLoaded) {
      return;
    }
    try {
      const raw = localStorage.getItem(filterStorageKey);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<StoredFilters>;
        if (
          parsed.viewMode === "kanban" ||
          parsed.viewMode === "list" ||
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
  }, [filterStorageKey, filtersLoaded, viewMode, assigneeFilter, dueFilter, listStatusFilter]);

  const createTask = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = {
        project_id: projectId,
        title,
        description,
        priority,
        assignee_ids: assigneeIds,
        start_date: startDate ? new Date(startDate).toISOString() : null,
        due_date: dueDate ? new Date(dueDate).toISOString() : null,
        recurrence,
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
      setIsComposerOpen(false);
      setOrderedTasks((prev) => [...prev, newTask]);
      void queryClient.invalidateQueries({
        queryKey: ["tasks", projectId],
      });
      toast.success("Task created");
    },
  });

  const updateTaskStatus = useMutation({
    mutationFn: async ({ taskId, status }: { taskId: number; status: TaskStatus }) => {
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
        const next = prev.map((task) => (task.id === updatedTask.id ? updatedTask : task));
        return [...next].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
      });
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
      if (!Number.isFinite(projectId) || nextTasks.length === 0) {
        return;
      }
      const payload: TaskReorderPayload = {
        project_id: projectId,
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

    const overData = finalOver.data.current as { type?: string; status?: TaskStatus } | undefined;
    let targetStatus = currentTask.status;
    let overTaskId: number | null = null;

    if (overData?.type === "task") {
      targetStatus = overData.status ?? targetStatus;
      const parsed = Number(finalOver.id);
      overTaskId = Number.isFinite(parsed) ? parsed : null;
    } else if (overData?.type === "column") {
      targetStatus = overData.status ?? targetStatus;
    }

    if (targetStatus === currentTask.status && overTaskId === currentTask.id) {
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
      <Tabs
        value={viewMode}
        onValueChange={(value) => setViewMode(value as "list" | "kanban" | "calendar" | "gantt")}
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
            <TabsTrigger value="list" className="inline-flex items-center gap-2">
              <List className="h-4 w-4" />
              List
            </TabsTrigger>
            <TabsTrigger value="kanban" className="inline-flex items-center gap-2">
              <Kanban className="h-4 w-4" />
              Kanban
            </TabsTrigger>
            <TabsTrigger value="calendar" className="inline-flex items-center gap-2">
              <Calendar className="h-4 w-4" />
              Calendar
            </TabsTrigger>
            <TabsTrigger value="gantt" className="inline-flex items-center gap-2">
              <GanttChart className="h-4 w-4" />
              Gantt
            </TabsTrigger>
          </TabsList>
        </div>

        <ProjectTasksFilters
          viewMode={viewMode}
          userOptions={userOptions}
          assigneeFilter={assigneeFilter}
          dueFilter={dueFilter}
          listStatusFilter={listStatusFilter}
          onAssigneeFilterChange={setAssigneeFilter}
          onDueFilterChange={setDueFilter}
          onListStatusFilterChange={setListStatusFilter}
        />

        <TabsContent value="kanban">
          <ProjectTasksKanbanView
            groupedTasks={groupedTasks}
            canReorderTasks={canReorderTasks}
            canEditTaskDetails={canEditTaskDetails}
            onTaskClick={onTaskClick}
            priorityVariant={priorityVariant}
            sensors={kanbanSensors}
            activeTask={activeTask}
            onDragStart={handleTaskDragStart}
            onDragOver={handleKanbanDragOver}
            onDragEnd={handleKanbanDragEnd}
            onDragCancel={handleKanbanDragCancel}
          />
        </TabsContent>

        <TabsContent value="list">
          <ProjectTasksListView
            listTasks={listTasks}
            sensors={listSensors}
            canReorderTasks={canReorderTasks}
            canEditTaskDetails={canEditTaskDetails}
            taskActionsDisabled={taskActionsDisabled}
            priorityVariant={priorityVariant}
            onDragStart={handleTaskDragStart}
            onDragEnd={handleListDragEnd}
            onDragCancel={handleListDragCancel}
            onStatusChange={(taskId, status) =>
              updateTaskStatus.mutate({
                taskId,
                status,
              })
            }
            onTaskClick={onTaskClick}
          />
        </TabsContent>
        <TabsContent value="calendar">
          <ProjectCalendarView
            tasks={filteredTasks}
            canOpenTask={canEditTaskDetails}
            onTaskClick={onTaskClick}
          />
        </TabsContent>
        <TabsContent value="gantt">
          <ProjectGanttView
            tasks={filteredTasks}
            canOpenTask={canEditTaskDetails}
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
                  className="fixed bottom-6 right-6 z-40 h-12 rounded-full px-6 shadow-lg shadow-primary/40"
                  onClick={() => setIsComposerOpen(true)}
                >
                  Add Task
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top" sideOffset={12}>
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
                  startDate={startDate}
                  dueDate={dueDate}
                  recurrence={recurrence}
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
