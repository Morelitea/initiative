import { useRouter, useSearch } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { CounterGroupCard } from "@/components/initiativeTools/counters/CounterGroupCard";
import { CountersFilterBar } from "@/components/initiativeTools/counters/CountersFilterBar";
import { CreateCounterGroupDialog } from "@/components/initiativeTools/counters/CreateCounterGroupDialog";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useGuilds } from "@/hooks/useGuilds";
import {
  canCreate as canCreatePermission,
  useMyInitiativePermissions,
} from "@/hooks/useInitiativeRoles";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";

const INITIATIVE_FILTER_ALL = "all";

type CountersViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const CounterGroupsView = ({ fixedInitiativeId, canCreate }: CountersViewProps) => {
  const { t } = useTranslation(["counters", "common"]);
  const router = useRouter();
  const gp = useGuildPath();
  const { activeGuildId } = useGuilds();
  const searchParams = useSearch({ strict: false }) as {
    initiativeId?: string;
    create?: string;
  };

  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;

  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    lockedInitiativeId ? String(lockedInitiativeId) : INITIATIVE_FILTER_ALL
  );

  const filteredInitiativeId =
    initiativeFilter !== INITIATIVE_FILTER_ALL ? Number(initiativeFilter) : null;
  const effectiveInitiativeId = lockedInitiativeId ?? filteredInitiativeId;

  const lastConsumedParams = useRef<string>("");
  const prevGuildIdRef = useRef<number | null>(activeGuildId);

  // Consume ?initiativeId from the URL once.
  useEffect(() => {
    const urlInitiativeId = searchParams.initiativeId;
    const paramKey = urlInitiativeId ?? "";
    if (urlInitiativeId && !lockedInitiativeId && paramKey !== lastConsumedParams.current) {
      lastConsumedParams.current = paramKey;
      setInitiativeFilter(urlInitiativeId);
    }
  }, [searchParams, lockedInitiativeId]);

  // Keep the filter pinned to the locked initiative.
  useEffect(() => {
    if (lockedInitiativeId) {
      const lockedValue = String(lockedInitiativeId);
      setInitiativeFilter((prev) => (prev === lockedValue ? prev : lockedValue));
    }
  }, [lockedInitiativeId]);

  // Reset the initiative filter when the active guild changes.
  useEffect(() => {
    const prevGuildId = prevGuildIdRef.current;
    prevGuildIdRef.current = activeGuildId;
    if (prevGuildId !== null && prevGuildId !== activeGuildId && !lockedInitiativeId) {
      setInitiativeFilter(INITIATIVE_FILTER_ALL);
      lastConsumedParams.current = "";
    }
  }, [activeGuildId, lockedInitiativeId]);

  const { data: initiativePerms } = useMyInitiativePermissions(effectiveInitiativeId);

  const groupsQuery = useCounterGroupsList({
    ...(effectiveInitiativeId ? { initiative_id: effectiveInitiativeId } : {}),
    page: 1,
    page_size: 50,
  });
  const initiativesQuery = useInitiatives();
  const initiatives = useMemo(
    () => (initiativesQuery.data ?? []).filter((init) => init.counters_enabled),
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
      return canCreatePermission(initiativePerms, "counters");
    }
    return initiatives.length > 0;
  }, [canCreate, effectiveInitiativeId, initiativePerms, initiatives.length]);

  const [createOpen, setCreateOpen] = useState(searchParams.create === "true");
  const isClosingCreateDialog = useRef(false);
  const [search, setSearch] = useState("");

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateGroups ? { run: () => setCreateOpen(true), label: t("createGroup") } : null
  );

  // Open the create dialog whenever ?create=true is present — including when
  // the sidebar "+" navigates here while already on the page (the useState
  // initializer above only runs on mount).
  useEffect(() => {
    const shouldCreate = searchParams.create === "true";
    if (shouldCreate && !createOpen && !isClosingCreateDialog.current) {
      setCreateOpen(true);
    }
    if (!shouldCreate) {
      isClosingCreateDialog.current = false;
    }
  }, [searchParams.create, createOpen]);

  const handleCreateOpenChange = (open: boolean) => {
    setCreateOpen(open);
    if (!open && searchParams.create) {
      isClosingCreateDialog.current = true;
      void router.navigate({
        to: gp("/counter-groups"),
        search: { initiativeId: searchParams.initiativeId },
        replace: true,
      });
    }
  };
  const getDefaultFiltersVisibility = () =>
    typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches;
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
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {groups.map((group) => (
            <CounterGroupCard
              key={group.id}
              group={group}
              initiativeName={initiativeNameMap.get(group.initiative_id)}
            />
          ))}
        </div>
      ) : totalCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingGroups")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noGroups")}</CardTitle>
            <CardDescription>{t("noGroupsDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setCreateOpen(true)} disabled={!canCreateGroups}>
              {t("createFirst")}
            </Button>
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
