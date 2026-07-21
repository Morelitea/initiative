import { useNavigate } from "@tanstack/react-router";
import { ChevronDown, Download, Filter, Loader2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type {
  FilterCondition,
  FilterGroup,
  ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendarEvents, invalidateAllTasks } from "@/api/query-keys";
import {
  buildTaskCalendarEntries,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
  calendarVisibleRange,
} from "@/components/calendar";
import { PullToRefresh } from "@/components/PullToRefresh";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useAuth } from "@/hooks/useAuth";
import { useMyCalendarEntries } from "@/hooks/useCalendarEntries";
import { useGuilds } from "@/hooks/useGuilds";
import { useViewPreference } from "@/hooks/useViewPreference";
import { toast } from "@/lib/chesterToast";
import { guildPath, useGuildPath } from "@/lib/guildUrl";
import { getProjectColor } from "@/lib/projectColor";

const STORAGE_KEY = "initiative-my-calendar-prefs";

type StoredPrefs = {
  showEvents: boolean;
  showTasks: boolean;
  calendarViewMode: CalendarViewMode;
  statusFilters: TaskStatusCategory[];
  priorityFilters: TaskPriority[];
  guildFilters: number[];
};

const PREFS_DEFAULTS: StoredPrefs = {
  showEvents: true,
  showTasks: true,
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
    showEvents: typeof v.showEvents === "boolean" ? v.showEvents : PREFS_DEFAULTS.showEvents,
    showTasks: typeof v.showTasks === "boolean" ? v.showTasks : PREFS_DEFAULTS.showTasks,
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

const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];

const getDefaultFiltersVisibility = () =>
  typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches;

export const MyCalendarPage = () => {
  const { t } = useTranslation(["tasks", "calendarEvents", "common"]);
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
  const { calendarViewMode, showEvents, showTasks } = storedPrefs;
  const setCalendarViewMode = useCallback(
    (next: CalendarViewMode) =>
      setStoredPrefs((prev) => ({ ...sanitizeStoredPrefs(prev), calendarViewMode: next })),
    [setStoredPrefs]
  );
  const setShowEvents = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) =>
      setStoredPrefs((prev) => {
        const safe = sanitizeStoredPrefs(prev);
        return {
          ...safe,
          showEvents: typeof next === "function" ? next(safe.showEvents) : next,
        };
      }),
    [setStoredPrefs]
  );
  const setShowTasks = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) =>
      setStoredPrefs((prev) => {
        const safe = sanitizeStoredPrefs(prev);
        return {
          ...safe,
          showTasks: typeof next === "function" ? next(safe.showTasks) : next,
        };
      }),
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

  const userTimezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  // The span the current view renders — the window events + tasks fetch over.
  const visibleRange = useMemo(
    () => calendarVisibleRange(focusDate, calendarViewMode, weekStartsOn),
    [focusDate, calendarViewMode, weekStartsOn]
  );

  // Task filter conditions (same JSON shape GET /me/tasks accepts). Placed by
  // start_date or due_date within the window; narrowed by the calendar filters.
  const taskConditions = useMemo((): (FilterCondition | FilterGroup)[] => {
    const conditions: (FilterCondition | FilterGroup)[] = [];
    conditions.push({
      logic: "or",
      conditions: (["start_date", "due_date"] as const).map((field) => ({
        logic: "and" as const,
        conditions: [
          { field, op: "gte", value: visibleRange.start.toISOString() },
          { field, op: "lte", value: visibleRange.end.toISOString() },
        ],
      })),
    });
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
  }, [visibleRange, statusFilters, priorityFilters, guildFilters]);

  // --- One request: cross-guild events + assigned-task markers over the window. ---
  const entriesParams = useMemo((): ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams => {
    const params: ListMyCalendarEntriesApiV1MeCalendarEntriesGetParams = {
      start_after: visibleRange.start.toISOString(),
      start_before: visibleRange.end.toISOString(),
      conditions: taskConditions,
      tz: userTimezone,
      include_events: showEvents,
      include_tasks: showTasks,
    };
    if (guildFilters.length > 0) {
      params.guild_ids = guildFilters;
    }
    return params;
  }, [visibleRange, taskConditions, userTimezone, showEvents, showTasks, guildFilters]);

  const entriesQuery = useMyCalendarEntries(entriesParams);

  const handleRefresh = useCallback(async () => {
    await Promise.all([invalidateAllTasks(), invalidateAllCalendarEvents()]);
  }, []);

  // --- Merge tasks + events into calendar entries ---
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    // Task entries (only if showTasks is true). Reuse the shared builder so the
    // start/due markers get the same visual treatment as the other calendars,
    // injecting guildId into meta for cross-guild navigation. Not draggable here
    // (My Calendar has no reschedule handler).
    if (showTasks) {
      (entriesQuery.data?.tasks ?? []).forEach((task) => {
        for (const entry of buildTaskCalendarEntries(
          task,
          getProjectColor(task.project_id),
          false
        )) {
          entries.push({
            ...entry,
            meta: { ...(entry.meta as Record<string, unknown>), guildId: task.guild_id },
          });
        }
      });
    }

    // Event entries (only if showEvents is true, since events have no task status)
    if (showEvents) {
      const events = entriesQuery.data?.events ?? [];
      events.forEach((event) => {
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
          meta: { type: "event", eventId: event.id, guildId: event.guild_id },
        });
      });
    }

    return entries;
  }, [entriesQuery.data, showEvents, showTasks]);

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
      toast.error(t("calendarEvents:export.exportError"));
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
            {t("calendarEvents:export.exportIcs")}
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
                  options={priorityOrder.map((p) => ({
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
              <div className="flex items-end gap-2">
                <Button
                  variant={showTasks ? "default" : "outline"}
                  size="sm"
                  onClick={() => setShowTasks(!showTasks)}
                  title={t("tasks:myCalendar.typeTasks")}
                >
                  {t("tasks:myCalendar.typeTasks")}
                </Button>
                <Button
                  variant={showEvents ? "default" : "outline"}
                  size="sm"
                  onClick={() => setShowEvents(!showEvents)}
                  title={t("tasks:myCalendar.typeEvents")}
                >
                  {t("tasks:myCalendar.typeEvents")}
                </Button>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin" />
          </div>
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
