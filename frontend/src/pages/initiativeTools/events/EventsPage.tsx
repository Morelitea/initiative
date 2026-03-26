import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { format } from "date-fns";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CalendarView, type CalendarEntry, type CalendarViewMode } from "@/components/calendar";
import { useCalendarEventsList } from "@/hooks/useCalendarEvents";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useMyInitiativePermissions,
  canCreate as canCreatePermission,
} from "@/hooks/useInitiativeRoles";
import { CreateEventDialog } from "@/components/initiativeTools/events/CreateEventDialog";
import { EventsFilterBar } from "@/components/initiativeTools/events/EventsFilterBar";

const INITIATIVE_FILTER_ALL = "all";

type EventsViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const EventsView = ({ fixedInitiativeId, canCreate }: EventsViewProps) => {
  const { t } = useTranslation(["events", "common"]);
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

  // Fetch events (large page to cover the visible range)
  const eventsQuery = useCalendarEventsList({
    ...(initiativeFilter !== INITIATIVE_FILTER_ALL
      ? { initiative_id: Number(initiativeFilter) }
      : {}),
    page: 1,
    page_size: 200,
  });

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

  // Map API events to CalendarEntry[]
  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const items = eventsQuery.data?.items ?? [];
    return items.map((event) => ({
      id: event.id,
      title: event.title,
      description: event.description,
      startAt: event.start_at,
      endAt: event.end_at,
      allDay: event.all_day,
      color: event.color ?? undefined,
      attendees: (event.attendee_names ?? []).map((name) => ({ name })),
    }));
  }, [eventsQuery.data]);

  // Create dialog state
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createDefaultDate, setCreateDefaultDate] = useState<Date | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(() =>
    typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches
  );

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
    void router.navigate({ to: gp(`/events/${entry.id}`) });
  };

  // Filter entries by search query client-side
  const filteredEntries = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return calendarEntries;
    return calendarEntries.filter((e) => e.title.toLowerCase().includes(query));
  }, [calendarEntries, searchQuery]);

  const lockedInitiativeName = lockedInitiativeId
    ? (initiatives.find((i) => i.id === lockedInitiativeId)?.name ?? null)
    : null;

  const defaultStartDate = createDefaultDate
    ? format(createDefaultDate, "yyyy-MM-dd")
    : undefined;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
      </div>

      <EventsFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        initiativeFilter={initiativeFilter}
        onInitiativeFilterChange={setInitiativeFilter}
        lockedInitiativeId={lockedInitiativeId}
        lockedInitiativeName={lockedInitiativeName}
        initiatives={initiatives}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
      />

      {eventsQuery.isLoading ? (
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
    </div>
  );
};

export function EventsPage() {
  return <EventsView />;
}
