import { useRouter } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllCounterGroups } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import { CounterGroupCard } from "@/components/initiativeTools/counters/CounterGroupCard";
import { CountersFilterBar } from "@/components/initiativeTools/counters/CountersFilterBar";
import { CreateCounterGroupDialog } from "@/components/initiativeTools/counters/CreateCounterGroupDialog";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

type CountersViewProps = {
  /** The initiative this list belongs to. Required: counter groups are only
   *  ever browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

export const CounterGroupsView = ({ fixedInitiativeId, canCreate }: CountersViewProps) => {
  const { t } = useTranslation(["counterGroups", "common", "access"]);
  const router = useRouter();
  const gp = useGuildPath();

  const groupsQuery = useCounterGroupsList({
    initiative_id: fixedInitiativeId,
    page: 1,
    page_size: 50,
  });

  // Canonical create answer: the locked/filtered initiative's server-computed
  // create flag, or (in the "All" view) whether any visible initiative grants
  // it. An explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.counter_group, {
    initiativeId: fixedInitiativeId,
  });
  const canCreateGroups = canCreate ?? canCreateDerived;

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

  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);

  const groups = useMemo(() => {
    const items = groupsQuery.data?.items ?? [];
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((g) => g.name.toLowerCase().includes(query));
  }, [groupsQuery.data, search]);

  const totalCount = groupsQuery.data?.total_count ?? 0;

  const handleCreated = (group: { id: number }) => {
    void router.navigate({
      to: gp(toolDetailRoute(Tool.counter_group, fixedInitiativeId, group.id)),
    });
  };

  const selection = useGridSelection<(typeof groups)[number]>(groups);

  const groupImport = useToolImportAction({
    tool: Tool.counter_group,
    canImport: canCreateGroups,
    fixedInitiativeId,
  });

  return (
    <div className="space-y-6">
      <ToolListToolbar
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: search.trim() ? 1 : 0,
        }}
        actions={
          canCreateGroups ? (
            <Button variant="outline" size="sm" className="h-9" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("createGroup")}
            </Button>
          ) : null
        }
        menuItems={groupImport.menuItem}
        onEnterSelection={!selection.active && groups.length > 0 ? selection.enter : undefined}
      />
      {groupImport.dialog}

      <CountersFilterBar
        searchQuery={search}
        onSearchQueryChange={setSearch}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
        onClear={() => setSearch("")}
        activeCount={search.trim() ? 1 : 0}
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
                onToggle={(options) => selection.toggle(group, options)}
                label={group.name}
              >
                <CounterGroupCard group={group} />
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
              fixedInitiativeId={fixedInitiativeId}
              variant="button"
            />
          </CardContent>
        </Card>
      )}

      <CreateCounterGroupDialog
        open={createOpen}
        onOpenChange={handleCreateOpenChange}
        initiativeId={fixedInitiativeId}
        defaultInitiativeId={fixedInitiativeId}
        onSuccess={handleCreated}
      />
    </div>
  );
};
