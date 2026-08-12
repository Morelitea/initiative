import { useParams, useRouter, useSearch } from "@tanstack/react-router";
import { format } from "date-fns";
import { ChevronDown, Filter, Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CalendarSummary,
  FilterCondition,
  FilterGroup,
  ListCalendarEntriesApiV1GGuildIdCalendarEntriesGetParams,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  buildTaskCalendarEntries,
  CALENDAR_VIEW_MODE_KEY,
  type CalendarEntry,
  type CalendarEntryReschedule,
  CalendarView,
  type CalendarViewMode,
  calendarVisibleRange,
} from "@/components/calendar";
import { ExportButton } from "@/components/exports/ExportButton";
import { TOOL_EXPORT_FORMATS } from "@/components/exports/formats";
import { ToolImportAction } from "@/components/imports/ToolImportAction";
import {
  CalendarPanelDropdown,
  type ProjectTaskCalendar,
} from "@/components/initiativeTools/events/CalendarListPanel";
import { CreateCalendarDialog } from "@/components/initiativeTools/events/CreateCalendarDialog";
import {
  CreateEventDialog,
  isWritableCalendar,
} from "@/components/initiativeTools/events/CreateEventDialog";
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
import { useCalendar, useCalendarsList } from "@/hooks/useCalendars";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { getDefaultFiltersVisibility } from "@/hooks/useDefaultFiltersOpen";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useProjects } from "@/hooks/useProjects";
import { useRecordRecentView } from "@/hooks/useRecents";
import { useUpdateTask } from "@/hooks/useTasks";
import { useViewPreference } from "@/hooks/useViewPreference";
import { exportFilenameStem } from "@/lib/exportDownload";
import { useGuildPath } from "@/lib/guildUrl";
import { getProjectColor } from "@/lib/projectColor";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { getItem, setItem } from "@/lib/storage";
import { toolExportEndpoint } from "@/lib/tools";

const STORAGE_KEY = "initiative-calendars-prefs";
const VISIBILITY_KEY = "initiative-calendar-visibility";

const STATUS_CATEGORIES: TaskStatusCategory[] = ["backlog", "todo", "in_progress", "done"];

const DEFAULT_EVENT_COLOR = "#6366f1";

interface StoredPrefs {
  statusFilters: TaskStatusCategory[];
  priorityFilters: TaskPriority[];
  propertyFilters: PropertyFilterCondition[];
}

const PREFS_DEFAULTS: StoredPrefs = {
  statusFilters: [], // Don't apply default status filters - they're custom per guild
  priorityFilters: [],
  propertyFilters: [],
};

const readStoredPrefs = (): StoredPrefs => {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return PREFS_DEFAULTS;
    const parsed = JSON.parse(raw);
    return {
      statusFilters: Array.isArray(parsed?.statusFilters)
        ? parsed.statusFilters
        : PREFS_DEFAULTS.statusFilters,
      priorityFilters: Array.isArray(parsed?.priorityFilters)
        ? parsed.priorityFilters
        : PREFS_DEFAULTS.priorityFilters,
      propertyFilters: Array.isArray(parsed?.propertyFilters)
        ? parsed.propertyFilters
        : PREFS_DEFAULTS.propertyFilters,
    };
  } catch {
    return PREFS_DEFAULTS;
  }
};

// Visibility persists as HIDDEN id sets (per guild) so a newly created
// calendar or project appears checked by default — tasks default on.
interface StoredVisibility {
  hiddenCalendarIds: number[];
  hiddenProjectIds: number[];
}

const readStoredVisibility = (guildId: number): StoredVisibility => {
  try {
    const raw = getItem(`${VISIBILITY_KEY}:${guildId}`);
    if (!raw) return { hiddenCalendarIds: [], hiddenProjectIds: [] };
    const parsed = JSON.parse(raw);
    return {
      hiddenCalendarIds: Array.isArray(parsed?.hiddenCalendarIds) ? parsed.hiddenCalendarIds : [],
      hiddenProjectIds: Array.isArray(parsed?.hiddenProjectIds) ? parsed.hiddenProjectIds : [],
    };
  } catch {
    return { hiddenCalendarIds: [], hiddenProjectIds: [] };
  }
};

const toggleInSet = (prev: ReadonlySet<number>, id: number): Set<number> => {
  const next = new Set(prev);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  return next;
};

type CalendarsViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
  /** Focus a single calendar (the /calendars/$calendarId route): it is forced
   * visible so the deep link always shows its events. */
  focusCalendarId?: number;
  /** A guild calendar rendered as its own whole surface — the calendar app.
   * Guild apps show guild-level content only, so this mode shows exactly this
   * calendar's events: no tasks, no projects, no other calendars, no
   * initiative-flavored filters. */
  soloCalendar?: CalendarSummary;
};

export const CalendarsView = ({
  fixedInitiativeId,
  canCreate,
  focusCalendarId,
  soloCalendar,
}: CalendarsViewProps) => {
  const { t } = useTranslation(["calendars", "tasks", "common", "access"]);
  const router = useRouter();
  const { user } = useAuth();
  const gp = useGuildPath();
  const guildId = useActiveGuildId();
  const searchParams = useSearch({ strict: false }) as {
    initiativeId?: string;
    create?: string;
  };

  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  const solo = soloCalendar != null;

  // Resolve initiative from prop or URL param. A solo (guild) calendar belongs
  // to no initiative, so none applies.
  const initiativeId = solo
    ? null
    : (fixedInitiativeId ?? (searchParams.initiativeId ? Number(searchParams.initiativeId) : null));

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
  const [statusFilters, setStatusFilters] = useState<TaskStatusCategory[]>(
    () => storedPrefs.statusFilters
  );
  const [priorityFilters, setPriorityFilters] = useState<TaskPriority[]>(
    () => storedPrefs.priorityFilters
  );
  const [propertyFilters, setPropertyFilters] = useState<PropertyFilterCondition[]>(
    () => storedPrefs.propertyFilters
  );
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  // Per-calendar / per-project visibility (persisted per guild as hidden sets).
  const storedVisibility = useMemo(() => readStoredVisibility(guildId), [guildId]);
  const [hiddenCalendarIds, setHiddenCalendarIds] = useState<Set<number>>(
    () => new Set(storedVisibility.hiddenCalendarIds)
  );
  const [hiddenProjectIds, setHiddenProjectIds] = useState<Set<number>>(
    () => new Set(storedVisibility.hiddenProjectIds)
  );

  // A deep-linked calendar is always shown, whatever the stored toggles say.
  useEffect(() => {
    if (focusCalendarId === undefined) return;
    setHiddenCalendarIds((prev) => {
      if (!prev.has(focusCalendarId)) return prev;
      const next = new Set(prev);
      next.delete(focusCalendarId);
      return next;
    });
  }, [focusCalendarId]);

  // Persist preferences
  useEffect(() => {
    setItem(STORAGE_KEY, JSON.stringify({ statusFilters, priorityFilters, propertyFilters }));
  }, [statusFilters, priorityFilters, propertyFilters]);

  useEffect(() => {
    setItem(
      `${VISIBILITY_KEY}:${guildId}`,
      JSON.stringify({
        hiddenCalendarIds: [...hiddenCalendarIds],
        hiddenProjectIds: [...hiddenProjectIds],
      })
    );
  }, [guildId, hiddenCalendarIds, hiddenProjectIds]);

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

  // Task filter conditions (same JSON shape GET /tasks accepts). The date
  // window travels as start_after/start_before on the request (see
  // entriesParams) — the endpoint bounds the task leg by those.
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
  }, [initiativeId, statusFilters, priorityFilters, propertyFilters]);

  // --- One request: events + task markers over the visible window. ---
  const entriesParams = useMemo((): ListCalendarEntriesApiV1GGuildIdCalendarEntriesGetParams => {
    // Solo: exactly this calendar's events, and nothing task- or
    // initiative-shaped at all.
    if (solo) {
      return {
        calendar_ids: [soloCalendar.id],
        start_after: visibleRange.start.toISOString(),
        start_before: visibleRange.end.toISOString(),
        tz: userTimezone,
        include_events: true,
        include_tasks: false,
      };
    }
    return {
      ...(initiativeId ? { initiative_id: initiativeId } : {}),
      start_after: visibleRange.start.toISOString(),
      start_before: visibleRange.end.toISOString(),
      ...(propertyFiltersParam ? { property_filters: propertyFiltersParam } : {}),
      conditions: taskConditions,
      tz: userTimezone,
      include_events: true,
      include_tasks: true,
    };
  }, [
    solo,
    soloCalendar?.id,
    initiativeId,
    visibleRange,
    propertyFiltersParam,
    taskConditions,
    userTimezone,
  ]);

  const entriesQuery = useCalendarEntries(entriesParams);

  // The real calendars backing the list panel, colors, and the create seams.
  const calendarsQuery = useCalendarsList(
    {
      page_size: 200,
      ...(initiativeId ? { initiative_id: initiativeId } : {}),
    },
    { enabled: !solo }
  );
  const calendars = useMemo(
    () => (solo ? [soloCalendar] : (calendarsQuery.data?.items ?? [])),
    [solo, soloCalendar, calendarsQuery.data]
  );
  const calendarsById = useMemo(() => {
    const map = new Map<number, (typeof calendars)[number]>();
    for (const calendar of calendars) map.set(calendar.id, calendar);
    return map;
  }, [calendars]);

  // Same param shape the sidebar and dashboard use, so this shares their cache.
  const projectsQuery = useProjects(undefined, { staleTime: 30_000, enabled: !solo });
  const projectNamesById = useMemo(() => {
    const map = new Map<number, string>();
    for (const project of projectsQuery.data?.items ?? []) map.set(project.id, project.name);
    return map;
  }, [projectsQuery.data]);

  // One read-only virtual calendar per project with a task in the window —
  // fully derived from the entries payload, never stored.
  const projectCalendars = useMemo<ProjectTaskCalendar[]>(() => {
    const seen = new Map<number, ProjectTaskCalendar>();
    for (const task of entriesQuery.data?.tasks ?? []) {
      if (task.project_id == null || seen.has(task.project_id)) continue;
      seen.set(task.project_id, {
        projectId: task.project_id,
        guildId: task.guild_id ?? guildId,
        name: projectNamesById.get(task.project_id) ?? `#${task.project_id}`,
        color: getProjectColor(task.project_id),
      });
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [entriesQuery.data, projectNamesById, guildId]);

  // Creating a CALENDAR is the role-permission gate; creating an EVENT is
  // write access on at least one calendar (the project→task pattern). An
  // explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateCalendarsDerived } = useToolCreateAccess(Tool.calendar, {
    initiativeId,
  });
  const canCreateCalendars = solo ? false : (canCreate ?? canCreateCalendarsDerived);
  const writableCalendars = useMemo(() => calendars.filter(isWritableCalendar), [calendars]);
  const canCreateEvents = writableCalendars.length > 0;

  // --- Merge events + tasks into calendar entries (visibility-filtered) ---
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    for (const event of entriesQuery.data?.events ?? []) {
      if (hiddenCalendarIds.has(event.calendar_id)) continue;
      const calendar = calendarsById.get(event.calendar_id);
      entries.push({
        id: `event-${event.id}`,
        title: event.title,
        description: event.description,
        startAt: event.start_at,
        endAt: event.end_at,
        allDay: event.all_day,
        // Events render in their calendar's stored color.
        color: calendar?.color ?? DEFAULT_EVENT_COLOR,
        attendees: (event.attendee_previews ?? []).map((att) => ({
          name: att.name,
          avatarUrl: att.avatar_url,
          avatarBase64: att.avatar_base64,
          userId: att.user_id,
        })),
        properties: event.property_values,
        tags: event.tags,
        draggable: event.my_permission_level === "write" || event.my_permission_level === "owner",
        meta: { type: "event", eventId: event.id },
      });
    }

    for (const task of entriesQuery.data?.tasks ?? []) {
      if (task.project_id != null && hiddenProjectIds.has(task.project_id)) continue;
      // Task chips stay non-draggable here: per-project edit rights vary
      // across the visible projects; the task page is the editing surface.
      entries.push(...buildTaskCalendarEntries(task, getProjectColor(task.project_id), false));
    }

    return entries;
  }, [entriesQuery.data, hiddenCalendarIds, hiddenProjectIds, calendarsById]);

  // Create dialog state
  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam({
    onClose: () => setCreateDefaultDate(null),
  });
  const [createCalendarOpen, setCreateCalendarOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [createDefaultDate, setCreateDefaultDate] = useState<Date | null>(null);

  // Drive the app-wide bottom-nav add button for this route. Creating an
  // event needs a writable calendar; with none, offer calendar creation.
  useRegisterPrimaryCreateAction(
    canCreateEvents
      ? {
          run: () => {
            setCreateDefaultDate(null);
            setCreateDialogOpen(true);
          },
          label: t("createEvent"),
        }
      : canCreateCalendars
        ? {
            run: () => setCreateCalendarOpen(true),
            label: t("createCalendar"),
          }
        : null
  );

  const handleEventCreated = (event: { id: number }) => {
    void router.navigate({ to: gp(`/calendar-events/${event.id}`) });
  };

  const handleSlotClick = (date: Date) => {
    if (!canCreateEvents) return;
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

  // Drag-to-reschedule for events (the backend enforces calendar write).
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

  const isLoading =
    (entriesQuery.isLoading && !entriesQuery.data) ||
    (calendarsQuery.isLoading && !calendarsQuery.data);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-semibold text-3xl tracking-tight">
          {solo ? soloCalendar.name : t("title")}
        </h1>
        <div className="flex items-center gap-2">
          {/* Export and tool import aggregate across calendars, which is not
              what a single guild calendar's surface is; ICS import stays — a
              club calendar is exactly what one imports events into. */}
          {!solo && (
            <ExportButton
              endpoint={toolExportEndpoint(Tool.calendar)}
              params={initiativeId ? { initiative_id: initiativeId } : {}}
              formats={TOOL_EXPORT_FORMATS[Tool.calendar] ?? []}
              filenameStem={exportFilenameStem(t("title"), "calendars")}
            />
          )}
          {canCreateEvents && (
            <Button variant="outline" size="sm" onClick={() => setImportDialogOpen(true)}>
              <Upload className="h-4 w-4" />
              {t("import.importIcs")}
            </Button>
          )}
          {!solo && (
            <ToolImportAction
              tool={Tool.calendar}
              canImport={canCreateCalendars}
              fixedInitiativeId={fixedInitiativeId}
            />
          )}
        </div>
      </div>

      {/* Filters — task- and initiative-shaped, so the solo (guild calendar)
          surface has none of them. */}
      {!solo && (
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
              {/* Calendar visibility — real calendars + per-project task
                calendars behind one dropdown, so the grid keeps full width. */}
              <div className="flex items-end">
                <CalendarPanelDropdown
                  calendars={calendars}
                  projectCalendars={projectCalendars}
                  isCalendarHidden={(calendar) => hiddenCalendarIds.has(calendar.id)}
                  isProjectHidden={(project) => hiddenProjectIds.has(project.projectId)}
                  onToggleCalendar={(calendar) =>
                    setHiddenCalendarIds((prev) => toggleInSet(prev, calendar.id))
                  }
                  onToggleProject={(project) =>
                    setHiddenProjectIds((prev) => toggleInSet(prev, project.projectId))
                  }
                  settingsPathFor={(calendar) => gp(`/calendars/${calendar.id}/settings`)}
                  canCreate={canCreateCalendars}
                  onCreate={() => setCreateCalendarOpen(true)}
                />
              </div>

              {/* Status filter (for tasks) */}
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

              {/* Priority filter (for tasks) */}
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
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : (
        <CalendarView
          entries={calendarEntries}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          focusDate={focusDate}
          onFocusDateChange={setFocusDate}
          onEntryClick={handleEntryClick}
          onSlotClick={canCreateEvents ? handleSlotClick : undefined}
          onEntryReschedule={handleEntryReschedule}
          weekStartsOn={weekStartsOn}
        />
      )}

      <CreateEventDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        {...(solo ? { calendarId: soloCalendar.id } : {})}
        defaultCalendarId={focusCalendarId}
        {...(fixedInitiativeId !== undefined ? { initiativeId: fixedInitiativeId } : {})}
        defaultStartDate={defaultStartDate}
        onSuccess={handleEventCreated}
      />

      <CreateCalendarDialog
        open={createCalendarOpen}
        onOpenChange={setCreateCalendarOpen}
        initiativeId={fixedInitiativeId}
        defaultInitiativeId={initiativeId ?? undefined}
      />

      <ICalImportDialog open={importDialogOpen} onOpenChange={setImportDialogOpen} />
    </div>
  );
};

export function CalendarsPage() {
  return <CalendarsView />;
}

/** The /calendars/$calendarId deep link (recents tabs, command palette):
 * the same calendar page with that calendar forced visible, recorded as a
 * recent open. */
export function CalendarFocusPage() {
  const { calendarId: calendarIdParam, guildId } = useParams({ strict: false });
  const calendarId = Number(calendarIdParam);
  const calendarQuery = useCalendar(Number.isFinite(calendarId) ? calendarId : null);
  const calendar = calendarQuery.data;

  // Track recently viewed calendars for the layout header tabs bar — only
  // once the read succeeds (access checks passed).
  const recordViewMutation = useRecordRecentView("calendar", Number(guildId));
  const viewedCalendarId = calendar?.id;
  useEffect(() => {
    if (!viewedCalendarId) return;
    recordViewMutation.mutate(viewedCalendarId);
  }, [viewedCalendarId, recordViewMutation.mutate]);

  // Which kind of calendar decides which surface renders, so nothing renders
  // until the read resolves: a guild calendar (the app) must never flash the
  // guild-wide view, whose fetches reach into initiative content.
  if (!calendar) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }

  const isGuildCalendar = calendar.initiative_id == null;
  return (
    <CalendarsView
      focusCalendarId={calendar.id}
      soloCalendar={isGuildCalendar ? calendar : undefined}
    />
  );
}
