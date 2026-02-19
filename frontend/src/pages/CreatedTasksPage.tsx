import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { useGuilds } from "@/hooks/useGuilds";
import { useGlobalTasksTable } from "@/hooks/useGlobalTasksTable";
import { globalTaskColumns } from "@/components/tasks/globalTaskColumns";
import { GlobalTaskFilters } from "@/components/tasks/GlobalTaskFilters";
import { DataTable } from "@/components/ui/data-table";
import { PullToRefresh } from "@/components/PullToRefresh";
import type { TranslateFn } from "@/types/i18n";

export const CreatedTasksPage = () => {
  const { t } = useTranslation(["tasks", "dates", "common"]);
  const { guilds } = useGuilds();

  const table = useGlobalTasksTable({ scope: "global_created", storageKeyPrefix: "created-tasks" });

  const handleRefresh = useCallback(async () => {
    await table.localQueryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
  }, [table.localQueryClient]);

  const columns = useMemo(
    () =>
      globalTaskColumns({
        activeGuildId: table.activeGuildId,
        isUpdatingTaskStatus: table.isUpdatingTaskStatus,
        changeTaskStatus: table.changeTaskStatus,
        changeTaskStatusById: table.changeTaskStatusById,
        fetchProjectStatuses: table.fetchProjectStatuses,
        projectStatusCache: table.projectStatusCache,
        projectsById: table.projectsById,
        t: t as TranslateFn,
        showAssignees: true,
      }),
    [
      table.activeGuildId,
      table.isUpdatingTaskStatus,
      table.changeTaskStatus,
      table.changeTaskStatusById,
      table.fetchProjectStatuses,
      table.projectStatusCache,
      table.projectsById,
      t,
    ]
  );

  const groupingOptions = useMemo(
    () => [
      { id: "date group", label: t("createdTasks.groupByDate") },
      { id: "guild", label: t("createdTasks.groupByGuild") },
    ],
    [t]
  );

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("createdTasks.title")}</h1>
          <p className="text-muted-foreground">{t("createdTasks.subtitle")}</p>
        </div>

        <GlobalTaskFilters
          statusFilters={table.statusFilters}
          setStatusFilters={table.setStatusFilters}
          priorityFilters={table.priorityFilters}
          setPriorityFilters={table.setPriorityFilters}
          guildFilters={table.guildFilters}
          setGuildFilters={table.setGuildFilters}
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
              {t("createdTasks.loadError")}
            </p>
          ) : (
            <DataTable
              columns={columns}
              data={table.displayTasks}
              groupingOptions={groupingOptions}
              initialState={{
                grouping: ["date group"],
                expanded: true,
                columnVisibility: { "date group": false, guild: false },
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
      </div>
    </PullToRefresh>
  );
};
