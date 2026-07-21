import { useRouter, useSearch } from "@tanstack/react-router";
import { format } from "date-fns";
import { ChevronDown, Filter, Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CalendarEventSummary,
  FilterCondition,
  FilterGroup,
  ListCalendarEntriesApiV1GGuildIdCalendarEntriesGetParams,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendarEvents } from "@/api/query-keys";
import { BulkAccessBar, canManageSharing } from "@/components/access/BulkAccessBar";
import { BulkEditAccessDialog } from "@/components/access/BulkEditAccessDialog";
import {
  buildTaskCalendarEntries,
  CALENDAR_VIEW_MODE_KEY,
  type CalendarEntry,
  type CalendarEntryReschedule,
  CalendarView,
  type CalendarViewMode,
  calendarVisibleRange,
} from "@/components/calendar";
import { BulkExportButton } from "@/components/exports/BulkExportButton";
import { ExportButton } from "@/components/exports/ExportButton";
import { TOOL_EXPORT_FORMATS } from "@/components/exports/formats";
import { ToolImportAction } from "@/components/imports/ToolImportAction";
import { CreateEventDialog } from "@/components/initiativeTools/events/CreateEventDialog";
import { ICalImportDialog } from "@/components/initiativeTools/events/ICalImportDialog";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import {
  PropertyFilter,
  type PropertyFilterCondition,
} from "@/components/properties/PropertyFilter";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useAuth } from "@/hooks/useAuth";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useRescheduleCalendarEvent } from "@/hooks/useCalendarEvents";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useGridSelection } from "@/hooks/useGridSelection";
import { canCreateTool, useMyInitiativePermissions } from "@/hooks/useInitiativeRoles";
import { useProjects } from "@/hooks/useProjects";
import { useUpdateTask } from "@/hooks/useTasks";
import { useViewPreference } from "@/hooks/useViewPreference";
import { exportFilenameStem } from "@/lib/exportDownload";
import { useGuildPath } from "@/lib/guildUrl";
import { getProjectColor } from "@/lib/projectColor";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { getItem, setItem } from "@/lib/storage";
import { toolExportEndpoint } from "@/lib/tools";

const STORAGE_KEY = "initiative-events-prefs";

const STATUS_CATEGORIES: TaskStatusCategory[] = ["backlog", "todo", "in_progress", "done"];

interface StoredPrefs {
  showEvents: boolean;
  showTasks: boolean;
  statusFilters: TaskStatusCategory[];
  priorityFilters: TaskPriority[];
  projectFilters: number[];
  propertyFilters: PropertyFilterCondition[];
}

const PREFS_DEFAULTS: StoredPrefs = {
  showEvents: true,
  showTasks: true,
  statusFilters: [], // Don't apply default status filters - they're custom per guild
  priorityFilters: [],
  projectFilters: [],
  propertyFilters: [],
};

const readStoredPrefs = (): StoredPrefs => {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return PREFS_DEFAULTS;
    const parsed = JSON.parse(raw);
    return {
      showEvents:
        typeof parsed?.showEvents === "boolean" ? parsed.showEvents : PREFS_DEFAULTS.showEvents,
      showTasks:
        typeof parsed?.showTasks === "boolean" ? parsed.showTasks : PREFS_DEFAULTS.showTasks,
      statusFilters: Array.isArray(parsed?.statusFilters)
        ? parsed.statusFilters
        : PREFS_DEFAULTS.statusFilters,
      priorityFilters: Array.isArray(parsed?.priorityFilters)
        ? parsed.priorityFilters
        : PREFS_DEFAULTS.priorityFilters,
      projectFilters: Array.isArray(parsed?.projectFilters)
        ? parsed.projectFilters
        : PREFS_DEFAULTS.projectFilters,
      propertyFilters: Array.isArray(parsed?.propertyFilters)
        ? parsed.propertyFilters
        : PREFS_DEFAULTS.propertyFilters,
    };
  } catch {
    return PREFS_DEFAULTS;
  }
};

type EventsViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const EventsView = ({ fixedInitiativeId, canCreate }: EventsViewProps) => {
  const { t } = useTranslation(["calendarEvents", "tasks", "common", "access"]);
  const router = useRouter();
  const { user } = useAuth();
  const gp = useGuildPath();
  const _guildId = useActiveGuildId();
  const searchParams = useSearch({ strict: false }) as {
    initiativeId?: string;
    create?: string;
  };

  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  // Resolve initiative from prop or URL param
  const initiativeId =
    fixedInitiativeId ?? (searchParams.initiativeId ? Number(searchParams.initiativeId) : null);

  const { data: initiativePermissions } = useMyInitiativePermissions(initiativeId);

  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  // Calendar state — view mode persists per-user across all calendars.
  const [viewMode, setViewMode] = useViewPreference<CalendarViewMode>(
    CALENDAR_VIEW_MODE_KEY,
    "month"
  );
  const [focusDate, setFocusDate] = useState(() => new Date());

  // Filter state (persisted)
  const storedPrefs = useMemo(() => readStoredPrefs(), []);
  const [showEvents, setShowEvents] = useState(() => storedPrefs.showEvents);
  const [showTasks, setShowTasks] = useState(() => storedPrefs.showTasks);
  const [statusFilters, setStatusFilters] = useState<TaskStatusCategory[]>(
    () => storedPrefs.statusFilters
  );
  const [priorityFilters, setPriorityFilters] = useState<TaskPriority[]>(
    () => storedPrefs.priorityFilters
  );
  const [projectFilters, setProjectFilters] = useState<number[]>(() => storedPrefs.projectFilters);
  const [propertyFilters, setPropertyFilters] = useState<PropertyFilterCondition[]>(
    () => storedPrefs.propertyFilters
  );
  const [filtersOpen, setFiltersOpen] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches
  );

  // Reset project filter when initiative changes (project IDs are initiative-scoped)
  const prevInitiativeId = useRef(initiativeId);
  useEffect(() => {
    if (prevInitiativeId.current !== initiativeId) {
      prevInitiativeId.current = initiativeId;
      setProjectFilters([]);
    }
  }, [initiativeId]);

  // Persist preferences
  useEffect(() => {
    setItem(
      STORAGE_KEY,
      JSON.stringify({
        showEvents,
        showTasks,
        statusFilters,
        priorityFilters,
        projectFilters,
        propertyFilters,
      })
    );
  }, [showEvents, showTasks, statusFilters, priorityFilters, projectFilters, propertyFilters]);

  // The span the current view renders — the window events + tasks fetch over.
  const visibleRange = useMemo(
    () => calendarVisibleRange(focusDate, viewMode, weekStartsOn),
    [focusDate, viewMode, weekStartsOn]
  );

  // Serialize property filters into the query-param shape the backend
  // expects. Empty list drops the param entirely so the URL stays clean.
  const propertyFiltersParam = useMemo(() => {
    if (propertyFilters.length === 0) return undefined;
    return JSON.stringify(propertyFilters);
  }, [propertyFilters]);

  const userTimezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  // Task filter conditions (same JSON shape GET /tasks accepts). Built even when
  // tasks are toggled off so the memo is stable; the backend skips the task leg
  // via include_tasks below. The date window travels as start_after/start_before
  // on the request (see entriesParams) — the endpoint bounds the task leg by
  // those, so it isn't repeated here.
  const taskConditions = useMemo((): (FilterCondition | FilterGroup)[] => {
    const conditions: (FilterCondition | FilterGroup)[] = [];

    // If initiativeId is specified, filter by that initiative; otherwise show all guild tasks
    if (initiativeId) {
      conditions.push({ field: "initiative_ids", op: "in_", value: [initiativeId] });
    }

    // Only add filters if explicitly selected by user
    if (statusFilters.length > 0) {
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    }
    if (priorityFilters.length > 0) {
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    }
    if (projectFilters.length > 0) {
      conditions.push({ field: "project_id", op: "in_", value: projectFilters });
    }
    // Translate the shared PropertyFilter conditions into the tasks endpoint's
    // ``property_values`` virtual-field shape so the same filter row narrows
    // both events and tasks on the calendar. PropertyFilterCondition.op is
    // typed as string (runtime value matches FilterOp); cast here rather
    // than re-enumerate.
    for (const cond of propertyFilters) {
      conditions.push({
        field: "property_values",
        op: cond.op as FilterCondition["op"],
        value: { property_id: cond.property_id, value: cond.value },
      });
    }
    return conditions;
  }, [initiativeId, statusFilters, priorityFilters, projectFilters, propertyFilters]);

  // --- One request: events + task markers over the visible window. ---
  const entriesParams = useMemo(
    (): ListCalendarEntriesApiV1GGuildIdCalendarEntriesGetParams => ({
      ...(initiativeId ? { initiative_id: initiativeId } : {}),
      start_after: visibleRange.start.toISOString(),
      start_before: visibleRange.end.toISOString(),
      ...(propertyFiltersParam ? { property_filters: propertyFiltersParam } : {}),
      conditions: taskConditions,
      tz: userTimezone,
      include_events: showEvents,
      include_tasks: showTasks,
    }),
    [
      initiativeId,
      visibleRange,
      propertyFiltersParam,
      taskConditions,
      userTimezone,
      showEvents,
      showTasks,
    ]
  );

  const entriesQuery = useCalendarEntries(entriesParams);

  // Same param shape the sidebar and dashboard use, so this shares their cache.
  const projectsQuery = useProjects(undefined, { enabled: showTasks, staleTime: 30_000 });

  const canCreateEvents = useMemo(() => {
    if (canCreate !== undefined) return canCreate;
    if (initiativeId && initiativePermissions) {
      return canCreateTool(initiativePermissions, Tool.calendar_event);
    }
    return false;
  }, [canCreate, initiativeId, initiativePermissions]);

  // Tasks belong to projects; the precise per-project edit permission is
  // enforced by the backend on drop. Here we gate task-chip dragging on
  // project-create permission as a proxy, so users who can't manage project
  // content don't get draggable task chips. Decoupled from canCreateEvents so
  // event-create and task-edit are judged independently.
  const canEditTasks = useMemo(() => {
    if (initiativeId && initiativePermissions) {
      return canCreateTool(initiativePermissions, Tool.project);
    }
    return false;
  }, [initiativeId, initiativePermissions]);

  // --- Merge events + tasks into calendar entries ---
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    if (showEvents) {
      const items = entriesQuery.data?.events ?? [];
      items.forEach((event) => {
        entries.push({
          id: `event-${event.id}`,
          title: event.title,
          description: event.description,
          startAt: event.start_at,
          endAt: event.end_at,
          allDay: event.all_day,
          color: event.color ?? "#6366f1",
          attendees: (event.attendee_previews ?? []).map((att) => ({
            name: att.name,
            avatarUrl: att.avatar_url,
            avatarBase64: att.avatar_base64,
            userId: att.user_id,
          })),
          properties: event.property_values,
          tags: event.tags,
          draggable: canCreateEvents,
          meta: { type: "event", eventId: event.id },
        });
      });
    }

    if (showTasks) {
      const tasks = entriesQuery.data?.tasks ?? [];
      tasks.forEach((task) => {
        entries.push(
          ...buildTaskCalendarEntries(task, getProjectColor(task.project_id), canEditTasks)
        );
      });
    }

    return entries;
  }, [showEvents, showTasks, entriesQuery.data, canCreateEvents, canEditTasks]);

  // --- Bulk edit-access selection (list view only) ---
  const eventSelection = useGridSelection<CalendarEventSummary>();
  const [bulkAccessOpen, setBulkAccessOpen] = useState(false);

  const eventsById = useMemo(() => {
    const map = new Map<number, CalendarEventSummary>();
    for (const event of entriesQuery.data?.events ?? []) map.set(event.id, event);
    return map;
  }, [entriesQuery.data]);

  const selectedEntryIds = useMemo(
    () => new Set<CalendarEntry["id"]>(eventSelection.selectedItems.map((e) => `event-${e.id}`)),
    [eventSelection.selectedItems]
  );

  const isEntrySelectable = useCallback(
    (entry: CalendarEntry) => (entry.meta as { type?: string } | undefined)?.type === "event",
    []
  );

  const toggleEntrySelection = useCallback(
    (entry: CalendarEntry) => {
      const eventId = (entry.meta as { eventId?: number } | undefined)?.eventId;
      const event = typeof eventId === "number" ? eventsById.get(eventId) : undefined;
      if (event) eventSelection.toggle(event);
    },
    [eventsById, eventSelection]
  );

  // Selection only exists in the list view — leaving it cancels the selection.
  // Depend on the stable primitive/callback, not the per-render selection object.
  const { active: selectionModeActive, exit: exitSelection } = eventSelection;
  useEffect(() => {
    if (viewMode !== "list" && selectionModeActive) exitSelection();
  }, [viewMode, selectionModeActive, exitSelection]);

  // Create dialog state
  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam({
    onClose: () => setCreateDefaultDate(null),
  });
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [createDefaultDate, setCreateDefaultDate] = useState<Date | null>(null);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateEvents && initiativeId
      ? {
          run: () => {
            setCreateDefaultDate(null);
            setCreateDialogOpen(true);
          },
          label: t("createEvent"),
        }
      : null
  );

  const handleEventCreated = (event: { id: number }) => {
    void router.navigate({ to: gp(`/calendar-events/${event.id}`) });
  };

  const handleSlotClick = (date: Date) => {
    if (!canCreateEvents || !initiativeId) return;
    setCreateDefaultDate(date);
    setCreateDialogOpen(true);
  };

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as { type: string; taskId?: number; eventId?: number } | undefined;
    if (!meta) return;
    if (meta.type === "event" && meta.eventId) {
      void router.navigate({ to: gp(`/calendar-events/${meta.eventId}`) });
    } else if (meta.type === "task" && meta.taskId) {
      void router.navigate({ to: gp(`/tasks/${meta.taskId}`) });
    }
  };

  // Drag-to-reschedule: route the computed new times to the right mutation.
  // A start/due marker patches only that field; an event or same-day span
  // shifts both endpoints (CalendarView already preserved the duration).
  const updateTask = useUpdateTask();
  const rescheduleEvent = useRescheduleCalendarEvent();

  const handleEntryReschedule = useCallback(
    ({ entry, startAt, endAt }: CalendarEntryReschedule) => {
      const meta = entry.meta as
        | { type?: string; taskId?: number; eventId?: number; kind?: "start" | "due" | "span" }
        | undefined;
      if (!meta) return;
      if (meta.type === "event" && meta.eventId) {
        rescheduleEvent.mutate({
          eventId: meta.eventId,
          data: { start_at: startAt, end_at: endAt },
        });
        return;
      }
      if (meta.type === "task" && meta.taskId) {
        if (meta.kind === "start") {
          updateTask.mutate({ taskId: meta.taskId, data: { start_date: startAt } });
        } else if (meta.kind === "due") {
          updateTask.mutate({ taskId: meta.taskId, data: { due_date: startAt } });
        } else {
          updateTask.mutate({
            taskId: meta.taskId,
            data: { start_date: startAt, due_date: endAt },
          });
        }
      }
    },
    [updateTask, rescheduleEvent]
  );

  const defaultStartDate = createDefaultDate ? format(createDefaultDate, "yyyy-MM-dd") : undefined;

  const statusOptions = useMemo(
    () =>
      STATUS_CATEGORIES.map((cat) => ({
        value: cat,
        label: t(`tasks:statusCategory.${cat}`),
      })),
    [t]
  );

  // Options for the project filter. Sourced from the projects list rather than
  // the task rows those filters produce: the rows only cover the visible date
  // window, so deriving from them would drop a project from the dropdown on
  // every month it happens to have no task in — including the one currently
  // selected.
  const projectOptions = useMemo(() => {
    const projects = projectsQuery.data?.items ?? [];
    return projects
      .filter(
        (project) =>
          // Template projects are held out of the calendar's tasks, so an
          // option for one would filter to nothing.
          !project.is_template && (initiativeId === null || project.initiative_id === initiativeId)
      )
      .map((project) => ({ value: String(project.id), label: project.name }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [projectsQuery.data, initiativeId]);

  const isLoading = entriesQuery.isLoading && !entriesQuery.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <div className="flex items-center gap-2">
          <ExportButton
            endpoint={toolExportEndpoint(Tool.calendar_event)}
            params={initiativeId ? { initiative_id: initiativeId } : {}}
            formats={TOOL_EXPORT_FORMATS[Tool.calendar_event] ?? []}
            filenameStem={exportFilenameStem(t("title"), "calendar-events")}
          />
          {canCreateEvents && (
            <Button variant="outline" size="sm" onClick={() => setImportDialogOpen(true)}>
              <Upload className="h-4 w-4" />
              {t("import.importIcs")}
            </Button>
          )}
          <ToolImportAction
            tool={Tool.calendar_event}
            canImport={canCreateEvents}
            fixedInitiativeId={fixedInitiativeId}
          />
        </div>
      </div>

      {/* Filters */}
      <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
        <div className="flex items-center justify-between sm:hidden">
          <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
            <Filter className="h-4 w-4" />
            {t("filters.heading")}
          </div>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-8 px-3">
              {filtersOpen ? t("filters.hide") : t("filters.show")}
              <ChevronDown
                className={`h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
              />
            </Button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <div className="mt-2 flex flex-wrap items-end gap-4 rounded-md border border-muted bg-background/40 p-3 sm:mt-0">
            {/* Status filter (for tasks) */}
            {showTasks && (
              <div className="w-full sm:w-48 lg:flex-1">
                <Label className="mb-2 block font-medium text-muted-foreground text-xs">
                  {t("tasks:filters.filterByStatusCategory")}
                </Label>
                <MultiSelect
                  selectedValues={statusFilters}
                  options={statusOptions}
                  onChange={(values) => setStatusFilters(values as TaskStatusCategory[])}
                  placeholder={t("tasks:filters.allStatusCategories")}
                  emptyMessage={t("tasks:filters.noStatusCategories")}
                />
              </div>
            )}

            {/* Priority filter (for tasks) */}
            {showTasks && (
              <div className="w-full sm:w-48 lg:flex-1">
                <Label className="mb-2 block font-medium text-muted-foreground text-xs">
                  {t("tasks:filters.filterByPriority")}
                </Label>
                <MultiSelect
                  selectedValues={priorityFilters}
                  options={PRIORITY_ORDER.map((p) => ({
                    value: p,
                    label: t(`tasks:priority.${p}` as never),
                  }))}
                  onChange={(values) => setPriorityFilters(values as TaskPriority[])}
                  placeholder={t("tasks:filters.allPriorities")}
                  emptyMessage={t("tasks:filters.noPriorities")}
                />
              </div>
            )}

            {/* Project filter (for tasks) */}
            {showTasks && (projectOptions.length > 1 || projectFilters.length > 0) && (
              <div className="w-full sm:w-48 lg:flex-1">
                <Label className="mb-2 block font-medium text-muted-foreground text-xs">
                  {t("common:project", "Project")}
                </Label>
                <MultiSelect
                  selectedValues={projectFilters.map(String)}
                  options={projectOptions}
                  onChange={(values) =>
                    setProjectFilters(values.map(Number).filter(Number.isFinite))
                  }
                  placeholder={t("common:all")}
                  emptyMessage={t("common:none")}
                />
              </div>
            )}

            {/* Type toggles */}
            <div className="flex items-end gap-2">
              <Button
                variant={showEvents ? "default" : "outline"}
                size="sm"
                onClick={() => setShowEvents(!showEvents)}
              >
                {t("calendarEvents:event")}
              </Button>
              <Button
                variant={showTasks ? "default" : "outline"}
                size="sm"
                onClick={() => setShowTasks(!showTasks)}
              >
                {t("tasks:myCalendar.typeTasks" as never)}
              </Button>
            </div>
            {/* Custom property filters — applied to both events and tasks
                rendered on the calendar. Scoped to the active initiative
                when one is selected, union across accessible initiatives
                otherwise. Nested inside the same bordered filter container
                so it lines up with the other controls. */}
            <div className="w-full">
              <PropertyFilter
                value={propertyFilters}
                onChange={setPropertyFilters}
                {...(initiativeId != null ? { initiativeId } : {})}
              />
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : (
        <div className="space-y-3">
          {eventSelection.active ? (
            <BulkAccessBar
              count={eventSelection.selectedItems.length}
              canManage={canManageSharing(eventSelection.selectedItems)}
              onEditAccess={() => setBulkAccessOpen(true)}
              onExit={eventSelection.exit}
            >
              <BulkExportButton
                tool={Tool.calendar_event}
                ids={eventSelection.selectedItems.map((e) => e.id)}
              />
            </BulkAccessBar>
          ) : viewMode === "list" ? (
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={eventSelection.enter}>
                {t("access:bulkBar.select")}
              </Button>
            </div>
          ) : null}
          <CalendarView
            entries={calendarEntries}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            focusDate={focusDate}
            onFocusDateChange={setFocusDate}
            onEntryClick={handleEntryClick}
            onSlotClick={canCreateEvents ? handleSlotClick : undefined}
            onEntryReschedule={canCreateEvents || canEditTasks ? handleEntryReschedule : undefined}
            weekStartsOn={weekStartsOn}
            selectionActive={eventSelection.active}
            selectedEntryIds={selectedEntryIds}
            isEntrySelectable={isEntrySelectable}
            onToggleEntrySelection={toggleEntrySelection}
          />
        </div>
      )}

      {initiativeId && (
        <CreateEventDialog
          open={createDialogOpen}
          onOpenChange={handleCreateDialogOpenChange}
          initiativeId={initiativeId}
          defaultStartDate={defaultStartDate}
          onSuccess={handleEventCreated}
        />
      )}

      <BulkEditAccessDialog
        open={bulkAccessOpen}
        onOpenChange={setBulkAccessOpen}
        items={eventSelection.selectedItems}
        resourceType={Tool.calendar_event}
        invalidate={invalidateAllCalendarEvents}
        onSuccess={eventSelection.exit}
      />

      <ICalImportDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        fixedInitiativeId={initiativeId ?? undefined}
      />
    </div>
  );
};

export function EventsPage() {
  return <EventsView />;
}
