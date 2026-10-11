import { useNavigate } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import {
  buildTaskCalendarEntries,
  type CalendarEntry,
  CalendarView,
  type CalendarViewMode,
} from "@/components/calendar";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolLayoutSelect } from "@/components/initiativeTools/shared/ToolLayoutSelect";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { PullToRefresh } from "@/components/PullToRefresh";
import { listLayoutLooks } from "@/components/projects/projectTasksConfig";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { FocusSummary } from "@/components/tasks/FocusSummary";
import { globalTaskColumns } from "@/components/tasks/globalTaskColumns";
import { TaskFilters } from "@/components/tasks/TaskFilters";
import { DataTable } from "@/components/ui/data-table";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { useFocusSummary } from "@/hooks/useFocusSummary";
import { MY_TASKS_VIEW, useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { useListView } from "@/hooks/useListView";
import { useProperties } from "@/hooks/useProperties";
import { communityPath, useCommunityPath } from "@/lib/communityUrl";
import { LAYOUT_NAMESPACES, type LayoutEnv } from "@/lib/layouts/fields";
import { taskFields } from "@/lib/layouts/tasks";
import { getProjectColor } from "@/lib/projectColor";
import { entityRefRoute, taskRoute } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

/** The ways My Tasks lists them. */
const MY_TASKS_LAYOUTS = ["table", "calendar"] as const;

export const MyTasksPage = () => {
  const { t } = useTranslation(["tasks", "dates", "common", "projects"]);

  const { communities } = useCommunities();
  const { user } = useAuth();
  const gp = useCommunityPath();
  const navigate = useNavigate();

  // This person's view of My Tasks: table or calendar, the calendar's month
  // or week, and the table's grouping and columns.
  const view = useListView(MY_TASKS_VIEW);
  const viewMode: "table" | "calendar" = view.layout === "calendar" ? "calendar" : "table";
  const setViewMode = view.rememberLayout as (next: "table" | "calendar") => void;
  const calendarViewMode = (view.mode ?? "month") as CalendarViewMode;
  const setCalendarViewMode = view.setMode as (next: CalendarViewMode) => void;
  const [calendarFocusDate, setCalendarFocusDate] = useState(() => new Date());
  const weekStartsOn = (user?.week_starts_on ?? 0) as 0 | 1 | 2 | 3 | 4 | 5 | 6;

  const table = useGlobalTasksTable();
  const focus = useFocusSummary();

  const handleRefresh = useCallback(async () => {
    await invalidate(q.allTasks());
  }, []);

  const { data: allPropertyDefinitions = [] } = useProperties();
  const fields = useMemo(() => taskFields(allPropertyDefinitions), [allPropertyDefinitions]);
  // Rows come from every community: each one's links go to its own.
  const { t: viewT } = useTranslation(LAYOUT_NAMESPACES);
  const env = useMemo<LayoutEnv>(() => {
    const path = (to: string, task: TaskListRead) => {
      const communityId = task.community_id ?? table.activeCommunityId;
      return communityId ? communityPath(communityId, to) : to;
    };
    return {
      t: viewT as TranslateFn,
      communityPath: path,
      // A row without an initiative resolves through /go.
      taskHref: (task) =>
        path(
          task.initiative_id != null
            ? taskRoute(task.initiative_id, task.project_id, task.id)
            : entityRefRoute("task", task.id),
          task
        ),
    };
  }, [viewT, table.activeCommunityId]);
  // Property columns start hidden.
  const propertyHiddenIds = useMemo(
    () => [...fields.values()].filter((field) => field.source === "property").map(({ id }) => id),
    [fields]
  );
  const { columns: keptColumns, setColumns: setColumnVisibility, setGrouping } = view;
  const tableState = { grouping: view.grouping };
  // A column they never chose about is shown, but for the date window, the
  // community ("guild", the id the stored state is keyed by) and properties.
  const effectiveColumnVisibility = useMemo(() => {
    const next = { ...keptColumns };
    for (const id of ["date group", "guild", ...propertyHiddenIds]) {
      if (!(id in next)) next[id] = false;
    }
    return next;
  }, [keptColumns, propertyHiddenIds]);

  const columns = useMemo(
    () =>
      globalTaskColumns({
        activeCommunityId: table.activeCommunityId,
        isUpdatingTask: table.isUpdatingTask,
        changeTaskStatus: table.changeTaskStatus,
        changeTaskStatusById: table.changeTaskStatusById,
        fetchProjectStatuses: table.fetchProjectStatuses,
        projectStatusCache: table.projectStatusCache,
        t: t as TranslateFn,
        isPinned: focus.isPinned,
        togglePin: focus.togglePin,
        fields,
        env,
      }),
    [
      table.activeCommunityId,
      table.isUpdatingTask,
      table.changeTaskStatus,
      table.changeTaskStatusById,
      table.fetchProjectStatuses,
      table.projectStatusCache,
      t,
      fields,
      env,
      focus.isPinned,
      focus.togglePin,
    ]
  );

  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("myTasks.groupByDate") },
      { id: "guild", label: t("myTasks.groupByCommunity") },
    ],
    [t]
  );

  const calendarEntries = useMemo<CalendarEntry[]>(() => {
    const entries: CalendarEntry[] = [];
    // Reuse the shared builder so start/due markers get the same visual
    // treatment as the other calendars, injecting communityId into meta for
    // cross-community navigation. Not draggable here (no reschedule handler).
    table.displayTasks.forEach((task) => {
      for (const entry of buildTaskCalendarEntries(task, getProjectColor(task.project_id), false)) {
        entries.push({
          ...entry,
          meta: { ...(entry.meta as Record<string, unknown>), communityId: task.community_id },
        });
      }
    });
    return entries;
  }, [table.displayTasks]);

  const handleEntryClick = (entry: CalendarEntry) => {
    const meta = entry.meta as
      | { taskId?: number; projectId?: number; initiativeId?: number | null; communityId?: number }
      | undefined;
    if (!meta?.taskId) return;
    // A task's URL names its project and initiative. This page spans communities, so
    // a row that didn't carry them resolves through `/go` instead of guessing.
    const path =
      meta.projectId != null && meta.initiativeId != null
        ? taskRoute(meta.initiativeId, meta.projectId, meta.taskId)
        : entityRefRoute("task", meta.taskId);
    void navigate({ to: meta.communityId ? communityPath(meta.communityId, path) : gp(path) });
  };

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="font-semibold text-3xl tracking-tight">{t("myTasks.title")}</h1>

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
            // The same layout menu as a project's tasks: My Tasks offers the
            // table and the calendar, and no presets.
            viewControl={
              <ToolLayoutSelect
                layouts={MY_TASKS_LAYOUTS.map((kind) => ({
                  slug: kind,
                  name: t(`projects:${listLayoutLooks[kind].labelKey}` as never),
                  icon: listLayoutLooks[kind].icon,
                }))}
                activeSlug={viewMode}
                modified={viewMode === "table" && table.activeFilterCount > 0}
                onSelect={(slug) => setViewMode(slug as "table" | "calendar")}
                label={t("projects:layouts.label")}
                modifiedLabel={t("projects:filters.modified")}
              />
            }
          />
        </div>

        <FocusSummary
          focus={focus}
          activeCommunityId={table.activeCommunityId}
          changeTaskStatus={table.changeTaskStatus}
          isUpdatingTask={table.isUpdatingTask}
        />

        {viewMode === "table" && (
          <>
            <ToolFilterPanel
              open={table.filtersOpen}
              onOpenChange={table.setFiltersOpen}
              onClear={table.clearFilters}
              activeCount={table.activeFilterCount}
            >
              <TaskFilters
                scope={{ kind: "mine", communities }}
                value={table.filters}
                onChange={table.setFilters}
              />
            </ToolFilterPanel>

            <div className="relative">
              {/* A refetch is a background event: a status change has already
                  been applied to the rows optimistically, and the reader can go
                  on sorting, paging and checking things off while the
                  cross-community aggregate catches up. So this says a refresh is
                  running and takes nothing away — no cover, no pointer events,
                  no dimming of rows that are already correct. */}
              {table.isRefetching ? (
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 top-0 z-10 h-0.5 overflow-hidden rounded-full bg-primary/15"
                >
                  <div className="h-full w-1/3 animate-indeterminate-sweep rounded-full bg-primary/60" />
                </div>
              ) : null}
              <span aria-live="polite" className="sr-only">
                {table.isRefetching ? t("updating") : ""}
              </span>
              {/* The saved sort has to be in hand before the table mounts: it
                  seeds its headers once, so a table built on the defaults would
                  keep claiming them while the rows came back in the saved
                  order. The filters resolve from the same request. */}
              {table.isInitialLoad || !table.preferencesLoaded ? (
                <SkeletonRegion>
                  <TableSkeleton rows={8} columns={6} pagination />
                </SkeletonRegion>
              ) : table.hasError ? (
                <p className="py-8 text-center text-destructive text-sm">
                  {t("myTasks.loadError")}
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
