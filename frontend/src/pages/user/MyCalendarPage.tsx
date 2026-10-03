import { useNavigate } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type FilterCondition,
  type FilterGroup,
  type ListMyCalendarEntriesParams,
  type TaskPriority,
  type TaskStatusCategory,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import {
  buildEventCalendarEntry,
  buildTaskCalendarEntries,
  buildTaskOccurrenceEntries,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
  calendarVisibleRange,
  useCalendarVisibility,
} from "@/components/calendar";
import {
  CalendarPanelDropdown,
  type ProjectTaskCalendar,
} from "@/components/initiativeTools/events/CalendarListPanel";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { PullToRefresh } from "@/components/PullToRefresh";
import { CalendarGridSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useAuth } from "@/hooks/useAuth";
import { useMyCalendarEntries } from "@/hooks/useCalendarEntries";
import { useMyCalendars } from "@/hooks/useCalendars";
import { useCommunities } from "@/hooks/useCommunities";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useViewPreference } from "@/hooks/useViewPreference";
import { communityPath, useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { getProjectColor } from "@/lib/projectColor";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { entityRefRoute, toolSettingsRoute } from "@/lib/tools";

const STORAGE_KEY = "initiative-my-calendar-prefs";
const VISIBILITY_KEY = "initiative-my-calendar-visibility";

type StoredPrefs = {
  calendarViewMode: CalendarViewMode;
  statusFilters: TaskStatusCategory[];
  priorityFilters: TaskPriority[];
  communityFilters: number[];
};

const PREFS_DEFAULTS: StoredPrefs = {
  calendarViewMode: "month",
  // Match the historical My Tasks default: hide done tasks unless the user opts in.
  statusFilters: ["backlog", "todo", "in_progress"],
  priorityFilters: [],
  communityFilters: [],
};

const sanitizeStoredPrefs = (raw: unknown): StoredPrefs => {
  if (raw === null || typeof raw !== "object") return PREFS_DEFAULTS;
  const v = raw as Partial<StoredPrefs>;
  return {
    calendarViewMode:
      typeof v.calendarViewMode === "string"
        ? (v.calendarViewMode as CalendarViewMode)
        : PREFS_DEFAULTS.calendarViewMode,
    statusFilters: Array.isArray(v.statusFilters) ? v.statusFilters : PREFS_DEFAULTS.statusFilters,
    priorityFilters: Array.isArray(v.priorityFilters)
      ? v.priorityFilters
      : PREFS_DEFAULTS.priorityFilters,
    communityFilters: Array.isArray(v.communityFilters)
      ? v.communityFilters
      : PREFS_DEFAULTS.communityFilters,
  };
};

export const MyCalendarPage = () => {
  const { t } = useTranslation(["tasks", "calendars", "common"]);
  const { communities } = useCommunities();
  const { user } = useAuth();
  const gp = useCommunityPath();
  const navigate = useNavigate();

  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  // Calendar-specific state (server-persisted)
  const [storedPrefsRaw, setStoredPrefs] = useViewPreference<StoredPrefs>(
    STORAGE_KEY,
    PREFS_DEFAULTS
  );
  const storedPrefs = useMemo(() => sanitizeStoredPrefs(storedPrefsRaw), [storedPrefsRaw]);
  const { calendarViewMode } = storedPrefs;
  const setCalendarViewMode = useCallback(
    (next: CalendarViewMode) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), calendarViewMode: next })),
    [setStoredPrefs]
  );
  const { statusFilters, priorityFilters, communityFilters } = storedPrefs;
  const setStatusFilters = useCallback(
    (next: TaskStatusCategory[]) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), statusFilters: next })),
    [setStoredPrefs]
  );
  const setPriorityFilters = useCallback(
    (next: TaskPriority[]) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), priorityFilters: next })),
    [setStoredPrefs]
  );
  const setCommunityFilters = useCallback(
    (next: number[]) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), communityFilters: next })),
    [setStoredPrefs]
  );
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [focusDate, setFocusDate] = useState(() => new Date());

  // Per-calendar / per-project visibility, across every community.
  const visibility = useCalendarVisibility(VISIBILITY_KEY);

  // Badges the filter button while the panel is closed. Hidden calendars count:
  // the reader has narrowed the grid, and nothing else on screen says so.
  const activeFilterCount =
    visibility.hiddenCount +
    statusFilters.length +
    priorityFilters.length +
    communityFilters.length;

  const clearFilters = () => {
    visibility.clear();
    setStatusFilters([]);
    setPriorityFilters([]);
    setCommunityFilters([]);
  };

  const userTimezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  // The span the current view renders — the window events + tasks fetch over.
  const visibleRange = useMemo(
    () => calendarVisibleRange(focusDate, calendarViewMode, weekStartsOn),
    [focusDate, calendarViewMode, weekStartsOn]
  );

  // Task filter conditions (same JSON shape GET /me/tasks accepts). The date
  // window travels as start_after/start_before on the request (see
  // entriesParams) — the cross-community task path can only be windowed by those
  // params, not by conditions — so it isn't repeated here.
  const taskConditions = useMemo((): (FilterCondition | FilterGroup)[] => {
    const conditions: (FilterCondition | FilterGroup)[] = [];
    if (statusFilters.length > 0) {
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    }
    if (priorityFilters.length > 0) {
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    }
    if (communityFilters.length > 0) {
      conditions.push({ field: "community_ids", op: "in_", value: communityFilters });
    }
    return conditions;
  }, [statusFilters, priorityFilters, communityFilters]);

  // --- One request: cross-community events + assigned-task markers over the window. ---
  const entriesParams = useMemo((): ListMyCalendarEntriesParams => {
    const params: ListMyCalendarEntriesParams = {
      start_after: visibleRange.start.toISOString(),
      start_before: visibleRange.end.toISOString(),
      conditions: taskConditions,
      tz: userTimezone,
      include_events: true,
      include_tasks: true,
    };
    if (communityFilters.length > 0) {
      params.community_ids = communityFilters;
    }
    return params;
  }, [visibleRange, taskConditions, userTimezone, communityFilters]);

  const entriesQuery = useMyCalendarEntries(entriesParams);

  // The user's visible calendars across communities — the grouping panel's rows and
  // the color source for events without their own color.
  const calendarsQuery = useMyCalendars(
    communityFilters.length > 0 ? { community_ids: communityFilters } : undefined
  );
  const calendars = useMemo(() => calendarsQuery.data?.items ?? [], [calendarsQuery.data]);
  const calendarColors = useMemo(() => {
    const map = new Map<string, string>();
    for (const calendar of calendars)
      map.set(`${calendar.community_id}:${calendar.id}`, calendar.color);
    return map;
  }, [calendars]);

  const communityNamesById = useMemo(() => {
    const map = new Map<number, string>();
    for (const community of communities) map.set(community.id, community.name);
    return map;
  }, [communities]);
  const multiCommunity = communities.length > 1;

  const handleRefresh = useCallback(async () => {
    await invalidate(q.allTasks(), q.allCalendars());
  }, []);

  // One read-only virtual calendar per project with a task in the window.
  const projectCalendars = useMemo<ProjectTaskCalendar[]>(() => {
    const seen = new Map<string, ProjectTaskCalendar>();
    const data = entriesQuery.data;
    for (const task of [...(data?.tasks ?? []), ...(data?.task_occurrences ?? [])]) {
      if (task.project_id == null) continue;
      const key = `${task.community_id ?? 0}:${task.project_id}`;
      if (seen.has(key)) continue;
      const communityName =
        multiCommunity && task.community_id != null
          ? communityNamesById.get(task.community_id)
          : undefined;
      const baseName = task.project_name ?? `#${task.project_id}`;
      seen.set(key, {
        projectId: task.project_id,
        communityId: task.community_id ?? 0,
        name: communityName ? `${baseName} · ${communityName}` : baseName,
        color: getProjectColor(task.project_id),
      });
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [entriesQuery.data, communityNamesById, multiCommunity]);

  // --- Merge tasks + events into calendar entries (visibility-filtered) ---
  const unread = useUnreadTree();
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    // Task entries. Reuse the shared builder so the start/due markers get the
    // same visual treatment as the other calendars, injecting communityId into
    // meta for cross-community navigation. Not draggable here (My Calendar has no
    // reschedule handler).
    const data = entriesQuery.data;
    const occurrences = new Set(data?.task_occurrences);
    for (const task of [...(data?.tasks ?? []), ...occurrences]) {
      if (
        task.project_id != null &&
        visibility.isProjectHidden(task.community_id, task.project_id)
      ) {
        continue;
      }
      const color = getProjectColor(task.project_id);
      for (const entry of occurrences.has(task)
        ? buildTaskOccurrenceEntries(task, color)
        : buildTaskCalendarEntries(task, color, false)) {
        entries.push({
          ...entry,
          meta: { ...(entry.meta as Record<string, unknown>), communityId: task.community_id },
        });
      }
    }

    for (const event of entriesQuery.data?.events ?? []) {
      if (visibility.isCalendarHidden(event.community_id, event.calendar_id)) continue;
      entries.push(
        buildEventCalendarEntry(
          event,
          calendarColors.get(`${event.community_id}:${event.calendar_id}`),
          unread.hasSubject(event.community_id, "calendar_event", event.id)
        )
      );
    }

    return entries;
  }, [entriesQuery.data, visibility, calendarColors, unread]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | {
          type: string;
          taskId?: number;
          eventId?: number;
          communityId?: number;
          occurrence?: string;
        }
      | undefined;
    if (!meta) return;
    const scopedPath = (path: string) =>
      meta.communityId ? communityPath(meta.communityId, path) : gp(path);
    // Cross-community rows carry no initiative, so the resolver works out where
    // the entity lives on the way in.
    if (meta.type === "task" && meta.taskId) {
      void navigate({ to: scopedPath(entityRefRoute("task", meta.taskId)) });
    } else if (meta.type === "event" && meta.eventId) {
      void navigate({
        to: scopedPath(entityRefRoute("calendar-event", meta.eventId)),
        search: meta.occurrence ? { occurrence: meta.occurrence } : {},
      });
    }
  };

  // Status filter options
  const statusOptions = useMemo(
    () => [
      { value: "backlog" as TaskStatusCategory, label: t("tasks:statusCategory.backlog") },
      { value: "todo" as TaskStatusCategory, label: t("tasks:statusCategory.todo") },
      { value: "in_progress" as TaskStatusCategory, label: t("tasks:statusCategory.in_progress") },
      { value: "done" as TaskStatusCategory, label: t("tasks:statusCategory.done") },
    ],
    [t]
  );

  // Wait for the calendars metadata too (same gate as the community page):
  // entries rendered before it resolves would flash the generic event color
  // until each calendar's own color arrives.
  const isLoading =
    (entriesQuery.isLoading && !entriesQuery.data) ||
    (calendarsQuery.isLoading && !calendarsQuery.data);

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <h1 className="font-semibold text-3xl tracking-tight">{t("tasks:myCalendar.title")}</h1>

        <ToolListToolbar
          filters={{
            open: filtersOpen,
            onOpenChange: setFiltersOpen,
            activeCount: activeFilterCount,
          }}
        />

        <ToolFilterPanel
          open={filtersOpen}
          onOpenChange={setFiltersOpen}
          title={t("tasks:filters.heading")}
          onClear={clearFilters}
          activeCount={activeFilterCount}
        >
          <div className="flex flex-wrap items-end gap-4">
            {/* Calendar visibility — the user's calendars across communities +
                  per-project task calendars behind one dropdown. */}
            <div className="flex items-end">
              <CalendarPanelDropdown
                calendars={calendars}
                projectCalendars={projectCalendars}
                isCalendarHidden={(calendar) =>
                  visibility.isCalendarHidden(calendar.community_id, calendar.id)
                }
                isProjectHidden={(project) =>
                  visibility.isProjectHidden(project.communityId, project.projectId)
                }
                onToggleCalendar={(calendar) =>
                  visibility.toggleCalendar(calendar.community_id, calendar.id)
                }
                onToggleProject={(project) =>
                  visibility.toggleProject(project.communityId, project.projectId)
                }
                calendarLabel={(calendar) => {
                  const communityName = multiCommunity
                    ? communityNamesById.get(calendar.community_id)
                    : undefined;
                  return communityName ? `${calendar.name} · ${communityName}` : calendar.name;
                }}
                settingsPathFor={(calendar) =>
                  communityPath(
                    calendar.community_id,
                    toolSettingsRoute(Tool.calendar, calendar.initiative_id, calendar.id)
                  )
                }
                canCreate={false}
                onCreate={() => {}}
              />
            </div>
            <div className="w-full sm:w-48 lg:flex-1">
              <Label className="mb-2 block font-medium text-muted-foreground text-xs">
                {t("tasks:filters.filterByStatusCategory")}
              </Label>
              <MultiSelect
                selectedValues={statusFilters}
                options={statusOptions.map((o) => ({ value: o.value, label: o.label }))}
                onChange={(values) => setStatusFilters(values as TaskStatusCategory[])}
                placeholder={t("tasks:filters.allStatusCategories")}
                emptyMessage={t("tasks:filters.noStatusCategories")}
              />
            </div>
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
            <div className="w-full sm:w-48 lg:flex-1">
              <Label className="mb-2 block font-medium text-muted-foreground text-xs">
                {t("tasks:filters.filterByCommunity")}
              </Label>
              <MultiSelect
                selectedValues={communityFilters.map(String)}
                options={communities.map((community) => ({
                  value: String(community.id),
                  label: community.name,
                }))}
                onChange={(values) => {
                  const numericValues = values.map(Number).filter(Number.isFinite);
                  setCommunityFilters(numericValues);
                }}
                placeholder={t("tasks:filters.allCommunities")}
                emptyMessage={t("tasks:filters.noCommunities")}
              />
            </div>
          </div>
        </ToolFilterPanel>

        {entriesQuery.isError ? (
          <p className="text-destructive text-sm" role="alert">
            {getErrorMessage(entriesQuery.error, "calendars:loadError")}
          </p>
        ) : null}

        {isLoading ? (
          <SkeletonRegion>
            <CalendarGridSkeleton />
          </SkeletonRegion>
        ) : (
          <CalendarView
            entries={calendarEntries}
            viewMode={calendarViewMode}
            onViewModeChange={setCalendarViewMode}
            focusDate={focusDate}
            onFocusDateChange={setFocusDate}
            onEntryClick={handleEntryClick}
            weekStartsOn={weekStartsOn}
          />
        )}
      </div>
    </PullToRefresh>
  );
};
