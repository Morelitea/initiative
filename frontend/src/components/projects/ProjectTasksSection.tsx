import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
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
import {
  Calendar,
  Kanban,
  Table,
  GanttChart,
  Filter,
  ChevronDown,
  Plus,
  Archive,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import {
  createTaskApiV1TasksPost,
  updateTaskApiV1TasksTaskIdPatch,
  deleteTaskApiV1TasksTaskIdDelete,
  reorderTasksApiV1TasksReorderPost,
  archiveDoneTasksApiV1TasksArchiveDonePost,
} from "@/api/generated/tasks/tasks";
import type {
  ListTasksApiV1TasksGetParams,
  TaskRecurrenceOutput,
  TaskReorderRequest,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useTasks } from "@/hooks/useTasks";
import { invalidateAllTasks } from "@/api/query-keys";
import { getItem, setItem } from "@/lib/storage";

import { useTags } from "@/hooks/useTags";
import type { TaskPriority } from "@/api/generated/initiativeAPI.schemas";
import type { TaskRecurrenceStrategy, Task } from "@/types/api";
import { ProjectCalendarView } from "@/components/projects/ProjectCalendarView";
import { ProjectGanttView } from "@/components/projects/ProjectGanttView";
import { ProjectTaskComposer } from "@/components/projects/ProjectTaskComposer";
import { ProjectTasksFilters } from "@/components/projects/ProjectTasksFilters";
import {
  priorityVariant,
  type DueFilterOption,
  type UserOption,
} from "@/components/projects/projectTasksConfig";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { TaskBulkEditPanel } from "@/components/tasks/TaskBulkEditPanel";
import { TaskBulkEditDialog, type TaskBulkUpdate } from "@/components/tasks/TaskBulkEditDialog";
import { BulkEditTaskTagsDialog } from "@/components/tasks/BulkEditTaskTagsDialog";
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

type ViewMode = "table" | "kanban" | "calendar" | "gantt";

type StoredFilters = {
  viewMode: ViewMode;
  assigneeFilters: string[];
  dueFilter: DueFilterOption;
  statusFilters: number[];
  tagFilters: number[];
  showArchived: boolean;
};

type TaskViewOption = { value: ViewMode; labelKey: string; icon: LucideIcon };

const TASK_VIEW_OPTIONS: TaskViewOption[] = [
  { value: "table", labelKey: "tasks.viewTable", icon: Table },
  { value: "kanban", labelKey: "tasks.viewKanban", icon: Kanban },
  { value: "calendar", labelKey: "tasks.viewCalendar", icon: Calendar },
  { value: "gantt", labelKey: "tasks.viewGantt", icon: GanttChart },
];

const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

type ProjectTasksSectionProps = {
  projectId: number;
  taskStatuses: TaskStatusRead[];
  userOptions: UserOption[];
  canEditTaskDetails: boolean;
  canWriteProject: boolean;
  projectIsArchived: boolean;
  canViewTaskDetails: boolean;
  onTaskClick: (taskId: number) => void;
};

export const ProjectTasksSection = ({
  projectId,
  taskStatuses,
  userOptions,
  canEditTaskDetails,
  canWriteProject,
  projectIsArchived,
  canViewTaskDetails,
  onTaskClick,
}: ProjectTasksSectionProps) => {
  const { t } = useTranslation("projects");
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
  const [recurrence, setRecurrence] = useState<TaskRecurrenceOutput | null>(null);
  const [recurrenceStrategy, setRecurrenceStrategy] = useState<TaskRecurrenceStrategy>("fixed");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [assigneeFilters, setAssigneeFilters] = useState<string[]>([]);
  const [dueFilter, setDueFilter] = useState<DueFilterOption>("all");
  const [statusFilters, setStatusFilters] = useState<number[]>([]);
  const [tagFilters, setTagFilters] = useState<number[]>([]);
  const [showArchived, setShowArchived] = useState(false);

  // Fetch guild tags for filtering
  const { data: tags = [] } = useTags();
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [localOverride, setLocalOverride] = useState<Task[] | null>(null);
  const [isComposerOpen, setIsComposerOpen] = useState(false);
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [filtersLoadedForProject, setFiltersLoadedForProject] = useState<number | null>(null);
  const [selectedTasks, setSelectedTasks] = useState<Task[]>([]);
  const [isBulkEditDialogOpen, setIsBulkEditDialogOpen] = useState(false);
  const [isBulkEditTagsDialogOpen, setIsBulkEditTagsDialogOpen] = useState(false);
  const [isArchiveDialogOpen, setIsArchiveDialogOpen] = useState(false);
  const [archiveDialogStatusId, setArchiveDialogStatusId] = useState<number | undefined>(undefined);
  const lastKanbanOverRef = useRef<DragOverEvent["over"] | null>(null);

  // Fetch tasks with server-side filtering (page_size=0 fetches all for drag-and-drop)
  const taskListParams: ListTasksApiV1TasksGetParams = {
    project_id: projectId,
    page_size: 0,
    ...(assigneeFilters.length > 0 && { assignee_ids: assigneeFilters }),
    ...(statusFilters.length > 0 && { task_status_ids: statusFilters }),
    ...(tagFilters.length > 0 && { tag_ids: tagFilters }),
    ...(showArchived && { include_archived: true }),
  };

  const tasksQuery = useTasks(taskListParams, {
    enabled: Number.isFinite(projectId) && filtersLoadedForProject === projectId,
  });

  const projectTasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const collapsedStorageKey = useMemo(
    () => (Number.isFinite(projectId) ? `project:${projectId}:kanban-collapsed` : null),
    [projectId]
  );
  const [collapsedStatuses, setCollapsedStatuses] = useState<Set<number>>(new Set());

  const statusLookup = useMemo(() => {
    const map = new Map<number, TaskStatusRead>();
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
    setLocalOverride(null);
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
    if (!filterStorageKey || filtersLoadedForProject === projectId) {
      return;
    }
    // Reset to defaults first, then load saved values
    setViewMode("table");
    setAssigneeFilters([]);
    setDueFilter("all");
    setStatusFilters([]);
    setTagFilters([]);
    setShowArchived(false);

    try {
      const raw = getItem(filterStorageKey);
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
        if (Array.isArray(parsed.assigneeFilters)) {
          setAssigneeFilters(parsed.assigneeFilters);
        }
        if (parsed.dueFilter) {
          setDueFilter(parsed.dueFilter);
        }
        if (Array.isArray(parsed.statusFilters)) {
          setStatusFilters(parsed.statusFilters);
        }
        if (Array.isArray(parsed.tagFilters)) {
          setTagFilters(parsed.tagFilters);
        }
        if (typeof parsed.showArchived === "boolean") {
          setShowArchived(parsed.showArchived);
        }
      }
    } catch {
      // ignore parse errors
    } finally {
      setFiltersLoadedForProject(projectId);
    }
  }, [filterStorageKey, filtersLoadedForProject, projectId]);

  useEffect(() => {
    if (!filterStorageKey || filtersLoadedForProject !== projectId) {
      return;
    }
    const payload: StoredFilters = {
      viewMode,
      assigneeFilters,
      dueFilter,
      statusFilters,
      tagFilters,
      showArchived,
    };
    setItem(filterStorageKey, JSON.stringify(payload));
  }, [
    filterStorageKey,
    filtersLoadedForProject,
    projectId,
    viewMode,
    assigneeFilters,
    dueFilter,
    statusFilters,
    tagFilters,
    showArchived,
  ]);

  useEffect(() => {
    if (!collapsedStorageKey) {
      return;
    }
    try {
      const raw = getItem(collapsedStorageKey);
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
      if (!collapsedStorageKey) {
        return;
      }
      setItem(collapsedStorageKey, JSON.stringify(Array.from(next)));
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
        recurrence: recurrence,
        task_status_id: defaultStatusId,
      };
      if (recurrence) {
        payload.recurrence = recurrence;
        payload.recurrence_strategy = recurrenceStrategy;
      } else {
        payload.recurrence = null;
        payload.recurrence_strategy = "fixed";
      }
      return await (createTaskApiV1TasksPost(payload as never) as unknown as Promise<Task>);
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
      setLocalOverride((prev) => [...(prev ?? projectTasks), newTask]);
      void invalidateAllTasks();
      toast.success(t("tasks.taskCreated"));
    },
    onError: () => {
      toast.error(t("tasks.createError"));
    },
  });

  const updateTaskStatus = useMutation({
    mutationFn: async ({ taskId, taskStatusId }: { taskId: number; taskStatusId: number }) => {
      return await (updateTaskApiV1TasksTaskIdPatch(taskId, {
        task_status_id: taskStatusId,
      } as never) as unknown as Promise<Task>);
    },
    onSuccess: (updatedTask) => {
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        if (!base.length) return prev;
        const matchesFilters =
          statusFilters.length === 0 || statusFilters.includes(updatedTask.task_status_id);
        if (matchesFilters) {
          return base.map((task) => (task.id === updatedTask.id ? updatedTask : task));
        }
        return base.filter((task) => task.id !== updatedTask.id);
      });
      void invalidateAllTasks();
      toast.success(t("tasks.taskUpdated"));
    },
  });

  const bulkUpdateTasks = useMutation({
    mutationFn: async ({
      taskIds,
      changes,
    }: {
      taskIds: number[];
      changes: Partial<TaskBulkUpdate>;
    }) => {
      const results = await Promise.all(
        taskIds.map(
          (taskId) =>
            updateTaskApiV1TasksTaskIdPatch(taskId, changes as never) as unknown as Promise<Task>
        )
      );
      return results;
    },
    onSuccess: (updatedTasks) => {
      const count = updatedTasks.length;
      toast.success(t("tasks.bulkUpdated", { count }));
      // setSelectedTasks([]);
      setIsBulkEditDialogOpen(false);
      setLocalOverride(null);
      void invalidateAllTasks();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("tasks.bulkUpdateError");
      toast.error(message);
    },
  });

  const bulkDeleteTasks = useMutation({
    mutationFn: async (taskIds: number[]) => {
      await Promise.all(taskIds.map((taskId) => deleteTaskApiV1TasksTaskIdDelete(taskId)));
    },
    onSuccess: (_data, taskIds) => {
      const count = taskIds.length;
      toast.success(t("tasks.bulkDeleted", { count }));
      setSelectedTasks([]);
      setLocalOverride(null);
      void invalidateAllTasks();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("tasks.bulkDeleteError");
      toast.error(message);
    },
  });

  const bulkArchiveTasks = useMutation({
    mutationFn: async (taskIds: number[]) => {
      const results = await Promise.all(
        taskIds.map(
          (taskId) =>
            updateTaskApiV1TasksTaskIdPatch(taskId, {
              is_archived: true,
            } as never) as unknown as Promise<Task>
        )
      );
      return results;
    },
    onSuccess: (updatedTasks) => {
      const count = updatedTasks.length;
      toast.success(t("tasks.archivedSuccess", { count }));
      setSelectedTasks([]);
      setLocalOverride(null);
      void invalidateAllTasks();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("tasks.archiveError");
      toast.error(message);
    },
  });

  const archiveDoneTasks = useMutation({
    mutationFn: async (taskStatusId?: number) => {
      return await (archiveDoneTasksApiV1TasksArchiveDonePost({
        project_id: projectId,
        ...(taskStatusId !== undefined && { task_status_id: taskStatusId }),
      }) as unknown as Promise<{ archived_count: number }>);
    },
    onSuccess: (data) => {
      const count = data.archived_count;
      if (count === 0) {
        toast.info(t("tasks.noDoneTasksToArchive"));
      } else {
        toast.success(t("tasks.archivedSuccess", { count }));
      }
      void invalidateAllTasks();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("tasks.archiveError");
      toast.error(message);
    },
  });

  const { mutate: persistTaskOrderMutate, isPending: isPersistingOrder } = useMutation({
    mutationFn: async (payload: TaskReorderRequest) => {
      return await (reorderTasksApiV1TasksReorderPost(payload as never) as unknown as Promise<
        Task[]
      >);
    },
    onSuccess: () => {
      // Don't set localOverride from response - it returns unfiltered tasks.
      // The optimistic update already shows the new order, and query
      // invalidation will confirm with filters (clearing localOverride).
      void invalidateAllTasks();
    },
  });

  const taskActionsDisabled = updateTaskStatus.isPending || isPersistingOrder;
  const canReorderTasks = canEditTaskDetails && !isPersistingOrder;

  const tasks = useMemo(() => localOverride ?? projectTasks, [localOverride, projectTasks]);
  const activeTask = useMemo(
    () => projectTasks.find((task) => task.id === activeTaskId) ?? null,
    [projectTasks, activeTaskId]
  );

  // Client-side filtering for due date (not yet supported server-side)
  const filteredTasks = useMemo(() => {
    if (dueFilter === "all") {
      return tasks;
    }
    const now = new Date();
    return tasks.filter((task) => {
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
      return true;
    });
  }, [tasks, dueFilter]);

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

  // Status filtering is now done server-side, so statusFilteredTasks is just filteredTasks
  const statusFilteredTasks = filteredTasks;

  // Count of archivable done tasks (non-archived tasks in done category)
  const archivableDoneTasksCount = useMemo(() => {
    return filteredTasks.filter((task) => task.task_status.category === "done" && !task.is_archived)
      .length;
  }, [filteredTasks]);

  // Count of archivable tasks per done status
  const archivableCountByStatus = useMemo(() => {
    const counts: Record<number, number> = {};
    sortedTaskStatuses.forEach((status) => {
      if (status.category === "done") {
        counts[status.id] = (groupedTasks[status.id] ?? []).filter((t) => !t.is_archived).length;
      }
    });
    return counts;
  }, [sortedTaskStatuses, groupedTasks]);

  const persistOrder = useCallback(
    (nextTasks: Task[]) => {
      if (!Number.isFinite(projectId) || nextTasks.length === 0) {
        return;
      }
      const payload: TaskReorderRequest = {
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
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        const currentTask = base.find((task) => task.id === taskId);
        if (!currentTask) {
          return prev;
        }
        const updatedTask: Task = {
          ...currentTask,
          task_status_id: targetStatus.id,
          task_status: targetStatus,
        };
        const withoutActive = base.filter((task) => task.id !== taskId);
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
    [persistOrder, statusLookup, projectTasks]
  );

  const reorderListTasks = useCallback(
    (activeId: number, overId: number) => {
      let nextState: Task[] | null = null;
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        const oldIndex = base.findIndex((task) => task.id === activeId);
        const newIndex = base.findIndex((task) => task.id === overId);
        if (oldIndex === -1 || newIndex === -1) {
          return prev;
        }
        nextState = arrayMove(base, oldIndex, newIndex);
        return nextState;
      });
      if (nextState) {
        persistOrder(nextState);
      }
    },
    [persistOrder, projectTasks]
  );

  const mouseSensorConfig = useMemo(() => ({ activationConstraint: { distance: 4 } }), []);
  const touchSensorConfig = useMemo(
    () => ({ activationConstraint: { delay: 200, tolerance: 8 } }),
    []
  );

  const kanbanSensors = useSensors(
    useSensor(MouseSensor, mouseSensorConfig),
    useSensor(TouchSensor, touchSensorConfig)
  );
  const listSensors = useSensors(
    useSensor(MouseSensor, mouseSensorConfig),
    useSensor(TouchSensor, touchSensorConfig)
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
          <div className="flex gap-2">
            <h2 className="text-xl font-semibold">{t("tasks.projectTasks")}</h2>
            {canEditTaskDetails && (
              <TooltipProvider>
                <Tooltip delayDuration={400}>
                  <TooltipTrigger asChild>
                    <Button size="sm" variant="outline" onClick={() => setIsComposerOpen(true)}>
                      <Plus className="h-4 w-4" />
                      {t("tasks.addTask")}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top" sideOffset={12}>
                    {t("tasks.enterTooltip")}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
          <div className="w-full sm:flex sm:w-auto sm:items-center sm:justify-end sm:gap-3">
            <div className="w-full sm:hidden">
              <Select value={viewMode} onValueChange={handleViewModeChange}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("tasks.selectView")} />
                </SelectTrigger>
                <SelectContent>
                  {TASK_VIEW_OPTIONS.map(({ value, labelKey, icon: Icon }) => (
                    <SelectItem key={value} value={value}>
                      <Icon className="mr-2 inline h-4 w-4" />
                      {t(labelKey as never)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="hidden sm:block">
              <TabsList>
                {TASK_VIEW_OPTIONS.map(({ value, labelKey, icon: Icon }) => (
                  <TabsTrigger key={value} value={value} className="gap-2">
                    <Icon className="h-4 w-4" />
                    {t(labelKey as never)}
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
              {t("tasks.filtersHeading")}
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 px-3">
                {filtersOpen ? t("tasks.hideFilters") : t("tasks.showFilters")}
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
              tags={tags}
              assigneeFilters={assigneeFilters}
              dueFilter={dueFilter}
              statusFilters={statusFilters}
              tagFilters={tagFilters}
              showArchived={showArchived}
              onAssigneeFiltersChange={setAssigneeFilters}
              onDueFilterChange={setDueFilter}
              onStatusFiltersChange={setStatusFilters}
              onTagFiltersChange={setTagFilters}
              onShowArchivedChange={setShowArchived}
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
            onArchiveDoneTasks={
              canEditTaskDetails
                ? (statusId) => {
                    setArchiveDialogStatusId(statusId);
                    setIsArchiveDialogOpen(true);
                  }
                : undefined
            }
            isArchivingDoneTasks={archiveDoneTasks.isPending}
          />
        </TabsContent>

        <TabsContent value="table" className="space-y-4">
          {selectedTasks.length > 0 && canEditTaskDetails && (
            <TaskBulkEditPanel
              selectedTasks={selectedTasks}
              onEdit={() => setIsBulkEditDialogOpen(true)}
              onEditTags={() => setIsBulkEditTagsDialogOpen(true)}
              onArchive={() => bulkArchiveTasks.mutate(selectedTasks.map((t) => t.id))}
              onDelete={() => {
                if (confirm(t("tasks.bulkDeleteConfirm", { count: selectedTasks.length }))) {
                  bulkDeleteTasks.mutate(selectedTasks.map((t) => t.id));
                }
              }}
              isArchiving={bulkArchiveTasks.isPending}
            />
          )}
          <ProjectTasksTableView
            tasks={statusFilteredTasks}
            taskStatuses={sortedTaskStatuses}
            sensors={listSensors}
            canReorderTasks={canReorderTasks}
            canEditTaskDetails={canEditTaskDetails}
            canOpenTask={canViewTaskDetails}
            taskActionsDisabled={taskActionsDisabled}
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
            onTaskSelectionChange={setSelectedTasks}
            onExitSelection={() => setSelectedTasks([])}
          />
          {canEditTaskDetails && (
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setArchiveDialogStatusId(undefined);
                  setIsArchiveDialogOpen(true);
                }}
                disabled={archiveDoneTasks.isPending}
              >
                <Archive className="h-4 w-4" />
                {archiveDoneTasks.isPending ? t("tasks.archiving") : t("tasks.archiveDoneTasks")}
              </Button>
            </div>
          )}
        </TabsContent>
        <TabsContent value="calendar">
          <ProjectCalendarView
            tasks={statusFilteredTasks}
            canOpenTask={canViewTaskDetails}
            onTaskClick={onTaskClick}
          />
        </TabsContent>
        <TabsContent value="gantt">
          <ProjectGanttView
            tasks={statusFilteredTasks}
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
                  <Plus className="h-4 w-4" />
                  {t("tasks.addTask")}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top" sideOffset={12}>
                {t("tasks.enterTooltip")}
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
          <Dialog open={isBulkEditDialogOpen} onOpenChange={setIsBulkEditDialogOpen}>
            <TaskBulkEditDialog
              selectedTasks={selectedTasks}
              taskStatuses={sortedTaskStatuses}
              userOptions={userOptions}
              isSubmitting={bulkUpdateTasks.isPending}
              onApply={(changes) => {
                bulkUpdateTasks.mutate({
                  taskIds: selectedTasks.map((t) => t.id),
                  changes,
                });
              }}
              onCancel={() => setIsBulkEditDialogOpen(false)}
            />
          </Dialog>
          <BulkEditTaskTagsDialog
            open={isBulkEditTagsDialogOpen}
            onOpenChange={setIsBulkEditTagsDialogOpen}
            tasks={selectedTasks}
            onSuccess={() => {}}
          />
        </>
      ) : null}

      <ConfirmDialog
        open={isArchiveDialogOpen}
        onOpenChange={setIsArchiveDialogOpen}
        title={t("tasks.archiveDialogTitle")}
        description={(() => {
          const count =
            archiveDialogStatusId !== undefined
              ? (archivableCountByStatus[archiveDialogStatusId] ?? 0)
              : archivableDoneTasksCount;
          return t("tasks.archiveDialogDescription", { count });
        })()}
        confirmLabel={t("tasks.archiveConfirm")}
        onConfirm={() => {
          archiveDoneTasks.mutate(archiveDialogStatusId);
          setIsArchiveDialogOpen(false);
        }}
        isLoading={archiveDoneTasks.isPending}
      />
    </div>
  );
};
