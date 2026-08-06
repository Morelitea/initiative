import { useNavigate } from "@tanstack/react-router";
import { ChevronDown, Download, Filter, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type {
  FilterCondition,
  FilterGroup,
  ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendars, invalidateAllTasks } from "@/api/query-keys";
import {
  buildTaskCalendarEntries,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
  calendarVisibleRange,
} from "@/components/calendar";
import {
  CalendarListPanel,
  type ProjectTaskCalendar,
} from "@/components/initiativeTools/events/CalendarListPanel";
import { PullToRefresh } from "@/components/PullToRefresh";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useAuth } from "@/hooks/useAuth";
import { useMyCalendarEntries } from "@/hooks/useCalendarEntries";
import { useMyCalendars } from "@/hooks/useCalendars";
import { getDefaultFiltersVisibility } from "@/hooks/useDefaultFiltersOpen";
import { useGuilds } from "@/hooks/useGuilds";
import { useViewPreference } from "@/hooks/useViewPreference";
import { toast } from "@/lib/chesterToast";
import { guildPath, useGuildPath } from "@/lib/guildUrl";
import { getProjectColor } from "@/lib/projectColor";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { getItem, setItem } from "@/lib/storage";

const STORAGE_KEY = "initiative-my-calendar-prefs";
const VISIBILITY_KEY = "initiative-my-calendar-visibility";

type StoredPrefs = {
  calendarViewMode: CalendarViewMode;
  statusFilters: TaskStatusCategory[];
  priorityFilters: TaskPriority[];
  guildFilters: number[];
};

const PREFS_DEFAULTS: StoredPrefs = {
  calendarViewMode: "month",
  // Match the historical My Tasks default: hide done tasks unless the user opts in.
  statusFilters: ["backlog", "todo", "in_progress"],
  priorityFilters: [],
  guildFilters: [],
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
    guildFilters: Array.isArray(v.guildFilters) ? v.guildFilters : PREFS_DEFAULTS.guildFilters,
  };
};

// Visibility persists as HIDDEN key sets so new calendars/projects appear
// checked. Cross-guild, so keys are "guildId:entityId" — per-guild ids
// collide across guilds.
interface StoredVisibility {
  hiddenCalendarKeys: string[];
  hiddenProjectKeys: string[];
}

const readStoredVisibility = (): StoredVisibility => {
  try {
    const raw = getItem(VISIBILITY_KEY);
    if (!raw) return { hiddenCalendarKeys: [], hiddenProjectKeys: [] };
    const parsed = JSON.parse(raw);
    return {
      hiddenCalendarKeys: Array.isArray(parsed?.hiddenCalendarKeys)
        ? parsed.hiddenCalendarKeys
        : [],
      hiddenProjectKeys: Array.isArray(parsed?.hiddenProjectKeys) ? parsed.hiddenProjectKeys : [],
    };
  } catch {
    return { hiddenCalendarKeys: [], hiddenProjectKeys: [] };
  }
};

const toggleInSet = (prev: ReadonlySet<string>, key: string): Set<string> => {
  const next = new Set(prev);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  return next;
};

export const MyCalendarPage = () => {
  const { t } = useTranslation(["tasks", "calendars", "common"]);
  const { guilds } = useGuilds();
  const { user } = useAuth();
  const gp = useGuildPath();
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
  const { statusFilters, priorityFilters, guildFilters } = storedPrefs;
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
  const setGuildFilters = useCallback(
    (next: number[]) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), guildFilters: next })),
    [setStoredPrefs]
  );
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);
  const [focusDate, setFocusDate] = useState(() => new Date());

  // Per-calendar / per-project visibility (persisted, cross-guild keys).
  const storedVisibility = useMemo(() => readStoredVisibility(), []);
  const [hiddenCalendarKeys, setHiddenCalendarKeys] = useState<Set<string>>(
    () => new Set(storedVisibility.hiddenCalendarKeys)
  );
  const [hiddenProjectKeys, setHiddenProjectKeys] = useState<Set<string>>(
    () => new Set(storedVisibility.hiddenProjectKeys)
  );

  useEffect(() => {
    setItem(
      VISIBILITY_KEY,
      JSON.stringify({
        hiddenCalendarKeys: [...hiddenCalendarKeys],
        hiddenProjectKeys: [...hiddenProjectKeys],
      })
    );
  }, [hiddenCalendarKeys, hiddenProjectKeys]);

  const userTimezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  // The span the current view renders — the window events + tasks fetch over.
  const visibleRange = useMemo(
    () => calendarVisibleRange(focusDate, calendarViewMode, weekStartsOn),
    [focusDate, calendarViewMode, weekStartsOn]
  );

  // Task filter conditions (same JSON shape GET /me/tasks accepts). The date
  // window travels as start_after/start_before on the request (see
  // entriesParams) — the cross-guild task path can only be windowed by those
  // params, not by conditions — so it isn't repeated here.
  const taskConditions = useMemo((): (FilterCondition | FilterGroup)[] => {
    const conditions: (FilterCondition | FilterGroup)[] = [];
    if (statusFilters.length > 0) {
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    }
    if (priorityFilters.length > 0) {
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    }
    if (guildFilters.length > 0) {
      conditions.push({ field: "guild_ids", op: "in_", value: guildFilters });
    }
    return conditions;
  }, [statusFilters, priorityFilters, guildFilters]);

  // --- One request: cross-guild events + assigned-task markers over the window. ---
  const entriesParams = useMemo((): ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams => {
    const params: ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams = {
      start_after: visibleRange.start.toISOString(),
      start_before: visibleRange.end.toISOString(),
      conditions: taskConditions,
      tz: userTimezone,
      include_events: true,
      include_tasks: true,
    };
    if (guildFilters.length > 0) {
      params.guild_ids = guildFilters;
    }
    return params;
  }, [visibleRange, taskConditions, userTimezone, guildFilters]);

  const entriesQuery = useMyCalendarEntries(entriesParams);

  // The user's visible calendars across guilds — the grouping panel's rows and
  // the color source for events without their own color.
  const calendarsQuery = useMyCalendars(
    guildFilters.length > 0 ? { guild_ids: guildFilters } : undefined
  );
  const calendars = useMemo(() => calendarsQuery.data?.items ?? [], [calendarsQuery.data]);
  const calendarsByKey = useMemo(() => {
    const map = new Map<string, (typeof calendars)[number]>();
    for (const calendar of calendars) map.set(`${calendar.guild_id}:${calendar.id}`, calendar);
    return map;
  }, [calendars]);

  const guildNamesById = useMemo(() => {
    const map = new Map<number, string>();
    for (const guild of guilds) map.set(guild.id, guild.name);
    return map;
  }, [guilds]);
  const multiGuild = guilds.length > 1;

  const handleRefresh = useCallback(async () => {
    await Promise.all([invalidateAllTasks(), invalidateAllCalendars()]);
  }, []);

  // One read-only virtual calendar per project with a task in the window.
  const projectCalendars = useMemo<ProjectTaskCalendar[]>(() => {
    const seen = new Map<string, ProjectTaskCalendar>();
    for (const task of entriesQuery.data?.tasks ?? []) {
      if (task.project_id == null || task.guild_id == null) continue;
      const key = `${task.guild_id}:${task.project_id}`;
      if (seen.has(key)) continue;
      const guildName = multiGuild ? guildNamesById.get(task.guild_id) : undefined;
      const baseName = task.project_name ?? `#${task.project_id}`;
      seen.set(key, {
        projectId: task.project_id,
        guildId: task.guild_id,
        name: guildName ? `${baseName} · ${guildName}` : baseName,
        color: getProjectColor(task.project_id),
      });
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [entriesQuery.data, guildNamesById, multiGuild]);

  // --- Merge tasks + events into calendar entries (visibility-filtered) ---
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    // Task entries. Reuse the shared builder so the start/due markers get the
    // same visual treatment as the other calendars, injecting guildId into
    // meta for cross-guild navigation. Not draggable here (My Calendar has no
    // reschedule handler).
    for (const task of entriesQuery.data?.tasks ?? []) {
      if (task.project_id != null && hiddenProjectKeys.has(`${task.guild_id}:${task.project_id}`)) {
        continue;
      }
      for (const entry of buildTaskCalendarEntries(task, getProjectColor(task.project_id), false)) {
        entries.push({
          ...entry,
          meta: { ...(entry.meta as Record<string, unknown>), guildId: task.guild_id },
        });
      }
    }

    for (const event of entriesQuery.data?.events ?? []) {
      const calendarKey = `${event.guild_id}:${event.calendar_id}`;
      if (hiddenCalendarKeys.has(calendarKey)) continue;
      const calendar = calendarsByKey.get(calendarKey);
      entries.push({
        id: `event-${event.guild_id}-${event.id}`,
        title: event.title,
        description: event.description,
        startAt: event.start_at,
        endAt: event.end_at,
        allDay: event.all_day,
        // Per-event color overrides the calendar's default, Google-style.
        color: event.color ?? calendar?.color ?? "#6366f1",
        attendees: (event.attendee_previews ?? []).map((att) => ({
          name: att.name,
          avatarUrl: att.avatar_url,
          avatarBase64: att.avatar_base64,
          userId: att.user_id,
        })),
        meta: { type: "event", eventId: event.id, guildId: event.guild_id },
      });
    }

    return entries;
  }, [entriesQuery.data, hiddenCalendarKeys, hiddenProjectKeys, calendarsByKey]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | { type: string; taskId?: number; eventId?: number; guildId?: number }
      | undefined;
    if (!meta) return;
    const scopedPath = (path: string) => (meta.guildId ? guildPath(meta.guildId, path) : gp(path));
    if (meta.type === "task" && meta.taskId) {
      void navigate({ to: scopedPath(`/tasks/${meta.taskId}`) });
    } else if (meta.type === "event" && meta.eventId) {
      void navigate({ to: scopedPath(`/calendar-events/${meta.eventId}`) });
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

  const isLoading = entriesQuery.isLoading && !entriesQuery.data;

  const handleExport = useCallback(async () => {
    try {
      const params: Record<string, string | number[]> = {};
      if (guildFilters.length > 0) {
        params.guild_ids = guildFilters;
      }
      const response = await apiClient.get("/me/calendar-events/export.ics", {
        params,
        responseType: "blob",
      });
      const url = URL.createObjectURL(response.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "events.ics";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      toast.error(t("calendars:export.exportError"));
    }
  }, [guildFilters, t]);

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-semibold text-3xl tracking-tight">{t("tasks:myCalendar.title")}</h1>
            <p className="text-muted-foreground">{t("tasks:myCalendar.subtitle")}</p>
          </div>
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-4 w-4" />
            {t("calendars:export.exportIcs")}
          </Button>
        </div>

        <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
          <div className="flex items-center justify-between sm:hidden">
            <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
              <Filter className="h-4 w-4" />
              {t("tasks:filters.heading")}
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 px-3">
                {filtersOpen ? t("tasks:filters.hide") : t("tasks:filters.show")}
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
                />
              </Button>
            </CollapsibleTrigger>
          </div>
          <CollapsibleContent forceMount className="data-[state=closed]:hidden">
            <div className="mt-2 flex flex-wrap items-end gap-4 rounded-md border border-muted bg-background/40 p-3 sm:mt-0">
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
                  {t("tasks:filters.filterByGuild")}
                </Label>
                <MultiSelect
                  selectedValues={guildFilters.map(String)}
                  options={guilds.map((guild) => ({
                    value: String(guild.id),
                    label: guild.name,
                  }))}
                  onChange={(values) => {
                    const numericValues = values.map(Number).filter(Number.isFinite);
                    setGuildFilters(numericValues);
                  }}
                  placeholder={t("tasks:filters.allGuilds")}
                  emptyMessage={t("tasks:filters.noGuilds")}
                />
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin" />
          </div>
        ) : (
          <div className="flex flex-col gap-4 lg:flex-row">
            {/* Grouping panel — the user's calendars across guilds plus one
                task calendar per project with tasks in the window. */}
            <aside className="shrink-0 lg:w-60">
              <CalendarListPanel
                calendars={calendars}
                projectCalendars={projectCalendars}
                isCalendarHidden={(calendar) =>
                  hiddenCalendarKeys.has(`${calendar.guild_id}:${calendar.id}`)
                }
                isProjectHidden={(project) =>
                  hiddenProjectKeys.has(`${project.guildId}:${project.projectId}`)
                }
                onToggleCalendar={(calendar) =>
                  setHiddenCalendarKeys((prev) =>
                    toggleInSet(prev, `${calendar.guild_id}:${calendar.id}`)
                  )
                }
                onToggleProject={(project) =>
                  setHiddenProjectKeys((prev) =>
                    toggleInSet(prev, `${project.guildId}:${project.projectId}`)
                  )
                }
                calendarLabel={(calendar) => {
                  const guildName = multiGuild ? guildNamesById.get(calendar.guild_id) : undefined;
                  return guildName ? `${calendar.name} · ${guildName}` : calendar.name;
                }}
                settingsPathFor={(calendar) =>
                  guildPath(calendar.guild_id, `/calendars/${calendar.id}/settings`)
                }
                canCreate={false}
                onCreate={() => {}}
              />
            </aside>
            <div className="min-w-0 flex-1">
              <CalendarView
                entries={calendarEntries}
                viewMode={calendarViewMode}
                onViewModeChange={setCalendarViewMode}
                focusDate={focusDate}
                onFocusDateChange={setFocusDate}
                onEntryClick={handleEntryClick}
                weekStartsOn={weekStartsOn}
              />
            </div>
          </div>
        )}
      </div>
    </PullToRefresh>
  );
};
