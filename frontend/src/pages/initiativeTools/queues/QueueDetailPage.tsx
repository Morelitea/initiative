import { Link, useParams } from "@tanstack/react-router";
import { Plus, Settings } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { QueueItemRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { ActHeldButton } from "@/components/initiativeTools/queues/ActHeldButton";
import { AddQueueItemDialog } from "@/components/initiativeTools/queues/AddQueueItemDialog";
import { EditQueueItemDialog } from "@/components/initiativeTools/queues/EditQueueItemDialog";
import { QueueControls } from "@/components/initiativeTools/queues/QueueControls";
import { QueueItemRow } from "@/components/initiativeTools/queues/QueueItemRow";
import { QueueTimeline } from "@/components/initiativeTools/queues/QueueTimeline";
import { QueueViewToggle } from "@/components/initiativeTools/queues/QueueViewToggle";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import {
  DetailPageSkeleton,
  ListSkeleton,
  SkeletonRegion,
} from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useReadOnOpen } from "@/hooks/useNotifications";
import {
  useAdvanceTurn,
  useHoldCurrent,
  usePreviousTurn,
  useQueue,
  useReleaseHeld,
  useResetQueue,
  useSetActiveItem,
  useStartQueue,
  useStopQueue,
  useUpdateQueue,
} from "@/hooks/useQueues";
import { useQueueView } from "@/hooks/useQueueView";
import { useRecordRecentView } from "@/hooks/useRecents";
import { useQueueRealtime } from "@/hooks/useResourceRealtime";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";

export function QueueDetailPage() {
  const { t } = useTranslation(["queues", "common"]);
  const { guildId, queueId } = useParams({ strict: false }) as {
    guildId: string;
    queueId: string;
  };
  const parsedId = Number(queueId);
  const gp = useGuildPath();

  const queueQuery = useQueue(Number.isFinite(parsedId) ? parsedId : null);
  const queue = queueQuery.data;
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(queue?.initiative_id);

  // Track recently viewed queues for the layout header tabs bar.
  const recordViewMutation = useRecordRecentView("queue", Number(guildId));
  const viewedQueueId = queue?.id;
  useReadOnOpen(Tool.queue, viewedQueueId);
  useEffect(() => {
    if (!viewedQueueId) return;
    recordViewMutation.mutate(viewedQueueId);
  }, [viewedQueueId, recordViewMutation.mutate]);

  // Per-queue view preference (list vs. on-deck), persisted to local storage.
  const [view, setView] = useQueueView(parsedId);

  // Turn controls just fire the mutation. The optimistic cache write happens
  // synchronously in the hook's `onMutate`; the On Deck component watches
  // the resulting queue prop and wraps its own re-render in a View
  // Transition. That way the animation plays for local clicks, the
  // mutation's server response, *and* WebSocket-driven refetches when
  // another user advances the queue.

  // Connect WebSocket for live updates
  useQueueRealtime(Number.isFinite(parsedId) ? parsedId : null);

  // Queue name editing
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState("");

  const updateQueue = useUpdateQueue(parsedId, {
    onSuccess: () => {
      toast.success(t("queueUpdated"));
      setEditingName(false);
    },
  });

  const handleNameSave = () => {
    const trimmed = nameValue.trim();
    if (!trimmed || trimmed === queue?.name) {
      setEditingName(false);
      return;
    }
    updateQueue.mutate({ name: trimmed });
  };

  // Turn controls
  const startQueue = useStartQueue(parsedId, {
    onSuccess: () => toast.success(t("queueStarted")),
  });
  const stopQueue = useStopQueue(parsedId, {
    onSuccess: () => toast.success(t("queueStopped")),
  });
  const advanceTurn = useAdvanceTurn(parsedId);
  const previousTurn = usePreviousTurn(parsedId);
  const resetQueue = useResetQueue(parsedId, {
    onSuccess: () => toast.success(t("queueReset")),
  });
  const setActiveItem = useSetActiveItem(parsedId);
  const holdCurrent = useHoldCurrent(parsedId, {
    onSuccess: () => toast.success(t("queueHeld")),
  });
  const releaseHeld = useReleaseHeld(parsedId, {
    onSuccess: () => toast.success(t("queueReleased")),
  });

  const isControlLoading =
    startQueue.isPending ||
    stopQueue.isPending ||
    advanceTurn.isPending ||
    previousTurn.isPending ||
    resetQueue.isPending ||
    holdCurrent.isPending ||
    releaseHeld.isPending;

  // Item dialogs
  const [addItemOpen, setAddItemOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<QueueItemRead | null>(null);

  const canEdit = Boolean(queue?.can.edit);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canEdit ? { run: () => setAddItemOpen(true), label: t("addItem") } : null
  );

  // Sort items by position descending (highest initiative goes first)
  const sortedItems = useMemo(() => {
    if (!queue?.items) return [];
    return [...queue.items].sort((a, b) => b.position - a.position);
  }, [queue?.items]);

  // Error / loading states
  if (queueQuery.isLoading) {
    return (
      <SkeletonRegion label={t("loadingQueue")}>
        <DetailPageSkeleton actions={3}>
          <ListSkeleton rows={5} rowClassName="rounded-lg border bg-card p-3" />
        </DetailPageSkeleton>
      </SkeletonRegion>
    );
  }

  if (queueQuery.isError || !queue) {
    return (
      <ToolAccessStatus
        error={queueQuery.error}
        keys="queues:"
        backTo={gp(toolListRoute(Tool.queue, initiativeId))}
        backLabel={t("backToQueues")}
      />
    );
  }

  const currentItemId = queue.current_item?.id ?? null;

  return (
    <div className="space-y-6">
      {/* Breadcrumb header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ToolBreadcrumb
          tool={Tool.queue}
          initiativeId={queue.initiative_id}
          trail={[{ label: queue.name }]}
        />

        <div className="flex items-center gap-2">
          <Badge variant={queue.is_active ? "default" : "secondary"}>
            {queue.is_active ? t("active") : t("inactive")}
          </Badge>
          {canEdit && (
            <Button variant="outline" size="sm" asChild>
              <Link
                to={gp(toolSettingsRoute(Tool.queue, initiativeId, queue.id))}
                className="inline-flex items-center gap-2"
              >
                <Settings className="h-4 w-4" />
                {t("settings")}
              </Link>
            </Button>
          )}
        </div>
      </div>

      {/* Editable queue name */}
      <div className="space-y-2">
        {editingName ? (
          <div className="flex items-center gap-2">
            <Input
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              placeholder={t("namePlaceholder")}
              className="font-semibold text-2xl"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") handleNameSave();
                if (e.key === "Escape") setEditingName(false);
              }}
              onBlur={handleNameSave}
            />
          </div>
        ) : (
          <h1
            className="font-semibold text-2xl tracking-tight"
            role={canEdit ? "button" : undefined}
            tabIndex={canEdit ? 0 : undefined}
            onClick={() => {
              if (canEdit) {
                setNameValue(queue.name);
                setEditingName(true);
              }
            }}
            onKeyDown={(e) => {
              if (canEdit && (e.key === "Enter" || e.key === " ")) {
                setNameValue(queue.name);
                setEditingName(true);
              }
            }}
          >
            {queue.name}
          </h1>
        )}
        {queue.description && <p className="text-muted-foreground text-sm">{queue.description}</p>}
      </div>

      {/* Queue Controls */}
      <QueueControls
        queue={queue}
        onStart={() => startQueue.mutate()}
        onStop={() => stopQueue.mutate()}
        onNext={() => advanceTurn.mutate()}
        onPrevious={() => previousTurn.mutate()}
        onReset={() => resetQueue.mutate()}
        onHold={() => holdCurrent.mutate()}
        isLoading={isControlLoading}
      />

      {/* Items list */}
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-medium text-lg">
            {t("items")} ({sortedItems.length})
          </h2>
          <div className="flex items-center gap-2">
            <QueueViewToggle view={view} onChange={setView} />
            {canEdit && (
              <Button variant="outline" size="sm" onClick={() => setAddItemOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("addItem")}
              </Button>
            )}
          </div>
        </div>

        {sortedItems.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>{t("noItems")}</CardTitle>
              <CardDescription>{t("noItemsDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              {canEdit && (
                <Button onClick={() => setAddItemOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("addItem")}
                </Button>
              )}
            </CardContent>
          </Card>
        ) : view === "on-deck" ? (
          <QueueTimeline
            queue={queue}
            onEdit={(editItem) => setEditingItem(editItem)}
            onSetActive={(itemId) => {
              if (canEdit && queue.is_active) {
                setActiveItem.mutate(itemId);
              }
            }}
            onAct={(itemId, reposition) => {
              if (canEdit) {
                releaseHeld.mutate({ itemId, reposition });
              }
            }}
          />
        ) : (
          <div className="space-y-2">
            {sortedItems.map((item) => (
              <QueueItemRow
                key={item.id}
                item={item}
                isActive={item.id === currentItemId}
                onEdit={(editItem) => setEditingItem(editItem)}
                onSetActive={(itemId) => {
                  if (canEdit && queue.is_active) {
                    setActiveItem.mutate(itemId);
                  }
                }}
                actionButton={
                  canEdit && item.held_at_round !== null ? (
                    <ActHeldButton
                      itemId={item.id}
                      onAct={(id, reposition) => releaseHeld.mutate({ itemId: id, reposition })}
                    />
                  ) : undefined
                }
              />
            ))}
          </div>
        )}
      </div>

      <ToolRelationsPanel
        tool={Tool.queue}
        entity={queue}
        canEdit={canEdit}
        entityTitle={queue?.name}
      />

      <ToolCommentsPanel tool={Tool.queue} entity={queue} canModerate={canEdit} />

      {/* Add Item Dialog */}
      <AddQueueItemDialog
        open={addItemOpen}
        onOpenChange={setAddItemOpen}
        queueId={parsedId}
        initiativeId={queue.initiative_id}
      />

      {/* Edit Item Dialog */}
      {editingItem && (
        <EditQueueItemDialog
          open={editingItem !== null}
          onOpenChange={(open) => {
            if (!open) setEditingItem(null);
          }}
          queueId={parsedId}
          initiativeId={queue.initiative_id}
          item={editingItem}
          readOnly={!canEdit}
        />
      )}
    </div>
  );
}
