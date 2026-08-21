import { Link, useRouter } from "@tanstack/react-router";
import { Loader2, Plus, Store } from "lucide-react";
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
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

type DashboardsViewProps = {
  /** The initiative this list belongs to. Required: dashboards are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

export const DashboardsView = ({ fixedInitiativeId, canCreate }: DashboardsViewProps) => {
  const { t } = useTranslation(["dashboards", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();

  const dashboardsQuery = useDashboardsList({
    initiative_id: fixedInitiativeId,
    page: 1,
    page_size: 50,
  });

  // Canonical create answer: this initiative's server-computed create flag. An
  // explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.dashboard, {
    initiativeId: fixedInitiativeId,
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

  const handleCreated = (dashboard: { id: number }) => {
    void router.navigate({
      to: gp(toolDetailRoute(Tool.dashboard, fixedInitiativeId, dashboard.id)),
    });
  };

  const selection = useGridSelection<(typeof dashboards)[number]>();

  return (
    <div className="space-y-6">
      {canCreateDashboards && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          <Button variant="outline" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("createDashboard")}
          </Button>
          <Button variant="ghost" asChild>
            <Link to={gp("/marketplace")} search={{ kind: "dashboard" }}>
              <Store className="h-4 w-4" />
              {t("browseMarketplace")}
            </Link>
          </Button>
        </div>
      )}

      <DashboardsFilterBar
        searchQuery={search}
        onSearchQueryChange={setSearch}
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
                <DashboardCard dashboard={dashboard} />
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
        initiativeId={fixedInitiativeId}
        defaultInitiativeId={fixedInitiativeId}
        onSuccess={handleCreated}
      />
    </div>
  );
};
