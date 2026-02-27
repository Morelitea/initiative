import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearch } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useQueuesList } from "@/hooks/useQueues";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useMyInitiativePermissions,
  canCreate as canCreatePermission,
} from "@/hooks/useInitiativeRoles";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { QueueCard } from "@/components/initiativeTools/queues/QueueCard";
import { CreateQueueDialog } from "@/components/initiativeTools/queues/CreateQueueDialog";
import {
  QueuesFilterBar,
  type StatusFilter,
} from "@/components/initiativeTools/queues/QueuesFilterBar";

const INITIATIVE_FILTER_ALL = "all";

type QueuesViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const QueuesView = ({ fixedInitiativeId, canCreate }: QueuesViewProps) => {
  const { t } = useTranslation(["queues", "common"]);
  const router = useRouter();
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as {
    initiativeId?: string;
    create?: string;
    page?: number;
  };

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

  // Consume ?initiativeId from URL once
  useEffect(() => {
    const urlInitiativeId = searchParams.initiativeId;
    const paramKey = urlInitiativeId || "";

    if (urlInitiativeId && !lockedInitiativeId && paramKey !== lastConsumedParams.current) {
      lastConsumedParams.current = paramKey;
      setInitiativeFilter(urlInitiativeId);
    }
  }, [searchParams, lockedInitiativeId]);

  const [page, setPageState] = useState(() => searchParams.page ?? 1);

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

  useEffect(() => {
    if (lockedInitiativeId) {
      const lockedValue = String(lockedInitiativeId);
      setInitiativeFilter((prev) => (prev === lockedValue ? prev : lockedValue));
    }
  }, [lockedInitiativeId]);

  // Reset initiative filter when guild changes
  useEffect(() => {
    const prevGuildId = prevGuildIdRef.current;
    prevGuildIdRef.current = activeGuildId;
    if (prevGuildId !== null && prevGuildId !== activeGuildId && !lockedInitiativeId) {
      setInitiativeFilter(INITIATIVE_FILTER_ALL);
      lastConsumedParams.current = "";
    }
  }, [activeGuildId, lockedInitiativeId]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [initiativeFilter, setPage]);

  const queuesQuery = useQueuesList({
    ...(initiativeFilter !== INITIATIVE_FILTER_ALL
      ? { initiative_id: Number(initiativeFilter) }
      : {}),
    page,
    page_size: 20,
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

  // Filter initiatives where user can create queues
  const creatableInitiatives = useMemo(() => {
    if (!user) return [];
    return initiatives.filter((initiative) =>
      initiative.members.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      )
    );
  }, [initiatives, user]);

  // Determine if user can create queues
  const canCreateQueues = useMemo(() => {
    if (canCreate !== undefined) return canCreate;
    if (filteredInitiativeId && filteredInitiativePermissions) {
      return canCreatePermission(filteredInitiativePermissions, "queues");
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

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const getDefaultFiltersVisibility = () =>
    typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches;
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  // Open create dialog when ?create=true is in URL
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
    if (!open && searchParams.create) {
      isClosingCreateDialog.current = true;
      void router.navigate({
        to: gp("/queues"),
        search: { initiativeId: searchParams.initiativeId },
        replace: true,
      });
    }
  };

  const handleQueueCreated = (queue: { id: number }) => {
    void router.navigate({
      to: gp(`/queues/${queue.id}`),
    });
  };

  const totalCount = queuesQuery.data?.total_count ?? 0;
  const hasNext = queuesQuery.data?.has_next ?? false;
  const pageSize = 20;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

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

  return (
    <div className="space-y-6">
      {!lockedInitiativeId && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
              {canCreateQueues && (
                <Button size="sm" variant="outline" onClick={() => setCreateDialogOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("createQueue")}
                </Button>
              )}
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
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : queuesQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : queues.length > 0 ? (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {queues.map((queue) => (
              <QueueCard
                key={queue.id}
                queue={queue}
                initiativeName={initiativeNameMap.get(queue.initiative_id)}
              />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                {t("previous")}
              </Button>
              <span className="text-muted-foreground text-sm">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={!hasNext}
              >
                {t("next")}
              </Button>
            </div>
          )}
        </>
      ) : totalCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingQueues")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noQueues")}</CardTitle>
            <CardDescription>{t("noQueuesDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setCreateDialogOpen(true)} disabled={!canCreateQueues}>
              {t("createFirst")}
            </Button>
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

      {canCreateQueues && (
        <Button
          type="button"
          className="shadow-primary/40 fixed right-6 bottom-6 z-40 h-12 rounded-full px-6 shadow-lg"
          onClick={() => setCreateDialogOpen(true)}
        >
          <Plus className="h-4 w-4" />
          {t("createQueue")}
        </Button>
      )}
    </div>
  );
};

export function QueuesPage() {
  return <QueuesView />;
}
