import { useNavigate } from "@tanstack/react-router";
import { CalendarDays, Loader2, Table2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllTasks } from "@/api/query-keys";
import {
  buildTaskCalendarEntries,
  CALENDAR_VIEW_MODE_KEY,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
} from "@/components/calendar";
import {
  ToolListToolbar,
  type ToolViewOption,
} from "@/components/initiativeTools/shared/ToolListToolbar";
import { PullToRefresh } from "@/components/PullToRefresh";
import { buildPropertyColumns, propertyColumnIds } from "@/components/properties/propertyColumns";
import { FocusSummary } from "@/components/tasks/FocusSummary";
import { GlobalTaskFilters } from "@/components/tasks/GlobalTaskFilters";
import { globalTaskColumns } from "@/components/tasks/globalTaskColumns";
import { DataTable } from "@/components/ui/data-table";
import { useAuth } from "@/hooks/useAuth";
import { useFocusSummary } from "@/hooks/useFocusSummary";
import { type MyTasksView, useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { useGuilds } from "@/hooks/useGuilds";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { usePersistedTableState } from "@/hooks/usePersistedTableState";
import { useProperties } from "@/hooks/useProperties";
import { useViewPreference } from "@/hooks/useViewPreference";
import { guildPath, useGuildPath } from "@/lib/guildUrl";
import { getProjectColor } from "@/lib/projectColor";
import { entityRefRoute, taskRoute } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

export type GlobalTasksPageProps = {
  /** Which cross-guild task list to render. */
  view: MyTasksView;
  /** Prefix for the `useGlobalTasksTable` filter/sort storage key. */
  storageKeyPrefix: string;
  /** Storage key for persisted column visibility. */
  columnsStorageKey: string;
  /** Whether the title column renders assignee avatars. */
  showAssignees?: boolean;
  /** i18n key prefix (in the `tasks` namespace) for the page's own strings. */
  i18nPrefix: "myTasks" | "createdTasks";
};

export const GlobalTasksPage = ({
  view,
  storageKeyPrefix,
  columnsStorageKey,
  showAssignees,
  i18nPrefix,
}: GlobalTasksPageProps) => {
  const { t } = useTranslation(["tasks", "dates", "common", "projects"]);

  const viewOptions: ToolViewOption<"table" | "calendar">[] = [
    { value: "table", label: t("projects:tasks.viewTable"), icon: Table2 },
    { value: "calendar", label: t("projects:tasks.viewCalendar"), icon: CalendarDays },
  ];
  const { guilds } = useGuilds();
  const { user } = useAuth();
  const gp = useGuildPath();
  const navigate = useNavigate();

  const [viewMode, setViewMode] = useState<"table" | "calendar">("table");
  const [calendarViewMode, setCalendarViewMode] = useViewPreference<CalendarViewMode>(
    CALENDAR_VIEW_MODE_KEY,
    "month"
  );
  const [calendarFocusDate, setCalendarFocusDate] = useState(() => new Date());
  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  const table = useGlobalTasksTable({ view, storageKeyPrefix });
  // Only the assigned view: a personal to-do list of work you did not take on
  // makes no sense on "tasks I created".
  const showFocus = view === "assigned";
  const focus = useFocusSummary({ enabled: showFocus });

  const handleRefresh = useCallback(async () => {
    await invalidateAllTasks();
  }, []);

  const { data: allPropertyDefinitions = [] } = useProperties();
  const propertyColumns = useMemo(
    () => buildPropertyColumns<TaskListRead>(allPropertyDefinitions, (row) => row.properties),
    [allPropertyDefinitions]
  );
  const propertyHiddenIds = useMemo(
    () => propertyColumnIds(allPropertyDefinitions),
    [allPropertyDefinitions]
  );
  const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
    columnsStorageKey,
    propertyHiddenIds
  );
  // Grouping is the reader's own arrangement, so it outlives the visit. Sorting
  // rides along with this list's other preferences (see useGlobalTasksTable),
  // which is why only the grouping half is kept here.
  const [tableState, { setGrouping }] = usePersistedTableState(
    `initiative-${storageKeyPrefix}-table`,
    { grouping: ["date group"] }
  );
  // Seed the two existing hidden-by-default columns from this page only on
  // first-ever render; after that, persisted state governs everything.
  const effectiveColumnVisibility = useMemo(() => {
    const next = { ...columnVisibility };
    if (!("date group" in next)) next["date group"] = false;
    if (!("guild" in next)) next["guild"] = false;
    return next;
  }, [columnVisibility]);

  const columns = useMemo(() => {
    const base = globalTaskColumns({
      activeGuildId: table.activeGuildId,
      isUpdatingTaskStatus: table.isUpdatingTaskStatus,
      changeTaskStatus: table.changeTaskStatus,
      changeTaskStatusById: table.changeTaskStatusById,
      fetchProjectStatuses: table.fetchProjectStatuses,
      projectStatusCache: table.projectStatusCache,
      t: t as TranslateFn,
      showAssignees,
      isPinned: showFocus ? focus.isPinned : undefined,
      togglePin: showFocus ? focus.togglePin : undefined,
    });
    if (propertyColumns.length === 0) return base;
    const tagsIdx = base.findIndex((c) => (c as { id?: string }).id === "tags");
    if (tagsIdx === -1) return [...base, ...propertyColumns];
    return [...base.slice(0, tagsIdx + 1), ...propertyColumns, ...base.slice(tagsIdx + 1)];
  }, [
    table.activeGuildId,
    table.isUpdatingTaskStatus,
    table.changeTaskStatus,
    table.changeTaskStatusById,
    table.fetchProjectStatuses,
    table.projectStatusCache,
    t,
    propertyColumns,
    showAssignees,
    showFocus,
    focus.isPinned,
    focus.togglePin,
  ]);

  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t(`${i18nPrefix}.groupByDate`) },
      { id: "guild", label: t(`${i18nPrefix}.groupByGuild`) },
    ],
    [t, i18nPrefix]
  );

  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];
    // Reuse the shared builder so start/due markers get the same visual
    // treatment as the other calendars, injecting guildId into meta for
    // cross-guild navigation. Not draggable here (no reschedule handler).
    table.displayTasks.forEach((task) => {
      for (const entry of buildTaskCalendarEntries(task, getProjectColor(task.project_id), false)) {
        entries.push({
          ...entry,
          meta: { ...(entry.meta as Record<string, unknown>), guildId: task.guild_id },
        });
      }
    });
    return entries;
  }, [table.displayTasks]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | { taskId?: number; projectId?: number; initiativeId?: number | null; guildId?: number }
      | undefined;
    if (!meta?.taskId) return;
    // A task's URL names its project and initiative. This page spans guilds, so
    // a row that didn't carry them resolves through `/go` instead of guessing.
    const path =
      meta.projectId != null && meta.initiativeId != null
        ? taskRoute(meta.initiativeId, meta.projectId, meta.taskId)
        : entityRefRoute("task", meta.taskId);
    void navigate({ to: meta.guildId ? guildPath(meta.guildId, path) : gp(path) });
  };

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-semibold text-3xl tracking-tight">{t(`${i18nPrefix}.title`)}</h1>
            <p className="text-muted-foreground">{t(`${i18nPrefix}.subtitle`)}</p>
          </div>
        </div>

        <ToolListToolbar
          filters={
            // The calendar view reads none of these task-table filters.
            viewMode === "table"
              ? {
                  open: table.filtersOpen,
                  onOpenChange: table.setFiltersOpen,
                  activeCount: table.activeFilterCount,
                }
              : undefined
          }
          view={{
            value: viewMode,
            onChange: setViewMode,
            options: viewOptions,
            label: t("common:toolbar.view"),
          }}
        />

        {showFocus ? (
          <FocusSummary
            focus={focus}
            activeGuildId={table.activeGuildId}
            changeTaskStatus={table.changeTaskStatus}
            isUpdatingTaskStatus={table.isUpdatingTaskStatus}
          />
        ) : null}

        {viewMode === "table" && (
          <>
            <GlobalTaskFilters
              onClear={table.clearFilters}
              activeCount={table.activeFilterCount}
              statusFilters={table.statusFilters}
              setStatusFilters={table.setStatusFilters}
              priorityFilters={table.priorityFilters}
              setPriorityFilters={table.setPriorityFilters}
              guildFilters={table.guildFilters}
              setGuildFilters={table.setGuildFilters}
              propertyFilters={table.propertyFilters}
              setPropertyFilters={table.setPropertyFilters}
              filtersOpen={table.filtersOpen}
              setFiltersOpen={table.setFiltersOpen}
              guilds={guilds}
            />

            <div className="relative">
              {table.isRefetching ? (
                <div className="absolute inset-0 z-10 flex items-start justify-center bg-background/60 pt-4">
                  <div className="flex items-center gap-2 rounded-md border border-border bg-background px-4 py-2 shadow-sm">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span className="text-muted-foreground text-sm">{t("updating")}</span>
                  </div>
                </div>
              ) : null}
              {/* The saved sort has to be in hand before the table mounts: it
                  seeds its headers once, so a table built on the defaults would
                  keep claiming them while the rows came back in the saved
                  order. The filters resolve from the same request. */}
              {table.isInitialLoad || !table.preferencesLoaded ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin" />
                </div>
              ) : table.hasError ? (
                <p className="py-8 text-center text-destructive text-sm">
                  {t(`${i18nPrefix}.loadError`)}
                </p>
              ) : (
                <DataTable
                  columns={columns}
                  data={table.displayTasks}
                  groupingOptions={groupingOptions}
                  columnVisibility={effectiveColumnVisibility}
                  onColumnVisibilityChange={setColumnVisibility}
                  onGroupingChange={setGrouping}
                  initialState={{
                    grouping: tableState.grouping,
                    expanded: true,
                  }}
                  initialSorting={table.initialSorting}
                  enableFilterInput
                  filterInputColumnKey="title"
                  filterInputPlaceholder={t("filters.filterPlaceholder")}
                  enablePagination
                  manualPagination
                  pageCount={table.totalPages}
                  rowCount={table.totalCount}
                  pageIndex={table.page - 1}
                  onPaginationChange={(pag) => {
                    if (pag.pageSize !== table.pageSize) {
                      table.setPageSize(pag.pageSize);
                      table.setPage(1);
                    } else {
                      table.setPage(pag.pageIndex + 1);
                    }
                  }}
                  onPrefetchPage={(pageIndex) => table.prefetchPage(pageIndex + 1)}
                  manualSorting
                  onSortingChange={table.handleSortingChange}
                  enableResetSorting
                  enableColumnVisibilityDropdown
                />
              )}
            </div>
          </>
        )}

        {viewMode === "calendar" && (
          <CalendarView
            entries={calendarEntries}
            viewMode={calendarViewMode}
            onViewModeChange={setCalendarViewMode}
            focusDate={calendarFocusDate}
            onFocusDateChange={setCalendarFocusDate}
            onEntryClick={handleEntryClick}
            weekStartsOn={weekStartsOn}
            isLoading={table.isInitialLoad}
          />
        )}
      </div>
    </PullToRefresh>
  );
};
