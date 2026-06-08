import { useNavigate } from "@tanstack/react-router";
import { addYears, endOfYear, startOfYear, subYears } from "date-fns";
import { ChevronDown, Download, Filter, Loader2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type {
  ListGlobalCalendarEventsApiV1CalendarEventsGlobalGetParams,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCalendarEvents, invalidateAllTasks } from "@/api/query-keys";
import {
  buildTaskCalendarEntries,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
} from "@/components/calendar";
import { PullToRefresh } from "@/components/PullToRefresh";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useAuth } from "@/hooks/useAuth";
import { useGlobalCalendarEventsList } from "@/hooks/useCalendarEvents";
import { useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
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
};

const PREFS_DEFAULTS: StoredPrefs = {
  showEvents: true,
  showTasks: true,
  calendarViewMode: "month",
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
  };
};

const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];

export const MyCalendarPage = () => {
  const { t } = useTranslation(["tasks", "events", "common"]);
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
  const [focusDate, setFocusDate] = useState(() => new Date());

  // Use the same hook as My Tasks for task data + filters
  const table = useGlobalTasksTable({ scope: "global", storageKeyPrefix: "my-calendar-tasks" });

  // --- Events query (global cross-guild) ---
  const eventsParams = useMemo((): ListGlobalCalendarEventsApiV1CalendarEventsGlobalGetParams => {
    const params: ListGlobalCalendarEventsApiV1CalendarEventsGlobalGetParams = {
      start_after: startOfYear(subYears(focusDate, 1)).toISOString(),
      start_before: endOfYear(addYears(focusDate, 1)).toISOString(),
      page: 1,
      page_size: 200,
    };
    if (table.guildFilters.length > 0) {
      params.guild_ids = table.guildFilters;
    }
    return params;
  }, [focusDate, table.guildFilters]);

  const eventsQuery = useGlobalCalendarEventsList(eventsParams);

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
      table.displayTasks.forEach((task) => {
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
      const events = eventsQuery.data?.items ?? [];
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
  }, [table.displayTasks, eventsQuery.data, showEvents, showTasks]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | { type: string; taskId?: number; eventId?: number; guildId?: number }
      | undefined;
    if (!meta) return;
    const scopedPath = (path: string) => (meta.guildId ? guildPath(meta.guildId, path) : gp(path));
    if (meta.type === "task" && meta.taskId) {
      void navigate({ to: scopedPath(`/tasks/${meta.taskId}`) });
    } else if (meta.type === "event" && meta.eventId) {
      void navigate({ to: scopedPath(`/events/${meta.eventId}`) });
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

  const isLoading = table.isInitialLoad || (eventsQuery.isLoading && !eventsQuery.data);

  const handleExport = useCallback(async () => {
    try {
      const params: Record<string, string | number[]> = {};
      if (table.guildFilters.length > 0) {
        params.guild_ids = table.guildFilters;
      }
      const response = await apiClient.get("/api/v1/calendar-events/global/export.ics", {
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
      toast.error(t("events:export.exportError"));
    }
  }, [table.guildFilters, t]);

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-semibold text-3xl tracking-tight">{t("tasks:myCalendar.title")}</h1>
            <p className="text-muted-foreground">{t("tasks:myCalendar.subtitle")}</p>
          </div>
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="mr-1.5 h-4 w-4" />
            {t("events:export.exportIcs")}
          </Button>
        </div>

        <Collapsible
          open={table.filtersOpen}
          onOpenChange={table.setFiltersOpen}
          className="space-y-2"
        >
          <div className="flex items-center justify-between sm:hidden">
            <div className="inline-flex items-center gap-2 font-medium text-muted-foreground text-sm">
              <Filter className="h-4 w-4" />
              {t("tasks:filters.heading")}
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 px-3">
                {table.filtersOpen ? t("tasks:filters.hide") : t("tasks:filters.show")}
                <ChevronDown
                  className={`ml-1 h-4 w-4 transition-transform ${table.filtersOpen ? "rotate-180" : ""}`}
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
                  selectedValues={table.statusFilters}
                  options={statusOptions.map((o) => ({ value: o.value, label: o.label }))}
                  onChange={(values) => table.setStatusFilters(values as TaskStatusCategory[])}
                  placeholder={t("tasks:filters.allStatusCategories")}
                  emptyMessage={t("tasks:filters.noStatusCategories")}
                />
              </div>
              <div className="w-full sm:w-48 lg:flex-1">
                <Label className="mb-2 block font-medium text-muted-foreground text-xs">
                  {t("tasks:filters.filterByPriority")}
                </Label>
                <MultiSelect
                  selectedValues={table.priorityFilters}
                  options={priorityOrder.map((p) => ({
                    value: p,
                    label: t(`tasks:priority.${p}` as never),
                  }))}
                  onChange={(values) => table.setPriorityFilters(values as TaskPriority[])}
                  placeholder={t("tasks:filters.allPriorities")}
                  emptyMessage={t("tasks:filters.noPriorities")}
                />
              </div>
              <div className="w-full sm:w-48 lg:flex-1">
                <Label className="mb-2 block font-medium text-muted-foreground text-xs">
                  {t("tasks:filters.filterByGuild")}
                </Label>
                <MultiSelect
                  selectedValues={table.guildFilters.map(String)}
                  options={guilds.map((guild) => ({
                    value: String(guild.id),
                    label: guild.name,
                  }))}
                  onChange={(values) => {
                    const numericValues = values.map(Number).filter(Number.isFinite);
                    table.setGuildFilters(numericValues);
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
