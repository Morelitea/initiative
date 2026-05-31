import {
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { arrayMove } from "@dnd-kit/sortable";
import type { LucideIcon } from "lucide-react";
import {
  Archive,
  Calendar,
  ChevronDown,
  Filter,
  GanttChart,
  Kanban,
  Plus,
  Table,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  FilterCondition,
  ListTasksApiV1TasksGetParams,
  TaskListRead,
  TaskListReadRecurrenceStrategy,
  TaskPriority,
  TaskRecurrenceOutput,
  TaskReorderRequest,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import { type CalendarEntry, CalendarView, type CalendarViewMode } from "@/components/calendar";
import { ProjectGanttView } from "@/components/projects/ProjectGanttView";
import { ProjectTaskComposer } from "@/components/projects/ProjectTaskComposer";
import { ProjectTasksFilters } from "@/components/projects/ProjectTasksFilters";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import {
  type DueFilterOption,
  priorityVariant,
  type UserOption,
} from "@/components/projects/projectTasksConfig";
import {
  computeMidpoint,
  reorderTaskList,
  shouldInsertAfter,
} from "@/components/projects/taskOrdering";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { BulkEditTaskTagsDialog } from "@/components/tasks/BulkEditTaskTagsDialog";
import { TaskBulkEditDialog } from "@/components/tasks/TaskBulkEditDialog";
import { TaskBulkEditPanel } from "@/components/tasks/TaskBulkEditPanel";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog } from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/hooks/useAuth";
import { useTags } from "@/hooks/useTags";
import {
  useArchiveDoneTasks,
  useBulkArchiveTasks,
  useBulkDeleteTasks,
  useBulkUpdateTasks,
  useCreateTask,
  useReorderTasks,
  useTasks,
  useUpdateTask,
} from "@/hooks/useTasks";
import { useViewPreference } from "@/hooks/useViewPreference";
import { toast } from "@/lib/chesterToast";
import { getItem, setItem } from "@/lib/storage";

type ViewMode = "table" | "kanban" | "calendar" | "gantt";

type StoredFilters = {
  viewMode: ViewMode;
  assigneeFilters: string[];
  dueFilter: DueFilterOption;
  statusFilters: number[];
  tagFilters: number[];
  propertyFilters: PropertyFilterCondition[];
  showArchived: boolean;
};

const DEFAULT_FILTERS: StoredFilters = {
  viewMode: "table",
  assigneeFilters: [],
  dueFilter: "all",
  statusFilters: [],
  tagFilters: [],
  propertyFilters: [],
  showArchived: false,
};

/**
 * Coerce whatever shape comes back from the server (or a legacy
 * localStorage blob) into a valid ``StoredFilters``. Drops any field
 * with the wrong type so a stale or corrupted blob can't crash the UI.
 */
function sanitizeStoredFilters(raw: unknown): StoredFilters {
  if (raw === null || typeof raw !== "object") return DEFAULT_FILTERS;
  const parsed = raw as Partial<StoredFilters>;
  const out: StoredFilters = { ...DEFAULT_FILTERS };
  if (
    parsed.viewMode === "table" ||
    parsed.viewMode === "kanban" ||
    parsed.viewMode === "calendar" ||
    parsed.viewMode === "gantt"
  ) {
    out.viewMode = parsed.viewMode;
  }
  if (Array.isArray(parsed.assigneeFilters)) {
    out.assigneeFilters = parsed.assigneeFilters.filter((v): v is string => typeof v === "string");
  }
  if (parsed.dueFilter) {
    out.dueFilter = parsed.dueFilter;
  }
  if (Array.isArray(parsed.statusFilters)) {
    out.statusFilters = parsed.statusFilters.filter((v): v is number => typeof v === "number");
  }
  if (Array.isArray(parsed.tagFilters)) {
    out.tagFilters = parsed.tagFilters.filter((v): v is number => typeof v === "number");
  }
  if (Array.isArray(parsed.propertyFilters)) {
    out.propertyFilters = parsed.propertyFilters.filter(
      (entry): entry is PropertyFilterCondition =>
        entry !== null &&
        typeof entry === "object" &&
        typeof (entry as PropertyFilterCondition).property_id === "number" &&
        typeof (entry as PropertyFilterCondition).op === "string"
    );
  }
  if (typeof parsed.showArchived === "boolean") {
    out.showArchived = parsed.showArchived;
  }
  return out;
}

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
  /**
   * Initiative the project belongs to. Threaded down to the table view so
   * programmatic property columns stay scoped to this initiative's
   * definitions.
   */
  initiativeId: number;
  taskStatuses: TaskStatusRead[];
  userOptions: UserOption[];
  canEditTaskDetails: boolean;
  canWriteProject: boolean;
  projectIsArchived: boolean;
  canViewTaskDetails: boolean;
  onTaskClick: (taskId: number) => void;
  initialComposerOpen?: boolean;
  onComposerOpenChange?: (isOpen: boolean) => void;
};

export const ProjectTasksSection = ({
  projectId,
  initiativeId,
  taskStatuses,
  userOptions,
  canEditTaskDetails,
  canWriteProject,
  projectIsArchived,
  canViewTaskDetails,
  onTaskClick,
  initialComposerOpen,
  onComposerOpenChange,
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
  const [recurrenceStrategy, setRecurrenceStrategy] =
    useState<TaskListReadRecurrenceStrategy>("fixed");
  const filterStorageKey = `project:${projectId}:view-filters`;
  const [storedFilters, setStoredFilters, { isLoaded: filtersLoaded }] =
    useViewPreference<StoredFilters>(filterStorageKey, DEFAULT_FILTERS);
  const filters = useMemo(() => sanitizeStoredFilters(storedFilters), [storedFilters]);
  const {
    viewMode,
    assigneeFilters,
    dueFilter,
    statusFilters,
    tagFilters,
    propertyFilters,
    showArchived,
  } = filters;
  const patchFilters = useCallback(
    (patch: Partial<StoredFilters>) => setStoredFilters((prev) => ({ ...prev, ...patch })),
    [setStoredFilters]
  );

  // Fetch guild tags for filtering
  const { data: tags = [] } = useTags();

  // Prune saved filters that reference items the user no longer has access
  // to (deleted tag, removed status, ex-member). The hook value is the
  // source of truth for filters; once the lookup data resolves we strip
  // any dangling IDs and write the cleaned blob back, so future loads
  // don't have to re-pay for the diff.
  const tagsLoaded = tags !== undefined;
  const userOptionsLoaded = userOptions.length > 0;
  useEffect(() => {
    if (!filtersLoaded || !tagsLoaded || !userOptionsLoaded) return;
    const tagIds = new Set(tags.map((tg) => tg.id));
    const statusIds = new Set(sortedTaskStatuses.map((s) => s.id));
    const assigneeIdsSet = new Set(userOptions.map((u) => String(u.id)));
    const cleaned: StoredFilters = {
      ...filters,
      tagFilters: filters.tagFilters.filter((id) => tagIds.has(id)),
      statusFilters: filters.statusFilters.filter((id) => statusIds.has(id)),
      assigneeFilters: filters.assigneeFilters.filter((id) => assigneeIdsSet.has(id)),
    };
    if (
      cleaned.tagFilters.length !== filters.tagFilters.length ||
      cleaned.statusFilters.length !== filters.statusFilters.length ||
      cleaned.assigneeFilters.length !== filters.assigneeFilters.length
    ) {
      setStoredFilters(cleaned);
    }
    // Property filter pruning lives in the property filter UI itself
    // (it needs the property definitions, which aren't fetched here).
  }, [
    filtersLoaded,
    tagsLoaded,
    userOptionsLoaded,
    tags,
    sortedTaskStatuses,
    userOptions,
    filters,
    setStoredFilters,
  ]);
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [localOverride, setLocalOverride] = useState<TaskListRead[] | null>(null);
  const [isComposerOpen, setIsComposerOpen] = useState(initialComposerOpen ?? false);
  useEffect(() => {
    if (initialComposerOpen) {
      setIsComposerOpen(true);
    }
  }, [initialComposerOpen]);
  useEffect(() => {
    onComposerOpenChange?.(isComposerOpen);
  }, [isComposerOpen, onComposerOpenChange]);
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [selectedTasks, setSelectedTasks] = useState<TaskListRead[]>([]);
  const [isBulkEditDialogOpen, setIsBulkEditDialogOpen] = useState(false);
  const [isBulkEditTagsDialogOpen, setIsBulkEditTagsDialogOpen] = useState(false);
  const [isArchiveDialogOpen, setIsArchiveDialogOpen] = useState(false);
  const [archiveDialogStatusId, setArchiveDialogStatusId] = useState<number | undefined>(undefined);
  const lastKanbanOverRef = useRef<DragOverEvent["over"] | null>(null);

  // Calendar view state
  const { user } = useAuth();
  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;
  const [calendarViewMode, setCalendarViewMode] = useState<CalendarViewMode>("month");
  const [calendarFocusDate, setCalendarFocusDate] = useState(() => new Date());

  // Fetch tasks with server-side filtering (page_size=0 fetches all for drag-and-drop)
  const conditions: FilterCondition[] = [
    { field: "project_id", op: "eq", value: projectId },
    ...(assigneeFilters.length > 0
      ? [{ field: "assignee_ids", op: "in_" as const, value: assigneeFilters }]
      : []),
    ...(statusFilters.length > 0
      ? [{ field: "task_status_id", op: "in_" as const, value: statusFilters }]
      : []),
    ...(tagFilters.length > 0 ? [{ field: "tag_ids", op: "in_" as const, value: tagFilters }] : []),
    ...propertyFilters.map((entry) => ({
      field: "property_values" as const,
      op: entry.op as FilterCondition["op"],
      value: { property_id: entry.property_id, value: entry.value },
    })),
  ];
  const taskListParams: ListTasksApiV1TasksGetParams = {
    conditions,
    page_size: 0,
    ...(showArchived && { include_archived: true }),
  };

  const tasksQuery = useTasks(taskListParams, {
    enabled: Number.isFinite(projectId) && filtersLoaded,
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

  const handleViewModeChange = (value: string) => {
    if (value === "table" || value === "kanban" || value === "calendar" || value === "gantt") {
      patchFilters({ viewMode: value });
    }
  };
  const handleAssigneeFiltersChange = useCallback(
    (v: string[]) => patchFilters({ assigneeFilters: v }),
    [patchFilters]
  );
  const handleDueFilterChange = useCallback(
    (v: DueFilterOption) => patchFilters({ dueFilter: v }),
    [patchFilters]
  );
  const handleStatusFiltersChange = useCallback(
    (v: number[]) => patchFilters({ statusFilters: v }),
    [patchFilters]
  );
  const handleTagFiltersChange = useCallback(
    (v: number[]) => patchFilters({ tagFilters: v }),
    [patchFilters]
  );
  const handlePropertyFiltersChange = useCallback(
    (v: PropertyFilterCondition[]) => patchFilters({ propertyFilters: v }),
    [patchFilters]
  );
  const handleShowArchivedChange = useCallback(
    (v: boolean) => patchFilters({ showArchived: v }),
    [patchFilters]
  );

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

  const createTask = useCreateTask({
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
      toast.success(t("tasks.taskCreated"));
    },
  });

  const updateTaskStatus = useUpdateTask({
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
      toast.success(t("tasks.taskUpdated"));
    },
  });

  const bulkUpdateTasks = useBulkUpdateTasks({
    onSuccess: (updatedTasks) => {
      const count = updatedTasks.length;
      toast.success(t("tasks.bulkUpdated", { count }));
      // setSelectedTasks([]);
      setIsBulkEditDialogOpen(false);
      setLocalOverride(null);
    },
  });

  const bulkDeleteTasks = useBulkDeleteTasks({
    onSuccess: (_data, taskIds) => {
      const count = taskIds.length;
      toast.success(t("tasks.bulkDeleted", { count }));
      setSelectedTasks([]);
      setLocalOverride(null);
    },
  });

  const bulkArchiveTasks = useBulkArchiveTasks({
    onSuccess: (updatedTasks) => {
      const count = updatedTasks.length;
      toast.success(t("tasks.archivedSuccess", { count }));
      setSelectedTasks([]);
      setLocalOverride(null);
    },
  });

  const archiveDoneTasks = useArchiveDoneTasks({
    onSuccess: (data) => {
      const count = data.archived_count;
      if (count === 0) {
        toast.info(t("tasks.noDoneTasksToArchive"));
      } else {
        toast.success(t("tasks.archivedSuccess", { count }));
      }
    },
  });

  const { mutate: persistTaskOrderMutate, isPending: isPersistingOrder } = useReorderTasks();

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
    const groups: Record<number, TaskListRead[]> = {};
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

  // Map tasks to CalendarEntry[] for the generic CalendarView
  const calendarEntries = useMemo(() => {
    const entries: CalendarEntry[] = [];
    statusFilteredTasks.forEach((task) => {
      const taskAttendees = task.assignees
        .filter((a) => a.full_name)
        .map((a) => ({
          name: a.full_name!,
          avatarUrl: a.avatar_url,
          avatarBase64: a.avatar_base64,
          userId: a.id,
        }));

      if (task.due_date) {
        entries.push({
          id: `${task.id}-due`,
          title: task.title,
          startAt: task.due_date,
          endAt: task.due_date,
          allDay: true,
          attendees: taskAttendees,
        });
      }
      if (task.start_date) {
        entries.push({
          id: `${task.id}-start`,
          title: task.title,
          startAt: task.start_date,
          endAt: task.start_date,
          allDay: true,
          color: "#10b981",
          attendees: taskAttendees,
        });
      }
    });
    return entries;
  }, [statusFilteredTasks]);

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

  // Persist a single moved task: compute its fractional midpoint from its new
  // neighbors in the global order and send only that task (not the whole list).
  const persistMove = useCallback(
    (movedTaskId: number, taskStatusId: number, orderedTasks: TaskListRead[]) => {
      if (!Number.isFinite(projectId) || isPersistingOrder) {
        return;
      }
      const insertIndex = orderedTasks.findIndex((task) => task.id === movedTaskId);
      if (insertIndex === -1) {
        return;
      }
      const withoutMoved = orderedTasks.filter((task) => task.id !== movedTaskId);
      const payload: TaskReorderRequest = {
        project_id: projectId,
        items: [
          {
            id: movedTaskId,
            task_status_id: taskStatusId,
            position: computeMidpoint(withoutMoved, insertIndex),
          },
        ],
      };
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
    (taskId: number, targetStatusId: number, overTaskId: number | null, insertAfter: boolean) => {
      const targetStatus = statusLookup.get(targetStatusId);
      if (!targetStatus) {
        return;
      }
      let nextState: TaskListRead[] | null = null;
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        const currentTask = base.find((task) => task.id === taskId);
        if (!currentTask) {
          return prev;
        }
        const updatedTask: TaskListRead = {
          ...currentTask,
          task_status_id: targetStatus.id,
          task_status: targetStatus,
        };
        nextState = reorderTaskList(base, updatedTask, overTaskId, insertAfter, targetStatus.id);
        return nextState;
      });
      if (nextState) {
        persistMove(taskId, targetStatus.id, nextState);
      }
    },
    [persistMove, statusLookup, projectTasks]
  );

  const reorderListTasks = useCallback(
    (activeId: number, overId: number) => {
      let nextState: TaskListRead[] | null = null;
      let movedStatusId: number | null = null;
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        const oldIndex = base.findIndex((task) => task.id === activeId);
        const newIndex = base.findIndex((task) => task.id === overId);
        if (oldIndex === -1 || newIndex === -1) {
          return prev;
        }
        movedStatusId = base[oldIndex].task_status_id;
        nextState = arrayMove(base, oldIndex, newIndex);
        return nextState;
      });
      if (nextState && movedStatusId !== null) {
        persistMove(activeId, movedStatusId, nextState);
      }
    },
    [persistMove, projectTasks]
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
    let insertAfter = false;

    if (overData?.type === "task") {
      targetStatusId = overData.statusId ?? targetStatusId;
      const parsed = Number(finalOver.id);
      overTaskId = Number.isFinite(parsed) ? parsed : null;
      // Drop before/after the target depending on which half of it the dragged
      // card's center released over (the first slot of a column was otherwise
      // unreachable — drops always snapped to the second slot).
      insertAfter = shouldInsertAfter(active.rect.current.translated, finalOver.rect);
    } else if (overData?.type === "column") {
      targetStatusId = overData.statusId ?? targetStatusId;
    }

    if (targetStatusId === currentTask.task_status_id && overTaskId === currentTask.id) {
      return;
    }

    moveTaskInOrder(activeId, targetStatusId, overTaskId, insertAfter);
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
            <h2 className="font-semibold text-xl">{t("tasks.projectTasks")}</h2>
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
            <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
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
              taskStatuses={sortedTaskStatuses}
              userOptions={userOptions}
              tags={tags}
              assigneeFilters={assigneeFilters}
              dueFilter={dueFilter}
              statusFilters={statusFilters}
              tagFilters={tagFilters}
              propertyFilters={propertyFilters}
              showArchived={showArchived}
              onAssigneeFiltersChange={handleAssigneeFiltersChange}
              onDueFilterChange={handleDueFilterChange}
              onStatusFiltersChange={handleStatusFiltersChange}
              onTagFiltersChange={handleTagFiltersChange}
              onPropertyFiltersChange={handlePropertyFiltersChange}
              onShowArchivedChange={handleShowArchivedChange}
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
            projectId={projectId}
            initiativeId={initiativeId}
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
                data: { task_status_id: taskStatusId },
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
          <CalendarView
            entries={calendarEntries}
            viewMode={calendarViewMode}
            onViewModeChange={setCalendarViewMode}
            focusDate={calendarFocusDate}
            onFocusDateChange={setCalendarFocusDate}
            onEntryClick={(entry) => {
              const taskId = Number(String(entry.id).split("-")[0]);
              if (canViewTaskDetails) onTaskClick(taskId);
            }}
            weekStartsOn={weekStartsOn}
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
                  className="fixed right-6 bottom-6 z-40 h-12 rounded-full px-6 shadow-lg shadow-primary/40"
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
              onSubmit={() => {
                if (!defaultStatusId) {
                  toast.error(t("tasks.createError"));
                  return;
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
                createTask.mutate(payload as never);
              }}
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
                  changes: changes as Parameters<typeof bulkUpdateTasks.mutate>[0]["changes"],
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
          archiveDoneTasks.mutate({
            projectId,
            taskStatusId: archiveDialogStatusId,
          });
          setIsArchiveDialogOpen(false);
        }}
        isLoading={archiveDoneTasks.isPending}
      />
    </div>
  );
};
