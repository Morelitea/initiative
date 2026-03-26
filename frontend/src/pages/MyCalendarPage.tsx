import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "@tanstack/react-router";
import { addYears, endOfYear, startOfYear, subYears } from "date-fns";
import { ChevronDown, Filter, Loader2 } from "lucide-react";

import { invalidateAllTasks, invalidateAllCalendarEvents } from "@/api/query-keys";
import type {
  ListGlobalCalendarEventsApiV1CalendarEventsGlobalGetParams,
  TaskPriority,
  TaskStatusCategory,
} from "@/api/generated/initiativeAPI.schemas";
import { useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { useGlobalCalendarEventsList } from "@/hooks/useCalendarEvents";
import { CalendarView, type CalendarEntry, type CalendarViewMode } from "@/components/calendar";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { PullToRefresh } from "@/components/PullToRefresh";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useGuildPath } from "@/lib/guildUrl";
import { getItem, setItem } from "@/lib/storage";

const STORAGE_KEY = "initiative-my-calendar-prefs";

const PREFS_DEFAULTS = {
  showEvents: true,
  calendarViewMode: "month" as CalendarViewMode,
};

const readStoredPrefs = () => {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return PREFS_DEFAULTS;
    const parsed = JSON.parse(raw);
    return {
      showEvents:
        typeof parsed?.showEvents === "boolean" ? parsed.showEvents : PREFS_DEFAULTS.showEvents,
      calendarViewMode:
        typeof parsed?.calendarViewMode === "string"
          ? (parsed.calendarViewMode as CalendarViewMode)
          : PREFS_DEFAULTS.calendarViewMode,
    };
  } catch {
    return PREFS_DEFAULTS;
  }
};

const priorityOrder: TaskPriority[] = ["low", "medium", "high", "urgent"];

export const MyCalendarPage = () => {
  const { t } = useTranslation(["tasks", "events", "common"]);
  const { guilds } = useGuilds();
  const { user } = useAuth();
  const gp = useGuildPath();
  const navigate = useNavigate();

  const storedPrefs = useMemo(() => readStoredPrefs(), []);

  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  // Calendar-specific state
  const [calendarViewMode, setCalendarViewMode] = useState<CalendarViewMode>(
    () => storedPrefs.calendarViewMode
  );
  const [focusDate, setFocusDate] = useState(() => new Date());
  const [showEvents, setShowEvents] = useState(() => storedPrefs.showEvents);

  // Use the same hook as My Tasks for task data + filters
  const table = useGlobalTasksTable({ scope: "global", storageKeyPrefix: "my-calendar-tasks" });

  // Persist calendar-specific preferences
  useEffect(() => {
    const payload = {
      showEvents,
      calendarViewMode,
    };
    setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [showEvents, calendarViewMode]);

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

    // Task entries
    table.displayTasks.forEach((task) => {
      const taskAttendees = task.assignees
        .filter((a) => a.full_name)
        .map((a) => ({ name: a.full_name!, avatarUrl: a.avatar_url }));

      if (task.due_date) {
        entries.push({
          id: `task-${task.id}-due`,
          title: task.title,
          startAt: task.due_date,
          endAt: task.due_date,
          allDay: true,
          attendees: taskAttendees,
          meta: { type: "task", taskId: task.id, guildId: task.guild_id },
        });
      }
      if (task.start_date) {
        entries.push({
          id: `task-${task.id}-start`,
          title: task.title,
          startAt: task.start_date,
          endAt: task.start_date,
          allDay: true,
          color: "#10b981",
          attendees: taskAttendees,
          meta: { type: "task", taskId: task.id, guildId: task.guild_id },
        });
      }
    });

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
          attendees: (event.attendee_names ?? []).map((name) => ({ name })),
          meta: { type: "event", eventId: event.id, guildId: event.guild_id },
        });
      });
    }

    return entries;
  }, [table.displayTasks, eventsQuery.data, showEvents]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | { type: string; taskId?: number; eventId?: number; guildId?: number }
      | undefined;
    if (!meta) return;
    if (meta.type === "task" && meta.taskId) {
      void navigate({ to: gp(`/tasks/${meta.taskId}`) });
    } else if (meta.type === "event" && meta.eventId) {
      void navigate({ to: gp(`/events/${meta.eventId}`) });
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

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("tasks:myCalendar.title")}</h1>
          <p className="text-muted-foreground">{t("tasks:myCalendar.subtitle")}</p>
        </div>

        <Collapsible
          open={table.filtersOpen}
          onOpenChange={table.setFiltersOpen}
          className="space-y-2"
        >
          <div className="flex items-center justify-between sm:hidden">
            <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
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
            <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
              <div className="w-full sm:w-48 lg:flex-1">
                <Label className="text-muted-foreground mb-2 block text-xs font-medium">
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
                <Label className="text-muted-foreground mb-2 block text-xs font-medium">
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
                <Label className="text-muted-foreground mb-2 block text-xs font-medium">
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
              <div className="flex items-end">
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
