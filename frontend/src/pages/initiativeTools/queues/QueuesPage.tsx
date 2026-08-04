import { useRouter, useSearch } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllQueues } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { PaginationBar } from "@/components/documents/PaginationBar";
import { ToolImportAction } from "@/components/imports/ToolImportAction";
import { CreateQueueDialog } from "@/components/initiativeTools/queues/CreateQueueDialog";
import { QueueCard } from "@/components/initiativeTools/queues/QueueCard";
import {
  QueuesFilterBar,
  type StatusFilter,
} from "@/components/initiativeTools/queues/QueuesFilterBar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { getDefaultFiltersVisibility } from "@/hooks/useDefaultFiltersOpen";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { INITIATIVE_FILTER_ALL, useInitiativeFilter } from "@/hooks/useInitiativeFilter";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useQueuesList } from "@/hooks/useQueues";
import { useGuildPath } from "@/lib/guildUrl";

type QueuesViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const QueuesView = ({ fixedInitiativeId, canCreate }: QueuesViewProps) => {
  const { t } = useTranslation(["queues", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as {
    initiativeId?: string;
    create?: string;
    page?: number;
  };

  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

  const { initiativeFilter, setInitiativeFilter, filteredInitiativeId } = useInitiativeFilter({
    lockedInitiativeId,
  });

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

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [initiativeFilter, setPage]);

  const queuesQuery = useQueuesList({
    ...(initiativeFilter !== INITIATIVE_FILTER_ALL
      ? { initiative_id: Number(initiativeFilter) }
      : {}),
    page,
    page_size: pageSize,
  });

  const initiativesQuery = useInitiatives();
  const initiatives = useMemo(
    () => (initiativesQuery.data ?? []).filter((init) => init.queues_enabled),
    [initiativesQuery.data]
  );

  // Build initiative name lookup
  const initiativeNameMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const init of initiatives) {
      map.set(init.id, init.name);
    }
    return map;
  }, [initiatives]);

  // Canonical create answer: the locked/filtered initiative's server-computed
  // create flag, or (in the "All" view) whether any visible initiative grants
  // it. An explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.queue, {
    initiativeId: lockedInitiativeId ?? filteredInitiativeId,
  });
  const canCreateQueues = canCreate ?? canCreateDerived;

  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam();
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateQueues ? { run: () => setCreateDialogOpen(true), label: t("createQueue") } : null
  );

  const handleQueueCreated = (queue: { id: number }) => {
    void router.navigate({
      to: gp(`/queues/${queue.id}`),
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

  const lockedInitiativeName = lockedInitiativeId
    ? (initiativeNameMap.get(lockedInitiativeId) ?? null)
    : null;

  const selection = useGridSelection<(typeof queues)[number]>();

  return (
    <div className="space-y-6">
      {!lockedInitiativeId && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
              {canCreateQueues && (
                <Button size="sm" variant="outline" onClick={() => setCreateDialogOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("createQueue")}
                </Button>
              )}
              <ToolImportAction tool={Tool.queue} canImport={canCreateQueues} />
            </div>
            <p className="text-muted-foreground text-sm">{t("noQueuesDescription")}</p>
          </div>
        </div>
      )}

      {lockedInitiativeId && canCreateQueues && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          <Button variant="outline" onClick={() => setCreateDialogOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("createQueue")}
          </Button>
          <ToolImportAction
            tool={Tool.queue}
            canImport={canCreateQueues}
            fixedInitiativeId={lockedInitiativeId ?? undefined}
          />
        </div>
      )}

      <QueuesFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        initiativeFilter={initiativeFilter}
        onInitiativeFilterChange={setInitiativeFilter}
        lockedInitiativeId={lockedInitiativeId}
        lockedInitiativeName={lockedInitiativeName}
        initiatives={initiatives}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
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
                <QueueCard
                  queue={queue}
                  initiativeName={initiativeNameMap.get(queue.initiative_id)}
                />
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
              fixedInitiativeId={lockedInitiativeId ?? undefined}
              variant="button"
            />
          </CardContent>
        </Card>
      )}

      <CreateQueueDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        initiativeId={lockedInitiativeId ?? undefined}
        defaultInitiativeId={
          initiativeFilter !== INITIATIVE_FILTER_ALL ? Number(initiativeFilter) : undefined
        }
        onSuccess={handleQueueCreated}
      />
    </div>
  );
};

export function QueuesPage() {
  return <QueuesView />;
}
