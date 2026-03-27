import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { addYears, endOfYear, format, startOfYear, subYears } from "date-fns";
import { ChevronDown, Download, Filter, Loader2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { keepPreviousData } from "@tanstack/react-query";

import { CalendarView, type CalendarEntry, type CalendarViewMode } from "@/components/calendar";
import { useCalendarEventsList } from "@/hooks/useCalendarEvents";
import { useTasks } from "@/hooks/useTasks";
import type {
  TaskStatusCategory,
  TaskPriority,
  FilterCondition,
  ListTasksApiV1TasksGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useMyInitiativePermissions,
  canCreate as canCreatePermission,
} from "@/hooks/useInitiativeRoles";
import { apiClient } from "@/api/client";
import { getItem, setItem } from "@/lib/storage";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { CreateEventDialog } from "@/components/initiativeTools/events/CreateEventDialog";
import { ICalImportDialog } from "@/components/initiativeTools/events/ICalImportDialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const INITIATIVE_FILTER_ALL = "all";
const STORAGE_KEY = "initiative-events-prefs";

const STATUS_CATEGORIES: TaskStatusCategory[] = ["backlog", "todo", "in_progress", "done"];
const PRIORITY_ORDER: TaskPriority[] = ["low", "medium", "high", "urgent"];

interface StoredPrefs {
  showEvents: boolean;
  showTasks: boolean;
  statusFilters: TaskStatusCategory[];
  priorityFilters: TaskPriority[];
}

const PREFS_DEFAULTS: StoredPrefs = {
  showEvents: true,
  showTasks: true,
  statusFilters: ["backlog", "todo", "in_progress"],
  priorityFilters: [],
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
  const { t } = useTranslation(["events", "tasks", "common"]);
  const router = useRouter();
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as {
    initiativeId?: string;
    create?: string;
  };

  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;
  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    lockedInitiativeId ? String(lockedInitiativeId) : INITIATIVE_FILTER_ALL
  );
  const filteredInitiativeId =
    initiativeFilter !== INITIATIVE_FILTER_ALL ? Number(initiativeFilter) : null;

  const { data: filteredInitiativePermissions } = useMyInitiativePermissions(
    !lockedInitiativeId && filteredInitiativeId ? filteredInitiativeId : null
  );

  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;
  const lastConsumedParams = useRef<string>("");
  const prevGuildIdRef = useRef<number | null>(activeGuildId);
  const isClosingCreateDialog = useRef(false);

  // Calendar state
  const [viewMode, setViewMode] = useState<CalendarViewMode>("month");
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
  const [filtersOpen, setFiltersOpen] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches
  );
  const [searchQuery] = useState("");

  // Persist preferences
  useEffect(() => {
    setItem(STORAGE_KEY, JSON.stringify({ showEvents, showTasks, statusFilters, priorityFilters }));
  }, [showEvents, showTasks, statusFilters, priorityFilters]);

  // Consume ?initiativeId from URL once
  useEffect(() => {
    const urlInitiativeId = searchParams.initiativeId;
    const paramKey = urlInitiativeId || "";
    if (urlInitiativeId && !lockedInitiativeId && paramKey !== lastConsumedParams.current) {
      lastConsumedParams.current = paramKey;
      setInitiativeFilter(urlInitiativeId);
    }
  }, [searchParams, lockedInitiativeId]);

  useEffect(() => {
    if (lockedInitiativeId) {
      const lockedValue = String(lockedInitiativeId);
      setInitiativeFilter((prev) => (prev === lockedValue ? prev : lockedValue));
    }
  }, [lockedInitiativeId]);

  useEffect(() => {
    const prevGuildId = prevGuildIdRef.current;
    prevGuildIdRef.current = activeGuildId;
    if (prevGuildId !== null && prevGuildId !== activeGuildId && !lockedInitiativeId) {
      setInitiativeFilter(INITIATIVE_FILTER_ALL);
      lastConsumedParams.current = "";
    }
  }, [activeGuildId, lockedInitiativeId]);

  // --- Events query ---
  const eventsQuery = useCalendarEventsList({
    ...(initiativeFilter !== INITIATIVE_FILTER_ALL
      ? { initiative_id: Number(initiativeFilter) }
      : {}),
    start_after: startOfYear(subYears(focusDate, 1)).toISOString(),
    start_before: endOfYear(addYears(focusDate, 1)).toISOString(),
    page: 1,
    page_size: 200,
  });

  // --- Tasks query (initiative-scoped) ---
  const userTimezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  const activeInitiativeId = filteredInitiativeId ?? lockedInitiativeId;

  const tasksParams = useMemo((): ListTasksApiV1TasksGetParams | null => {
    if (!showTasks || !activeInitiativeId) return null;
    const conditions: FilterCondition[] = [
      { field: "initiative_ids", op: "in_", value: [activeInitiativeId] },
    ];
    if (statusFilters.length > 0) {
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    }
    if (priorityFilters.length > 0) {
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    }
    return {
      conditions,
      page: 1,
      page_size: 200,
      tz: userTimezone,
    };
  }, [showTasks, activeInitiativeId, statusFilters, priorityFilters, userTimezone]);

  const defaultTaskParams: ListTasksApiV1TasksGetParams = { page: 1, page_size: 0 };
  const tasksQuery = useTasks(tasksParams ?? defaultTaskParams, {
    enabled: !!tasksParams,
    placeholderData: keepPreviousData,
  });

  // --- Initiatives ---
  const initiativesQuery = useInitiatives();
  const initiatives = useMemo(
    () => (initiativesQuery.data ?? []).filter((init) => init.events_enabled),
    [initiativesQuery.data]
  );

  const creatableInitiatives = useMemo(() => {
    if (!user) return [];
    return initiatives.filter((initiative) =>
      initiative.members.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      )
    );
  }, [initiatives, user]);

  const canCreateEvents = useMemo(() => {
    if (canCreate !== undefined) return canCreate;
    if (filteredInitiativeId && filteredInitiativePermissions) {
      return canCreatePermission(filteredInitiativePermissions, "events");
    }
    if (lockedInitiativeId) {
      return creatableInitiatives.some((initiative) => initiative.id === lockedInitiativeId);
    }
    return creatableInitiatives.length > 0;
  }, [
    canCreate,
    filteredInitiativeId,
    filteredInitiativePermissions,
    lockedInitiativeId,
    creatableInitiatives,
  ]);

  const createInitiativeId = useMemo(() => {
    if (lockedInitiativeId) return lockedInitiativeId;
    if (filteredInitiativeId) return filteredInitiativeId;
    return initiatives.length > 0 ? initiatives[0].id : null;
  }, [lockedInitiativeId, filteredInitiativeId, initiatives]);

  // --- Merge events + tasks into calendar entries ---
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];

    // Events
    if (showEvents) {
      const items = eventsQuery.data?.items ?? [];
      items.forEach((event) => {
        entries.push({
          id: `event-${event.id}`,
          title: event.title,
          description: event.description,
          startAt: event.start_at,
          endAt: event.end_at,
          allDay: event.all_day,
          color: event.color ?? "#6366f1",
          attendees: (event.attendee_names ?? []).map((name) => ({ name })),
          meta: { type: "event", eventId: event.id },
        });
      });
    }

    // Tasks
    if (showTasks) {
      const tasks = tasksQuery.data?.items ?? [];
      tasks.forEach((task) => {
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
            meta: { type: "task", taskId: task.id },
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
            meta: { type: "task", taskId: task.id },
          });
        }
      });
    }

    return entries;
  }, [showEvents, showTasks, eventsQuery.data, tasksQuery.data]);

  // Create dialog state
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [createDefaultDate, setCreateDefaultDate] = useState<Date | null>(null);

  useEffect(() => {
    const shouldCreate = searchParams.create === "true";
    if (shouldCreate && !createDialogOpen && !isClosingCreateDialog.current) {
      setCreateDialogOpen(true);
    }
    if (!shouldCreate) {
      isClosingCreateDialog.current = false;
    }
  }, [searchParams, createDialogOpen]);

  const handleCreateDialogOpenChange = (open: boolean) => {
    setCreateDialogOpen(open);
    if (!open) {
      setCreateDefaultDate(null);
      if (searchParams.create) {
        isClosingCreateDialog.current = true;
        void router.navigate({
          to: gp("/events"),
          search: { initiativeId: searchParams.initiativeId },
          replace: true,
        });
      }
    }
  };

  const handleEventCreated = (event: { id: number }) => {
    void router.navigate({ to: gp(`/events/${event.id}`) });
  };

  const handleSlotClick = (date: Date) => {
    if (!canCreateEvents || !createInitiativeId) return;
    setCreateDefaultDate(date);
    setCreateDialogOpen(true);
  };

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as { type: string; taskId?: number; eventId?: number } | undefined;
    if (!meta) return;
    if (meta.type === "event" && meta.eventId) {
      void router.navigate({ to: gp(`/events/${meta.eventId}`) });
    } else if (meta.type === "task" && meta.taskId) {
      void router.navigate({ to: gp(`/tasks/${meta.taskId}`) });
    }
  };

  // Filter entries by search query client-side
  const filteredEntries = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return calendarEntries;
    return calendarEntries.filter((e) => e.title.toLowerCase().includes(query));
  }, [calendarEntries, searchQuery]);

  const defaultStartDate = createDefaultDate ? format(createDefaultDate, "yyyy-MM-dd") : undefined;

  const handleExport = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (filteredInitiativeId) {
        params.initiative_id = String(filteredInitiativeId);
      }
      const response = await apiClient.get("/api/v1/calendar-events/export.ics", {
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
      toast.error(t("export.exportError"));
    }
  }, [filteredInitiativeId, t]);

  // Status/priority filter options
  const statusOptions = useMemo(
    () =>
      STATUS_CATEGORIES.map((cat) => ({
        value: cat,
        label: t(`tasks:statusCategory.${cat}`),
      })),
    [t]
  );

  const isLoading = eventsQuery.isLoading && !eventsQuery.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="mr-1.5 h-4 w-4" />
            {t("export.exportIcs")}
          </Button>
          {canCreateEvents && (
            <Button variant="outline" size="sm" onClick={() => setImportDialogOpen(true)}>
              <Upload className="mr-1.5 h-4 w-4" />
              {t("import.importIcs")}
            </Button>
          )}
        </div>
      </div>

      {/* Filters */}
      <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
        <div className="flex items-center justify-between sm:hidden">
          <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
            <Filter className="h-4 w-4" />
            {t("filters.heading")}
          </div>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-8 px-3">
              {filtersOpen ? t("filters.hide") : t("filters.show")}
              <ChevronDown
                className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
              />
            </Button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
            {/* Initiative filter (when not locked) */}
            {!lockedInitiativeId && initiatives.length > 1 && (
              <div className="w-full space-y-2 sm:w-48">
                <Label className="text-muted-foreground block text-xs font-medium">
                  {t("filters.filterByInitiative")}
                </Label>
                <Select value={initiativeFilter} onValueChange={setInitiativeFilter}>
                  <SelectTrigger>
                    <SelectValue placeholder={t("filters.allInitiatives")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={INITIATIVE_FILTER_ALL}>
                      {t("filters.allInitiatives")}
                    </SelectItem>
                    {initiatives.map((init) => (
                      <SelectItem key={init.id} value={String(init.id)}>
                        {init.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Status filter (for tasks) */}
            {showTasks && (
              <div className="w-full sm:w-48 lg:flex-1">
                <Label className="text-muted-foreground mb-2 block text-xs font-medium">
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
                <Label className="text-muted-foreground mb-2 block text-xs font-medium">
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

            {/* Type toggles */}
            <div className="flex items-end gap-2">
              <Button
                variant={showEvents ? "default" : "outline"}
                size="sm"
                onClick={() => setShowEvents(!showEvents)}
              >
                {t("events:event")}
              </Button>
              <Button
                variant={showTasks ? "default" : "outline"}
                size="sm"
                onClick={() => setShowTasks(!showTasks)}
              >
                {t("tasks:myCalendar.typeTasks" as never)}
              </Button>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      {isLoading ? (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : (
        <CalendarView
          entries={filteredEntries}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          focusDate={focusDate}
          onFocusDateChange={setFocusDate}
          onEntryClick={handleEntryClick}
          onSlotClick={canCreateEvents ? handleSlotClick : undefined}
          weekStartsOn={weekStartsOn}
        />
      )}

      {createInitiativeId && (
        <CreateEventDialog
          open={createDialogOpen}
          onOpenChange={handleCreateDialogOpenChange}
          initiativeId={createInitiativeId}
          defaultStartDate={defaultStartDate}
          onSuccess={handleEventCreated}
        />
      )}

      <ICalImportDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        fixedInitiativeId={filteredInitiativeId ?? undefined}
      />
    </div>
  );
};

export function EventsPage() {
  return <EventsView />;
}
