import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  rectSortingStrategy,
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { Link, useParams, useRouter } from "@tanstack/react-router";
import {
  ArrowDownUp,
  ArrowLeft,
  LayoutGrid,
  List,
  Loader2,
  Plus,
  RotateCcw,
  Settings,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CounterRead } from "@/api/generated/initiativeAPI.schemas";
import { CounterFormDialog } from "@/components/initiativeTools/counters/CounterFormDialog";
import { type CounterLayout, CounterRow } from "@/components/initiativeTools/counters/CounterRow";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCounterGroupRealtime } from "@/hooks/useCounterGroupRealtime";
import {
  useCounterGroup,
  useDeleteCounter,
  useResetAllCounters,
  useResetCounter,
  useSetCount,
  useSortCounters,
  useSteppedCount,
  useUpdateCounter,
} from "@/hooks/useCounters";
import { useRecordRecentView } from "@/hooks/useRecents";
import { useViewPreference } from "@/hooks/useViewPreference";
import { useGuildPath } from "@/lib/guildUrl";

const layoutStorageKey = (groupId: number) => `counter-group-${groupId}-layout`;

const computeMidpoint = (counters: CounterRead[], targetIndex: number): string => {
  const before = counters[targetIndex - 1];
  const after = counters[targetIndex];
  if (before && after) {
    const sum = Number(before.position) + Number(after.position);
    return (sum / 2).toFixed(10);
  }
  if (before) return (Number(before.position) + 1).toFixed(10);
  if (after) return (Number(after.position) - 1).toFixed(10);
  return "0";
};

export function CounterGroupDetailPage() {
  const { t } = useTranslation(["counters", "common"]);
  const router = useRouter();
  const gp = useGuildPath();
  const { guildId, groupId: groupIdParam } = useParams({ strict: false }) as {
    guildId: string;
    groupId?: string;
  };
  const groupId = groupIdParam ? Number(groupIdParam) : null;

  const groupQuery = useCounterGroup(groupId);
  useCounterGroupRealtime(groupId);

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { distance: 8 } })
  );

  const updateCounter = useUpdateCounter(groupId ?? 0);
  const setCount = useSetCount(groupId ?? 0);
  const stepper = useSteppedCount(groupId ?? 0);
  const resetOne = useResetCounter(groupId ?? 0);
  const resetAll = useResetAllCounters(groupId ?? 0);
  const deleteCounter = useDeleteCounter(groupId ?? 0);
  const sortCounters = useSortCounters(groupId ?? 0);

  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<CounterRead | null>(null);
  const [resetAllOpen, setResetAllOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CounterRead | null>(null);
  // The scope key encodes groupId, so the hook automatically returns
  // the right value when navigating between groups — no manual re-read.
  const [persistedLayout, setPersistedLayout] = useViewPreference<string>(
    groupId !== null ? layoutStorageKey(groupId) : "counter-group-noop-layout",
    "row"
  );
  const layout: CounterLayout = persistedLayout === "grid" ? "grid" : "row";

  const toggleLayout = () => {
    if (groupId === null) return;
    setPersistedLayout(layout === "row" ? "grid" : "row");
  };

  const group = groupQuery.data;
  const counters = useMemo(() => {
    const list = group?.counters ?? [];
    return [...list].sort((a, b) => Number(a.position) - Number(b.position));
  }, [group?.counters]);

  // Track recently viewed counter groups for the layout header tabs bar.
  const recordViewMutation = useRecordRecentView("counter_group", Number(guildId));
  const viewedGroupId = group?.id;
  useEffect(() => {
    if (!viewedGroupId) return;
    recordViewMutation.mutate(viewedGroupId);
  }, [viewedGroupId, recordViewMutation.mutate]);

  const canWrite = group?.my_permission_level === "owner" || group?.my_permission_level === "write";
  const canManage = group?.my_permission_level === "owner";

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || groupId === null) return;
    const activeId = Number(active.id);
    const overId = Number(over.id);
    const oldIndex = counters.findIndex((c) => c.id === activeId);
    const newIndex = counters.findIndex((c) => c.id === overId);
    if (oldIndex === -1 || newIndex === -1) return;

    // Build the list with `active` removed, then compute the midpoint for its new slot.
    const withoutActive = counters.filter((c) => c.id !== activeId);
    const insertAt = oldIndex < newIndex ? newIndex : newIndex;
    const newPosition = computeMidpoint(withoutActive, insertAt);

    updateCounter.mutate({
      counterId: activeId,
      data: { position: newPosition },
    });
  };

  const nextPosition = useMemo(() => {
    if (counters.length === 0) return "0";
    const max = counters.reduce((acc, c) => Math.max(acc, Number(c.position)), 0);
    return (max + 1).toFixed(10);
  }, [counters]);

  if (groupId === null) return null;

  if (groupQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingGroup")}
      </div>
    );
  }

  if (groupQuery.isError || !group) {
    return (
      <div className="space-y-3">
        <h1 className="font-semibold text-2xl">{t("notFound")}</h1>
        <p className="text-muted-foreground text-sm">{t("notFoundDescription")}</p>
        <Button variant="outline" asChild>
          <Link to={gp("/counter-groups")}>
            <ArrowLeft className="h-4 w-4" />
            {t("backToGroups")}
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Button variant="ghost" size="sm" asChild className="mb-2 -ml-3">
            <Link to={gp("/counter-groups")}>
              <ArrowLeft className="h-4 w-4" />
              {t("backToGroups")}
            </Link>
          </Button>
          <h1 className="font-semibold text-3xl tracking-tight">{group.name}</h1>
          {group.description && (
            <p className="mt-1 max-w-2xl text-muted-foreground text-sm">{group.description}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={toggleLayout}
            aria-label={
              layout === "row"
                ? t("switchToGridView", { defaultValue: "Switch to grid view" })
                : t("switchToRowView", { defaultValue: "Switch to row view" })
            }
            title={
              layout === "row"
                ? t("switchToGridView", { defaultValue: "Switch to grid view" })
                : t("switchToRowView", { defaultValue: "Switch to row view" })
            }
          >
            {layout === "row" ? <LayoutGrid className="h-4 w-4" /> : <List className="h-4 w-4" />}
          </Button>
          {canWrite && (
            <>
              <Button variant="outline" onClick={() => setAddOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("addCounter")}
              </Button>
              {counters.length > 1 && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" disabled={sortCounters.isPending}>
                      <ArrowDownUp className="h-4 w-4" />
                      {t("sort")}
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onSelect={() => sortCounters.mutate({ field: "name", direction: "asc" })}
                    >
                      {t("sortNameAsc")}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => sortCounters.mutate({ field: "name", direction: "desc" })}
                    >
                      {t("sortNameDesc")}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => sortCounters.mutate({ field: "count", direction: "asc" })}
                    >
                      {t("sortCountAsc")}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => sortCounters.mutate({ field: "count", direction: "desc" })}
                    >
                      {t("sortCountDesc")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              <Button
                variant="outline"
                onClick={() => setResetAllOpen(true)}
                disabled={counters.length === 0 || resetAll.isPending}
              >
                <RotateCcw className="h-4 w-4" />
                {t("resetAll")}
              </Button>
            </>
          )}
          {canManage && (
            <Button
              variant="outline"
              onClick={() => router.navigate({ to: gp(`/counter-groups/${group.id}/settings`) })}
            >
              <Settings className="h-4 w-4" />
              {t("settings")}
            </Button>
          )}
        </div>
      </div>

      {counters.length === 0 ? (
        <div className="rounded-md border border-dashed p-8 text-center">
          <p className="font-medium text-muted-foreground">{t("noCounters")}</p>
          <p className="mt-1 text-muted-foreground text-sm">{t("noCountersDescription")}</p>
          {canWrite && (
            <Button className="mt-4" onClick={() => setAddOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("addCounter")}
            </Button>
          )}
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext
            items={counters.map((c) => c.id.toString())}
            strategy={layout === "grid" ? rectSortingStrategy : verticalListSortingStrategy}
          >
            <div
              className={
                layout === "grid"
                  ? "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
                  : "space-y-2"
              }
            >
              {counters.map((counter) => (
                <CounterRow
                  key={counter.id}
                  counter={counter}
                  canWrite={!!canWrite}
                  layout={layout}
                  focusHref={gp(`/counter-groups/${group.id}/counter/${counter.id}`)}
                  onSetCount={(value) => {
                    // Direct typed entry wins over any pending stepped flush.
                    stepper.cancel(counter.id);
                    setCount.mutate({ counterId: counter.id, data: { count: value } });
                  }}
                  onIncrement={() => stepper.increment(counter)}
                  onDecrement={() => stepper.decrement(counter)}
                  onReset={() => {
                    stepper.cancel(counter.id);
                    resetOne.mutate(counter.id);
                  }}
                  onEdit={() => setEditing(counter)}
                  onDelete={() => {
                    stepper.cancel(counter.id);
                    setPendingDelete(counter);
                  }}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      {canWrite && (
        <CounterFormDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          groupId={groupId}
          defaultPosition={nextPosition}
        />
      )}

      {canWrite && editing && (
        <CounterFormDialog
          open={!!editing}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          groupId={groupId}
          counter={editing}
        />
      )}

      <ConfirmDialog
        open={resetAllOpen}
        onOpenChange={setResetAllOpen}
        title={t("resetAll")}
        description={t("resetAllConfirm")}
        confirmLabel={t("resetAll")}
        onConfirm={() => {
          // Drop any in-flight stepped edits so they don't overwrite the reset.
          stepper.cancelAll();
          resetAll.mutate(undefined, {
            onSuccess: () => setResetAllOpen(false),
          });
        }}
      />

      <ConfirmDialog
        open={!!pendingDelete}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={t("removeCounter")}
        description={t("removeCounterConfirm")}
        confirmLabel={t("removeCounter")}
        destructive
        onConfirm={() => {
          if (!pendingDelete) return;
          deleteCounter.mutate(pendingDelete.id, {
            onSuccess: () => setPendingDelete(null),
          });
        }}
      />
    </div>
  );
}
