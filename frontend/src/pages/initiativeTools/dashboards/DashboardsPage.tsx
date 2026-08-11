import { useRouter } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllDashboards } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { CreateDashboardDialog } from "@/components/initiativeTools/dashboards/CreateDashboardDialog";
import { DashboardCard } from "@/components/initiativeTools/dashboards/DashboardCard";
import { DashboardsFilterBar } from "@/components/initiativeTools/dashboards/DashboardsFilterBar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDashboardsList } from "@/hooks/useDashboards";
import { getDefaultFiltersVisibility } from "@/hooks/useDefaultFiltersOpen";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiativeFilter } from "@/hooks/useInitiativeFilter";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";

type DashboardsViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const DashboardsView = ({ fixedInitiativeId, canCreate }: DashboardsViewProps) => {
  const { t } = useTranslation(["dashboards", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();

  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

  const { initiativeFilter, setInitiativeFilter, filteredInitiativeId } = useInitiativeFilter({
    lockedInitiativeId,
  });
  const effectiveInitiativeId = lockedInitiativeId ?? filteredInitiativeId;

  const dashboardsQuery = useDashboardsList({
    ...(effectiveInitiativeId ? { initiative_id: effectiveInitiativeId } : {}),
    page: 1,
    page_size: 50,
  });
  const initiativesQuery = useInitiatives();
  const initiatives = useMemo(
    () => (initiativesQuery.data ?? []).filter((init) => init.dashboards_enabled),
    [initiativesQuery.data]
  );
  const initiativeNameMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const init of initiatives) map.set(init.id, init.name);
    return map;
  }, [initiatives]);

  // Canonical create answer: the locked/filtered initiative's server-computed
  // create flag, or (in the "All" view) whether any visible initiative grants
  // it. An explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.dashboard, {
    initiativeId: effectiveInitiativeId,
  });
  const canCreateDashboards = canCreate ?? canCreateDerived;

  const {
    open: createOpen,
    setOpen: setCreateOpen,
    onOpenChange: handleCreateOpenChange,
  } = useCreateFromSearchParam();
  const [search, setSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateDashboards ? { run: () => setCreateOpen(true), label: t("createDashboard") } : null
  );

  const dashboards = useMemo(() => {
    const items = dashboardsQuery.data?.items ?? [];
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((dashboard) => dashboard.name.toLowerCase().includes(query));
  }, [dashboardsQuery.data, search]);

  const totalCount = dashboardsQuery.data?.total_count ?? 0;

  const lockedInitiativeName = lockedInitiativeId
    ? (initiativeNameMap.get(lockedInitiativeId) ?? null)
    : null;

  const handleCreated = (dashboard: { id: number }) => {
    void router.navigate({ to: gp(`/dashboards/${dashboard.id}`) });
  };

  const selection = useGridSelection<(typeof dashboards)[number]>();

  return (
    <div className="space-y-6">
      {!lockedInitiativeId && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
              {canCreateDashboards && (
                <Button size="sm" variant="outline" onClick={() => setCreateOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("createDashboard")}
                </Button>
              )}
            </div>
            <p className="text-muted-foreground text-sm">{t("noDashboardsDescription")}</p>
          </div>
        </div>
      )}

      {lockedInitiativeId && canCreateDashboards && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          <Button variant="outline" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("createDashboard")}
          </Button>
        </div>
      )}

      <DashboardsFilterBar
        searchQuery={search}
        onSearchQueryChange={setSearch}
        initiativeFilter={initiativeFilter}
        onInitiativeFilterChange={setInitiativeFilter}
        lockedInitiativeId={lockedInitiativeId}
        lockedInitiativeName={lockedInitiativeName}
        initiatives={initiatives}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
      />

      {dashboardsQuery.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : dashboardsQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : dashboards.length > 0 ? (
        <>
          <BulkAccessSection
            selection={selection}
            tool={Tool.dashboard}
            invalidate={invalidateAllDashboards}
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {dashboards.map((dashboard) => (
              <SelectableGridItem
                key={dashboard.id}
                active={selection.active}
                selected={selection.selectedIds.has(dashboard.id)}
                onToggle={() => selection.toggle(dashboard)}
                label={dashboard.name}
              >
                <DashboardCard
                  dashboard={dashboard}
                  initiativeName={initiativeNameMap.get(dashboard.initiative_id)}
                />
              </SelectableGridItem>
            ))}
          </div>
        </>
      ) : totalCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingDashboards")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noDashboards")}</CardTitle>
            <CardDescription>{t("noDashboardsDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button onClick={() => setCreateOpen(true)} disabled={!canCreateDashboards}>
              {t("createFirst")}
            </Button>
          </CardContent>
        </Card>
      )}

      <CreateDashboardDialog
        open={createOpen}
        onOpenChange={handleCreateOpenChange}
        initiativeId={lockedInitiativeId ?? undefined}
        defaultInitiativeId={effectiveInitiativeId ?? undefined}
        onSuccess={handleCreated}
      />
    </div>
  );
};

export function DashboardsPage() {
  return <DashboardsView />;
}
