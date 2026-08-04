import { useRouter } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCounterGroups } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { ToolImportAction } from "@/components/imports/ToolImportAction";
import { CounterGroupCard } from "@/components/initiativeTools/counters/CounterGroupCard";
import { CountersFilterBar } from "@/components/initiativeTools/counters/CountersFilterBar";
import { CreateCounterGroupDialog } from "@/components/initiativeTools/counters/CreateCounterGroupDialog";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { getDefaultFiltersVisibility } from "@/hooks/useDefaultFiltersOpen";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiativeFilter } from "@/hooks/useInitiativeFilter";
import { canCreateTool, useMyInitiativePermissions } from "@/hooks/useInitiativeRoles";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";

type CountersViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const CounterGroupsView = ({ fixedInitiativeId, canCreate }: CountersViewProps) => {
  const { t } = useTranslation(["counterGroups", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();
  const { permissionsFor } = useInitiativeAccess();

  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

  const { initiativeFilter, setInitiativeFilter, filteredInitiativeId } = useInitiativeFilter({
    lockedInitiativeId,
  });
  const effectiveInitiativeId = lockedInitiativeId ?? filteredInitiativeId;

  const { data: initiativePerms } = useMyInitiativePermissions(effectiveInitiativeId);

  const groupsQuery = useCounterGroupsList({
    ...(effectiveInitiativeId ? { initiative_id: effectiveInitiativeId } : {}),
    page: 1,
    page_size: 50,
  });
  const initiativesQuery = useInitiatives();
  const initiatives = useMemo(
    () => (initiativesQuery.data ?? []).filter((init) => init.counter_groups_enabled),
    [initiativesQuery.data]
  );
  const initiativeNameMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const init of initiatives) map.set(init.id, init.name);
    return map;
  }, [initiatives]);

  const canCreateGroups = useMemo(() => {
    if (canCreate !== undefined) return canCreate;
    if (effectiveInitiativeId && initiativePerms) {
      return canCreateTool(initiativePerms, Tool.counter_group);
    }
    // No initiative filter: creatable if the shared access helper allows
    // creating in ANY counter-enabled initiative (honors guild-admin, PAM
    // grants, and frozen read-only guilds).
    return initiatives.some((initiative) => permissionsFor(initiative)[Tool.counter_group].create);
  }, [canCreate, effectiveInitiativeId, initiativePerms, initiatives, permissionsFor]);

  const {
    open: createOpen,
    setOpen: setCreateOpen,
    onOpenChange: handleCreateOpenChange,
  } = useCreateFromSearchParam();
  const [search, setSearch] = useState("");

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateGroups ? { run: () => setCreateOpen(true), label: t("createGroup") } : null
  );

  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  const groups = useMemo(() => {
    const items = groupsQuery.data?.items ?? [];
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((g) => g.name.toLowerCase().includes(query));
  }, [groupsQuery.data, search]);

  const totalCount = groupsQuery.data?.total_count ?? 0;

  const lockedInitiativeName = lockedInitiativeId
    ? (initiativeNameMap.get(lockedInitiativeId) ?? null)
    : null;

  const handleCreated = (group: { id: number }) => {
    void router.navigate({ to: gp(`/counter-groups/${group.id}`) });
  };

  const selection = useGridSelection<(typeof groups)[number]>();

  return (
    <div className="space-y-6">
      {!lockedInitiativeId && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
              {canCreateGroups && (
                <Button size="sm" variant="outline" onClick={() => setCreateOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("createGroup")}
                </Button>
              )}
              <ToolImportAction tool={Tool.counter_group} canImport={canCreateGroups} />
            </div>
            <p className="text-muted-foreground text-sm">{t("noGroupsDescription")}</p>
          </div>
        </div>
      )}

      {lockedInitiativeId && canCreateGroups && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          <Button variant="outline" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("createGroup")}
          </Button>
          <ToolImportAction
            tool={Tool.counter_group}
            canImport={canCreateGroups}
            fixedInitiativeId={lockedInitiativeId ?? undefined}
          />
        </div>
      )}

      <CountersFilterBar
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

      {groupsQuery.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : groupsQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : groups.length > 0 ? (
        <>
          <BulkAccessSection
            selection={selection}
            tool={Tool.counter_group}
            invalidate={invalidateAllCounterGroups}
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {groups.map((group) => (
              <SelectableGridItem
                key={group.id}
                active={selection.active}
                selected={selection.selectedIds.has(group.id)}
                onToggle={() => selection.toggle(group)}
                label={group.name}
              >
                <CounterGroupCard
                  group={group}
                  initiativeName={initiativeNameMap.get(group.initiative_id)}
                />
              </SelectableGridItem>
            ))}
          </div>
        </>
      ) : totalCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingGroups")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noGroups")}</CardTitle>
            <CardDescription>{t("noGroupsDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button onClick={() => setCreateOpen(true)} disabled={!canCreateGroups}>
              {t("createFirst")}
            </Button>
            <ToolImportAction
              tool={Tool.counter_group}
              canImport={canCreateGroups}
              fixedInitiativeId={lockedInitiativeId ?? undefined}
              variant="button"
            />
          </CardContent>
        </Card>
      )}

      <CreateCounterGroupDialog
        open={createOpen}
        onOpenChange={handleCreateOpenChange}
        initiativeId={lockedInitiativeId ?? undefined}
        defaultInitiativeId={effectiveInitiativeId ?? undefined}
        onSuccess={handleCreated}
      />
    </div>
  );
};

export function CounterGroupsPage() {
  return <CounterGroupsView />;
}
