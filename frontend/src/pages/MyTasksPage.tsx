import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { useNavigate } from "@tanstack/react-router";

import { invalidateAllTasks } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { useProperties } from "@/hooks/useProperties";
import { usePersistedColumnVisibility } from "@/hooks/usePersistedColumnVisibility";
import { PropertyAppliesTo, type TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { buildPropertyColumns, propertyColumnId } from "@/components/properties/propertyColumns";
import { globalTaskColumns } from "@/components/tasks/globalTaskColumns";
import { GlobalTaskFilters } from "@/components/tasks/GlobalTaskFilters";
import { CalendarView, type CalendarEntry, type CalendarViewMode } from "@/components/calendar";
import { DataTable } from "@/components/ui/data-table";
import { Button } from "@/components/ui/button";
import { PullToRefresh } from "@/components/PullToRefresh";
import { CalendarDays, Plus, Table2 } from "lucide-react";
import { getOpenCreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import { guildPath, useGuildPath } from "@/lib/guildUrl";
import type { TranslateFn } from "@/types/i18n";

export const MyTasksPage = () => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { guilds } = useGuilds();
  const { user } = useAuth();
  const gp = useGuildPath();
  const navigate = useNavigate();

  const [viewMode, setViewMode] = useState<"table" | "calendar">("table");
  const [calendarViewMode, setCalendarViewMode] = useState<CalendarViewMode>("month");
  const [calendarFocusDate, setCalendarFocusDate] = useState(() => new Date());
  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  const table = useGlobalTasksTable({ scope: "global", storageKeyPrefix: "my-tasks" });

  const handleRefresh = useCallback(async () => {
    await invalidateAllTasks();
  }, []);

  const { data: allPropertyDefinitions = [] } = useProperties();
  const taskPropertyDefinitions = useMemo(
    () =>
      allPropertyDefinitions.filter(
        (definition) =>
          definition.applies_to === PropertyAppliesTo.task ||
          definition.applies_to === PropertyAppliesTo.both
      ),
    [allPropertyDefinitions]
  );
  const propertyColumns = useMemo(
    () => buildPropertyColumns<TaskListRead>(taskPropertyDefinitions, (row) => row.properties),
    [taskPropertyDefinitions]
  );
  const propertyHiddenIds = useMemo(
    () => taskPropertyDefinitions.map((definition) => propertyColumnId(definition)),
    [taskPropertyDefinitions]
  );
  const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
    "initiative-my-tasks-columns",
    propertyHiddenIds
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
      projectsById: table.projectsById,
      t: t as TranslateFn,
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
    table.projectsById,
    t,
    propertyColumns,
  ]);

  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("myTasks.groupByDate") },
      { id: "guild", label: t("myTasks.groupByGuild") },
    ],
    [t]
  );

  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];
    table.displayTasks.forEach((task) => {
      const taskAttendees = task.assignees
        .filter((a) => a.full_name)
        .map((a) => ({ name: a.full_name!, avatarUrl: a.avatar_url }));

      if (task.due_date) {
        entries.push({
          id: `${task.id}-due`,
          title: task.title,
          startAt: task.due_date,
          endAt: task.due_date,
          allDay: true,
          attendees: taskAttendees,
          meta: { guildId: task.guild_id },
        });
      }
      if (task.start_date) {
        entries.push({
          id: `${task.id}-start`,
          title: task.title,
          startAt: task.start_date,
          endAt: task.start_date,
          allDay: true,
          color: "#10b981",
          attendees: taskAttendees,
          meta: { guildId: task.guild_id },
        });
      }
    });
    return entries;
  }, [table.displayTasks]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const taskId = Number(String(entry.id).split("-")[0]);
    if (!taskId) return;
    const meta = entry.meta as { guildId?: number } | undefined;
    const path = `/tasks/${taskId}`;
    void navigate({ to: meta?.guildId ? guildPath(meta.guildId, path) : gp(path) });
  };

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{t("myTasks.title")}</h1>
            <p className="text-muted-foreground">{t("myTasks.subtitle")}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => getOpenCreateTaskWizard()?.()}>
              <Plus className="mr-1 h-4 w-4" />
              {t("myTasks.addTask")}
            </Button>
            <div className="flex items-center gap-1 rounded-lg border p-1">
              <Button
                variant={viewMode === "table" ? "default" : "ghost"}
                size="sm"
                onClick={() => setViewMode("table")}
              >
                <Table2 className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === "calendar" ? "default" : "ghost"}
                size="sm"
                onClick={() => setViewMode("calendar")}
              >
                <CalendarDays className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {viewMode === "table" && (
          <>
            <GlobalTaskFilters
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
                <div className="bg-background/60 absolute inset-0 z-10 flex items-start justify-center pt-4">
                  <div className="bg-background border-border flex items-center gap-2 rounded-md border px-4 py-2 shadow-sm">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span className="text-muted-foreground text-sm">{t("updating")}</span>
                  </div>
                </div>
              ) : null}
              {table.isInitialLoad ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin" />
                </div>
              ) : table.hasError ? (
                <p className="text-destructive py-8 text-center text-sm">
                  {t("myTasks.loadError")}
                </p>
              ) : (
                <DataTable
                  columns={columns}
                  data={table.displayTasks}
                  groupingOptions={groupingOptions}
                  columnVisibility={effectiveColumnVisibility}
                  onColumnVisibilityChange={setColumnVisibility}
                  initialState={{
                    grouping: ["date group"],
                    expanded: true,
                  }}
                  initialSorting={[
                    { id: "date group", desc: false },
                    { id: "due date", desc: false },
                  ]}
                  enableFilterInput
                  filterInputColumnKey="title"
                  filterInputPlaceholder={t("filters.filterPlaceholder")}
                  enablePagination
                  manualPagination
                  pageCount={table.totalPages}
                  rowCount={table.totalCount}
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
