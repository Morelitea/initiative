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
import { useNavigate, useSearch } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import {
  Archive,
  BookmarkPlus,
  Calendar,
  Kanban,
  Plus,
  RotateCcw,
  Save,
  Table,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskFilterSpec as ApiTaskFilterSpec,
  TaskListRead,
  TaskRead,
  TaskReorderRequest,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  buildTaskCalendarEntries,
  CALENDAR_VIEW_MODE_KEY,
  type CalendarEntry,
  type CalendarEntryReschedule,
  CalendarView,
  type CalendarViewMode,
} from "@/components/calendar";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { ToolPresetSelect } from "@/components/initiativeTools/shared/ToolPresetSelect";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { ProjectFilterPresetDialog } from "@/components/projects/ProjectFilterPresetDialog";
import { ProjectTaskComposer } from "@/components/projects/ProjectTaskComposer";
import { ProjectTasksFilters } from "@/components/projects/ProjectTasksFilters";
import { ProjectTasksKanbanView } from "@/components/projects/ProjectTasksKanbanView";
import { ProjectTasksTableView } from "@/components/projects/ProjectTasksTableView";
import { priorityVariant } from "@/components/projects/projectTasksConfig";
import {
  computeMidpoint,
  isDraggingDown,
  reorderTaskList,
  resolveKanbanDropTarget,
  shouldInsertAfter,
} from "@/components/projects/taskOrdering";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { BulkEditTaskTagsDialog } from "@/components/tasks/BulkEditTaskTagsDialog";
import { ExportTasksButton } from "@/components/tasks/ExportTasksButton";
import { TaskBulkEditDialog } from "@/components/tasks/TaskBulkEditDialog";
import { TaskBulkEditPanel } from "@/components/tasks/TaskBulkEditPanel";
import {
  emptyTaskFormValue,
  serializeTaskFormValue,
  type TaskFormValue,
} from "@/components/tasks/TaskForm";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/hooks/useAuth";
import {
  useCreateFilterPreset,
  useFilterPresets,
  useUpdateFilterPreset,
} from "@/hooks/useFilterPresets";
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
import { resolvePresetState } from "@/lib/filters/presets";
import {
  buildTaskConditions,
  buildTaskListParams,
  EMPTY_TASK_FILTERS,
  specFromApi,
  specToApi,
  TASK_VIEW_MODES,
  type TaskFilterSpec,
  type TaskViewMode,
  taskFilterCount,
  taskFiltersEqual,
} from "@/lib/filters/taskFilters";
import { getProjectColor } from "@/lib/projectColor";
import { getItem, setItem } from "@/lib/storage";
import { taskReadToListRow } from "@/lib/taskUtils";

type ViewMode = TaskViewMode;

/**
 * What this project's task view remembers for one person: the filter values,
 * which view they were in, and which preset (if any) those filters came from.
 *
 * The filter half IS {@link TaskFilterSpec} — the same object a saved preset
 * holds and the same one the URL names — so a preset can be applied, tweaked,
 * and saved back without translating between shapes.
 */
type StoredFilters = TaskFilterSpec & {
  viewMode: ViewMode;
  /** The preset these values came from, or null once they were tweaked. */
  activePresetSlug: string | null;
};

const DEFAULT_FILTERS: StoredFilters = {
  ...EMPTY_TASK_FILTERS,
  viewMode: "table",
  activePresetSlug: null,
};

/** The pre-preset key names, still on disk for anyone who has used the app.
 *  Read once and written back in the new shape, so nobody loses their filters. */
type LegacyStoredFilters = {
  assigneeFilters?: unknown;
  dueFilter?: unknown;
  statusFilters?: unknown;
  tagFilters?: unknown;
  propertyFilters?: unknown;
  showArchived?: unknown;
};

const numberList = (raw: unknown): number[] | undefined =>
  Array.isArray(raw) ? raw.filter((v): v is number => typeof v === "number") : undefined;

/**
 * Coerce whatever shape comes back from the server (or a legacy
 * localStorage blob) into a valid ``StoredFilters``. Drops any field
 * with the wrong type so a stale or corrupted blob can't crash the UI.
 */
function sanitizeStoredFilters(raw: unknown): StoredFilters {
  if (raw === null || typeof raw !== "object") return DEFAULT_FILTERS;
  const parsed = raw as Partial<StoredFilters> & LegacyStoredFilters;
  const out: StoredFilters = {
    ...DEFAULT_FILTERS,
    ...specFromApi(parsed as ApiTaskFilterSpec),
  };
  if (TASK_VIEW_MODES.includes(parsed.viewMode as ViewMode)) {
    out.viewMode = parsed.viewMode as ViewMode;
  }
  if (typeof parsed.activePresetSlug === "string") {
    out.activePresetSlug = parsed.activePresetSlug;
  }

  // Legacy key names, used only when the modern one is absent.
  if (parsed.assignees === undefined && Array.isArray(parsed.assigneeFilters)) {
    out.assignees = parsed.assigneeFilters.filter((v): v is string => typeof v === "string");
  }
  if (parsed.due === undefined && typeof parsed.dueFilter === "string") {
    out.due = parsed.dueFilter === "all" ? null : (parsed.dueFilter as StoredFilters["due"]);
  }
  if (parsed.status_ids === undefined) {
    out.status_ids = numberList(parsed.statusFilters) ?? out.status_ids;
  }
  if (parsed.tag_ids === undefined) {
    out.tag_ids = numberList(parsed.tagFilters) ?? out.tag_ids;
  }
  if (parsed.properties === undefined && Array.isArray(parsed.propertyFilters)) {
    out.properties = (parsed.propertyFilters as PropertyFilterCondition[]).filter(
      (entry) =>
        entry !== null && typeof entry === "object" && typeof entry.property_id === "number"
    );
  }
  if (parsed.include_archived === undefined && typeof parsed.showArchived === "boolean") {
    out.include_archived = parsed.showArchived;
  }
  return out;
}

type TaskViewOption = { value: ViewMode; labelKey: string; icon: LucideIcon };

const TASK_VIEW_OPTIONS: TaskViewOption[] = [
  { value: "table", labelKey: "tasks.viewTable", icon: Table },
  { value: "kanban", labelKey: "tasks.viewKanban", icon: Kanban },
  { value: "calendar", labelKey: "tasks.viewCalendar", icon: Calendar },
];

type ProjectTasksSectionProps = {
  projectId: number;
  /**
   * Initiative the project belongs to. Threaded down to the table view so
   * programmatic property columns stay scoped to this initiative's
   * definitions.
   */
  initiativeId: number;
  taskStatuses: TaskStatusRead[];
  /** The project's configured default view, used only when this person has no
   *  view of their own yet and the URL doesn't name one. */
  projectDefaultViewMode?: string | null;
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
  projectDefaultViewMode,
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
  // Single source of truth for the aligned create dialog's fields (title,
  // description, status, priority, assignees, dates, recurrence, tags, and
  // custom properties). TaskForm mutates it via onChange; submit batches it
  // all into one create POST.
  const [composerValue, setComposerValue] = useState<TaskFormValue>(() => emptyTaskFormValue());
  const filterStorageKey = `project:${projectId}:view-filters`;
  // `null` fallback on purpose: "nothing saved yet" has to stay distinguishable
  // from "saved, and happens to equal the defaults", or someone's first visit
  // would shadow the project's own default preset with an empty one.
  const [storedFilters, setStoredFilters, { isLoaded: filtersLoaded }] =
    useViewPreference<StoredFilters | null>(filterStorageKey, null);
  const stored = useMemo(
    () => (storedFilters ? sanitizeStoredFilters(storedFilters) : null),
    [storedFilters]
  );
  const patchFilters = useCallback(
    (patch: Partial<StoredFilters>) =>
      setStoredFilters((prev) => ({ ...sanitizeStoredFilters(prev), ...patch })),
    [setStoredFilters]
  );

  // The project's shared presets. `can_manage` is computed server-side — a
  // project manager, the project owner, or a guild admin — and is what gates
  // every curation affordance below.
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { preset?: string; view?: ViewMode };
  const presetsQuery = useFilterPresets(projectId);
  const presetsLoaded = presetsQuery.isSuccess;
  const canManagePresets = presetsQuery.data?.can_manage ?? false;
  const presets = useMemo(
    () =>
      (presetsQuery.data?.items ?? []).map((preset) => ({
        ...preset,
        filters: specFromApi(preset.filters),
      })),
    [presetsQuery.data]
  );

  // URL first (a link means the same thing for whoever opens it), then what
  // this person last had, then the project's default. See lib/filters/presets.
  const { spec, viewMode, activeSlug, modified, unresolvedPreset } = useMemo(
    () =>
      resolvePresetState<TaskFilterSpec, ViewMode>({
        search,
        presets,
        stored:
          filtersLoaded && stored
            ? {
                spec: stored,
                viewMode: stored.viewMode,
                activePresetSlug: stored.activePresetSlug,
              }
            : null,
        allowedViews: TASK_VIEW_MODES,
        defaultView: projectDefaultViewMode,
        fallbackView: "table",
        emptySpec: EMPTY_TASK_FILTERS,
        equals: taskFiltersEqual,
      }),
    [search, presets, stored, filtersLoaded, projectDefaultViewMode]
  );

  // A preset named in the URL becomes this person's current view, so coming
  // back without the param finds it as they left it. Written once per slug:
  // the preference write is debounced and optimistic, and re-firing it every
  // render would race the router.
  const appliedPresetRef = useRef<string | null>(null);
  useEffect(() => {
    if (!filtersLoaded || !presetsLoaded) return;
    const slug = search.preset ?? null;
    if (slug === null || appliedPresetRef.current === slug) return;
    const preset = presets.find((candidate) => candidate.slug === slug);
    if (!preset) return;
    appliedPresetRef.current = slug;
    patchFilters({ ...preset.filters, activePresetSlug: slug });
  }, [search.preset, presets, filtersLoaded, presetsLoaded, patchFilters]);

  const setSearchParams = useCallback(
    (next: { preset?: string; view?: ViewMode }) => {
      // replace: the back button is for moving between resources, not for
      // stepping back through filter edits.
      // resetScroll: naming the preset in the URL is bookkeeping about the
      // list you are already looking at — the router's default would throw you
      // back to the top of it on every pick.
      void navigate({
        to: ".",
        search: ((prev: Record<string, unknown>) => ({ ...prev, ...next })) as never,
        replace: true,
        resetScroll: false,
      });
    },
    [navigate]
  );

  /**
   * Apply ad-hoc filter values.
   *
   * The preset stays recorded as where these values came from — that is what
   * lets the picker say "Incomplete · modified" and offer to fold the change
   * back into it. But it comes off the URL immediately: a link saying
   * `?preset=incomplete` has to show the preset, not one person's edit of it.
   */
  const applySpec = useCallback(
    (next: TaskFilterSpec) => {
      // Record the resolved view and origin preset alongside the values: this
      // may be the first thing ever written for this person, and the project's
      // defaults are what they were looking at when they made the edit.
      patchFilters({ ...next, viewMode, activePresetSlug: activeSlug });
      setSearchParams({ preset: undefined });
    },
    [patchFilters, setSearchParams, viewMode, activeSlug]
  );

  const selectPreset = useCallback(
    (slug: string | null) => {
      const preset = slug ? presets.find((candidate) => candidate.slug === slug) : null;
      appliedPresetRef.current = slug;
      patchFilters(
        preset ? { ...preset.filters, activePresetSlug: preset.slug } : { activePresetSlug: null }
      );
      setSearchParams({ preset: preset?.slug });
    },
    [presets, patchFilters, setSearchParams]
  );

  const [presetDialogOpen, setPresetDialogOpen] = useState(false);
  const createPreset = useCreateFilterPreset(projectId, {
    onSuccess: (created) => {
      setPresetDialogOpen(false);
      appliedPresetRef.current = created.slug;
      patchFilters({ activePresetSlug: created.slug });
      setSearchParams({ preset: created.slug });
      toast.success(t("filters.presetSaved"));
    },
  });
  const updatePreset = useUpdateFilterPreset(projectId, {
    onSuccess: () => toast.success(t("filters.presetSaved")),
  });

  const activePresetName = presets.find((preset) => preset.slug === activeSlug)?.name ?? "";

  /** Fold the current, tweaked filters back into the preset they came from. */
  const updateActivePreset = useCallback(() => {
    const active = presets.find((preset) => preset.slug === activeSlug);
    if (!active) return;
    updatePreset.mutate({ presetId: active.id, data: { filters: specToApi(spec) } });
  }, [presets, activeSlug, spec, updatePreset]);

  // Fetch guild tags for filtering
  const { data: tags = [] } = useTags();

  // Stale ids in a saved filter (a deleted tag, a removed status) simply match
  // nothing in the `in_` conditions, and the preset that named them is shared
  // rather than personal — so there is nothing to prune here any more.
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Badges the filter button while the panel is closed. Archived-included
  // counts: it widens what the list shows, which is as much a departure from
  // the default as narrowing it.
  const activeFilterCount = taskFilterCount(spec);

  const clearFilters = useCallback(() => applySpec(EMPTY_TASK_FILTERS), [applySpec]);

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

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canEditTaskDetails ? { run: () => setIsComposerOpen(true), label: t("tasks.addTask") } : null
  );

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
  // Persist the chosen sub-view (day/week/month/...) per-user, shared with the
  // other calendars via the same preference key.
  const [calendarViewMode, setCalendarViewMode] = useViewPreference<CalendarViewMode>(
    CALENDAR_VIEW_MODE_KEY,
    "month"
  );
  const [calendarFocusDate, setCalendarFocusDate] = useState(() => new Date());

  // Fetch tasks with server-side filtering (page_size=0 fetches all for
  // drag-and-drop). buildTaskListParams is shared with the route loader's
  // prefetch and the CSV export, so all three ask the same question.
  const taskListParams = useMemo(() => buildTaskListParams(spec, { projectId }), [spec, projectId]);

  const tasksQuery = useTasks(taskListParams, {
    enabled: Number.isFinite(projectId) && filtersLoaded && presetsLoaded,
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
    if (TASK_VIEW_MODES.includes(value as ViewMode)) {
      patchFilters({ viewMode: value as ViewMode });
      setSearchParams({ view: value as ViewMode });
    }
  };

  useEffect(() => {
    setLocalOverride(null);
  }, [projectTasks]);

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
      setComposerValue(emptyTaskFormValue({ statusId: defaultStatusId }));
      setIsComposerOpen(false);
      setLocalOverride((prev) => [...(prev ?? projectTasks), taskReadToListRow(newTask)]);
      toast.success(t("tasks.taskCreated"));
    },
  });

  // Seed the composer's status from the project default whenever it opens so
  // the user starts at the default but can override it. Also reset a status
  // that belongs to a different project — this section instance is reused when
  // navigating between projects, so a status id picked in the previous project
  // would otherwise linger and be submitted against the new one.
  useEffect(() => {
    if (isComposerOpen) {
      setComposerValue((prev) => {
        if (prev.statusId == null) {
          return { ...prev, statusId: defaultStatusId };
        }
        const belongsToProject = sortedTaskStatuses.some((status) => status.id === prev.statusId);
        if (!belongsToProject && sortedTaskStatuses.length > 0) {
          return { ...prev, statusId: defaultStatusId };
        }
        return prev;
      });
    }
  }, [isComposerOpen, defaultStatusId, sortedTaskStatuses]);

  // Dirty = the composer differs from a fresh form seeded at the default
  // status. Used to keep a backdrop click from discarding in-progress input.
  const composerDirty = useMemo(
    () =>
      serializeTaskFormValue(composerValue) !==
      serializeTaskFormValue(emptyTaskFormValue({ statusId: defaultStatusId })),
    [composerValue, defaultStatusId]
  );

  // Close and discard the composer draft so reopening starts fresh.
  const closeComposer = useCallback(() => {
    setComposerValue(emptyTaskFormValue({ statusId: defaultStatusId }));
    setIsComposerOpen(false);
  }, [defaultStatusId]);

  // Patch the locally-overridden task list with a server-confirmed update so
  // the board/calendar reflects it immediately (and drop the task if it no
  // longer matches the active status filter).
  const applyTaskUpdateToLocal = useCallback(
    (updatedTask: TaskRead) => {
      setLocalOverride((prev) => {
        const base = prev ?? projectTasks;
        if (!base.length) return prev;
        const matchesFilters =
          spec.status_ids.length === 0 || spec.status_ids.includes(updatedTask.task_status_id);
        if (matchesFilters) {
          const row = taskReadToListRow(updatedTask);
          return base.map((task) => (task.id === row.id ? row : task));
        }
        return base.filter((task) => task.id !== updatedTask.id);
      });
    },
    [projectTasks, spec.status_ids]
  );

  const updateTaskStatus = useUpdateTask({
    onSuccess: (updatedTask) => {
      applyTaskUpdateToLocal(updatedTask);
      toast.success(t("tasks.taskUpdated"));
    },
  });

  // Calendar drag-reschedule: patches the local list so the entry moves
  // immediately, but stays silent (no per-drag toast), matching the initiative
  // calendar's reschedule UX.
  const rescheduleTaskDates = useUpdateTask({
    onSuccess: applyTaskUpdateToLocal,
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

  // Due-date windows are applied server-side now (see buildTaskConditions), so
  // the board, the archive count, and the CSV export all agree with the list.
  const groupedTasks = useMemo(() => {
    const groups: Record<number, TaskListRead[]> = {};
    sortedTaskStatuses.forEach((status) => {
      groups[status.id] = [];
    });
    tasks.forEach((task) => {
      if (!groups[task.task_status_id]) {
        groups[task.task_status_id] = [];
      }
      groups[task.task_status_id].push(task);
    });
    return groups;
  }, [tasks, sortedTaskStatuses]);

  // Filtering is entirely server-side now.
  const statusFilteredTasks = tasks;

  // Map tasks to CalendarEntry[] for the generic CalendarView. Shares the
  // helper used by the initiative calendar so start/due markers, same-day
  // spans, tags, and drag-to-reschedule behave identically.
  const calendarEntries = useMemo(() => {
    const entries: CalendarEntry[] = [];
    statusFilteredTasks.forEach((task) => {
      entries.push(
        ...buildTaskCalendarEntries(task, getProjectColor(task.project_id), canEditTaskDetails)
      );
    });
    return entries;
  }, [statusFilteredTasks, canEditTaskDetails]);

  // Drag-to-reschedule on the calendar. Uses the silent date-update mutation
  // (patches the local list so the dropped entry moves immediately, no toast).
  // A start/due marker patches only that field; a same-day span shifts both
  // endpoints (CalendarView preserved the duration).
  const handleCalendarReschedule = useCallback(
    ({ entry, startAt, endAt }: CalendarEntryReschedule) => {
      const meta = entry.meta as
        | { type?: string; taskId?: number; kind?: "start" | "due" | "span" }
        | undefined;
      if (meta?.type !== "task" || !meta.taskId) return;
      if (meta.kind === "start") {
        rescheduleTaskDates.mutate({ taskId: meta.taskId, data: { start_date: startAt } });
      } else if (meta.kind === "due") {
        rescheduleTaskDates.mutate({ taskId: meta.taskId, data: { due_date: startAt } });
      } else {
        rescheduleTaskDates.mutate({
          taskId: meta.taskId,
          data: { start_date: startAt, due_date: endAt },
        });
      }
    },
    [rescheduleTaskDates]
  );

  // Count of archivable done tasks (non-archived tasks in done category)
  const archivableDoneTasksCount = useMemo(() => {
    return tasks.filter((task) => task.task_status.category === "done" && !task.is_archived).length;
  }, [tasks]);

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
    const { active } = event;
    const finalOver = resolveKanbanDropTarget(event, lastKanbanOverRef.current);
    const activeId = Number(active.id);
    const currentTask = Number.isFinite(activeId)
      ? tasks.find((task) => task.id === activeId)
      : undefined;
    if (!finalOver || !currentTask) {
      setActiveTaskId(null);
      lastKanbanOverRef.current = null;
      return;
    }

    const overData = finalOver.data;
    let targetStatusId = currentTask.task_status_id;
    let overTaskId: number | null = null;
    let insertAfter = false;

    if (overData?.type === "task") {
      targetStatusId = overData.statusId ?? targetStatusId;
      const parsed = Number(finalOver.id);
      overTaskId = Number.isFinite(parsed) ? parsed : null;
      if (targetStatusId === currentTask.task_status_id) {
        // Same column: derive before/after from the cards' current order. This
        // is the reliable arrayMove semantics the list view uses and reaches
        // both the top and bottom slots — the rect heuristic is unreliable here
        // because the sortable strategy shifts cards mid-drag (a drag to the top
        // would snap to the second slot).
        insertAfter = isDraggingDown(tasks, activeId, overTaskId);
      } else {
        // Cross column: there's no existing order to compare against, so decide
        // by which half of the target card the dragged card released over.
        // Without this the first slot of the column would be unreachable.
        insertAfter = shouldInsertAfter(active.rect.current.translated, finalOver.rect);
      }
    } else if (overData?.type === "column") {
      targetStatusId = overData.statusId ?? targetStatusId;
    }

    // Released on itself: nothing to persist, but the overlay still has to go.
    if (targetStatusId !== currentTask.task_status_id || overTaskId !== currentTask.id) {
      moveTaskInOrder(activeId, targetStatusId, overTaskId, insertAfter);
    }
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
        <ToolListToolbar
          heading={<h2 className="truncate font-semibold text-xl">{t("tasks.projectTasks")}</h2>}
          filters={{
            open: filtersOpen,
            onOpenChange: setFiltersOpen,
            activeCount: activeFilterCount,
          }}
          // The task views ARE this section's `Tabs`, so the picker has to be
          // the existing triggers rather than a second, nested Tabs.
          viewControl={
            <TabsList className="h-9">
              {TASK_VIEW_OPTIONS.map(({ value, labelKey, icon: Icon }) => (
                <TabsTrigger
                  key={value}
                  value={value}
                  aria-label={t(labelKey as never)}
                  className="gap-2 px-2.5 sm:px-3"
                >
                  <Icon className="h-4 w-4" />
                  <span className="hidden sm:inline">{t(labelKey as never)}</span>
                </TabsTrigger>
              ))}
            </TabsList>
          }
          trailing={
            /* resumePending: this is the view's single adopter of a stored
               in-flight job (the selection button must not double-handle it). */
            <ExportTasksButton
              params={{
                conditions: buildTaskConditions(spec, { projectId }),
                include_archived: spec.include_archived,
              }}
              resumePending
            />
          }
          actions={
            canEditTaskDetails ? (
              <TooltipProvider>
                <Tooltip delayDuration={400}>
                  <TooltipTrigger asChild>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-9"
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
            ) : null
          }
        />

        {unresolvedPreset ? (
          <Alert variant="default" className="mb-2">
            <AlertDescription>{t("filters.presetUnavailable")}</AlertDescription>
          </Alert>
        ) : null}

        <ToolFilterPanel
          open={filtersOpen}
          onOpenChange={setFiltersOpen}
          title={t("tasks.filtersHeading")}
          onClear={clearFilters}
          activeCount={activeFilterCount}
          leading={
            <ToolPresetSelect
              presets={presets}
              activeSlug={activeSlug}
              modified={modified}
              onSelect={selectPreset}
              label={t("filters.preset")}
              customLabel={t("filters.customFilters")}
              modifiedLabel={t("filters.modified")}
            />
          }
          actions={
            <>
              {/* Picking the preset again in the select can't undo an edit —
                  it is already the selected value — so getting back to it is
                  its own control, and it is for everyone, not just curators. */}
              {activeSlug && modified ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => selectPreset(activeSlug)}
                  title={activePresetName}
                >
                  <RotateCcw className="h-4 w-4" />
                  {t("filters.resetToPreset")}
                </Button>
              ) : null}
              {canManagePresets ? (
                <>
                  {activeSlug && modified ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={updateActivePreset}
                      disabled={updatePreset.isPending}
                    >
                      <Save className="h-4 w-4" />
                      {t("filters.updatePreset", { name: activePresetName })}
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="sm" onClick={() => setPresetDialogOpen(true)}>
                    <BookmarkPlus className="h-4 w-4" />
                    {t("filters.saveAsPreset")}
                  </Button>
                </>
              ) : null}
            </>
          }
        >
          <ProjectTasksFilters
            taskStatuses={sortedTaskStatuses}
            projectId={projectId}
            tags={tags}
            value={spec}
            onChange={applySpec}
          />
        </ToolFilterPanel>

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
              exportParams={{
                conditions: [{ field: "id", op: "in_", value: selectedTasks.map((t) => t.id) }],
                // Selection came from the visible list, which may include
                // archived rows when the toggle is on.
                include_archived: spec.include_archived,
              }}
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
              const meta = entry.meta as { taskId?: number } | undefined;
              if (meta?.taskId && canViewTaskDetails) onTaskClick(meta.taskId);
            }}
            onEntryReschedule={canEditTaskDetails ? handleCalendarReschedule : undefined}
            weekStartsOn={weekStartsOn}
          />
        </TabsContent>
      </Tabs>

      {canEditTaskDetails ? (
        <>
          <Dialog
            open={isComposerOpen}
            onOpenChange={(open) => (open ? setIsComposerOpen(true) : closeComposer())}
          >
            <ProjectTaskComposer
              canWrite={canWriteProject}
              isArchived={projectIsArchived}
              isSubmitting={createTask.isPending}
              hasError={Boolean(createTask.isError)}
              isDirty={composerDirty}
              form={{
                value: composerValue,
                onChange: setComposerValue,
                statuses: sortedTaskStatuses,
                projectId,
                initiativeId,
                currentUserId: user?.id,
                autoFocusTitle: true,
              }}
              onSubmit={() => {
                const selectedStatusId = composerValue.statusId ?? defaultStatusId;
                if (!selectedStatusId) {
                  toast.error(t("tasks.createError"));
                  return;
                }
                const payload: Record<string, unknown> = {
                  project_id: projectId,
                  title: composerValue.title,
                  description: composerValue.description,
                  priority: composerValue.priority,
                  assignee_ids: composerValue.assigneeIds,
                  start_date: composerValue.startDate
                    ? new Date(composerValue.startDate).toISOString()
                    : null,
                  due_date: composerValue.dueDate
                    ? new Date(composerValue.dueDate).toISOString()
                    : null,
                  task_status_id: selectedStatusId,
                  tag_ids: composerValue.tags.map((tg) => tg.id),
                  property_values: composerValue.properties.map((property) => ({
                    property_id: property.property_id,
                    value: composerValue.propertyValues[property.property_id] ?? null,
                  })),
                };
                if (composerValue.recurrence) {
                  payload.recurrence = composerValue.recurrence;
                  payload.recurrence_strategy = composerValue.recurrenceStrategy;
                } else {
                  payload.recurrence = null;
                  payload.recurrence_strategy = "fixed";
                }
                createTask.mutate(payload as never);
              }}
              onCancel={closeComposer}
            />
          </Dialog>
          <Dialog open={isBulkEditDialogOpen} onOpenChange={setIsBulkEditDialogOpen}>
            <TaskBulkEditDialog
              selectedTasks={selectedTasks}
              taskStatuses={sortedTaskStatuses}
              projectId={projectId}
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
          <ProjectFilterPresetDialog
            open={presetDialogOpen}
            onOpenChange={setPresetDialogOpen}
            isSubmitting={createPreset.isPending}
            onSubmit={({ name, isDefault }) =>
              createPreset.mutate({
                name,
                is_default: isDefault,
                filters: specToApi(spec),
              })
            }
          />

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
