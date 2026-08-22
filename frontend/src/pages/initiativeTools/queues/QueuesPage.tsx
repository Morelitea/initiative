import { useRouter, useSearch } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllQueues } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { PaginationBar } from "@/components/documents/PaginationBar";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import { CreateQueueDialog } from "@/components/initiativeTools/queues/CreateQueueDialog";
import { QueueCard } from "@/components/initiativeTools/queues/QueueCard";
import {
  QueuesFilterBar,
  type StatusFilter,
} from "@/components/initiativeTools/queues/QueuesFilterBar";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useQueuesList } from "@/hooks/useQueues";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

type QueuesViewProps = {
  /** The initiative this list belongs to. Required: queues are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

export const QueuesView = ({ fixedInitiativeId, canCreate }: QueuesViewProps) => {
  const { t } = useTranslation(["queues", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as {
    create?: string;
    page?: number;
  };

  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  const [page, setPageState] = useState(() => searchParams.page ?? 1);
  const [pageSize, setPageSize] = useState(20);

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setPageState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        void router.navigate({
          to: ".",
          search: {
            ...searchParamsRef.current,
            page: next <= 1 ? undefined : next,
          },
          replace: true,
        });
        return next;
      });
    },
    [router]
  );

  const queuesQuery = useQueuesList({
    initiative_id: fixedInitiativeId,
    page,
    page_size: pageSize,
  });

  // Canonical create answer: this initiative's server-computed create flag. An
  // explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.queue, {
    initiativeId: fixedInitiativeId,
  });
  const canCreateQueues = canCreate ?? canCreateDerived;

  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam();
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateQueues ? { run: () => setCreateDialogOpen(true), label: t("createQueue") } : null
  );

  const handleQueueCreated = (queue: { id: number }) => {
    void router.navigate({
      to: gp(toolDetailRoute(Tool.queue, fixedInitiativeId, queue.id)),
    });
  };

  const totalCount = queuesQuery.data?.total_count ?? 0;
  const hasNext = queuesQuery.data?.has_next ?? false;

  // Client-side filtering by search query and status
  const queues = useMemo(() => {
    const items = queuesQuery.data?.items ?? [];
    const query = searchQuery.trim().toLowerCase();
    return items.filter((queue) => {
      const matchesSearch = !query || queue.name.toLowerCase().includes(query);
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "active" && queue.is_active) ||
        (statusFilter === "inactive" && !queue.is_active);
      return matchesSearch && matchesStatus;
    });
  }, [queuesQuery.data, searchQuery, statusFilter]);

  const selection = useGridSelection<(typeof queues)[number]>();

  const queueImport = useToolImportAction({
    tool: Tool.queue,
    canImport: canCreateQueues,
    fixedInitiativeId,
  });

  const activeFilterCount = (searchQuery.trim() ? 1 : 0) + (statusFilter === "all" ? 0 : 1);

  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setStatusFilter("all");
  }, []);

  return (
    <div className="space-y-6">
      <ToolListToolbar
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        actions={
          canCreateQueues ? (
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => setCreateDialogOpen(true)}
            >
              <Plus className="h-4 w-4" />
              {t("createQueue")}
            </Button>
          ) : null
        }
        menuItems={queueImport.menuItem}
        onEnterSelection={!selection.active && queues.length > 0 ? selection.enter : undefined}
      />
      {queueImport.dialog}

      <QueuesFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
        onClear={clearFilters}
        activeCount={activeFilterCount}
      />

      {/* Content */}
      {queuesQuery.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : queuesQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : queues.length > 0 ? (
        <>
          <BulkAccessSection
            selection={selection}
            tool={Tool.queue}
            invalidate={invalidateAllQueues}
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {queues.map((queue) => (
              <SelectableGridItem
                key={queue.id}
                active={selection.active}
                selected={selection.selectedIds.has(queue.id)}
                onToggle={() => selection.toggle(queue)}
                label={queue.name}
              >
                <QueueCard queue={queue} />
              </SelectableGridItem>
            ))}
          </div>

          <PaginationBar
            page={page}
            pageSize={pageSize}
            totalCount={totalCount}
            hasNext={hasNext}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
            onPrefetchPage={() => {}}
          />
        </>
      ) : totalCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingQueues")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noQueues")}</CardTitle>
            <CardDescription>{t("noQueuesDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button onClick={() => setCreateDialogOpen(true)} disabled={!canCreateQueues}>
              {t("createFirst")}
            </Button>
            <ToolImportAction
              tool={Tool.queue}
              canImport={canCreateQueues}
              fixedInitiativeId={fixedInitiativeId}
              variant="button"
            />
          </CardContent>
        </Card>
      )}

      <CreateQueueDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        initiativeId={fixedInitiativeId}
        defaultInitiativeId={fixedInitiativeId}
        onSuccess={handleQueueCreated}
      />
    </div>
  );
};
