import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { Loader2, Plus, SearchX, Settings, ShieldAlert, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  useQueue,
  useUpdateQueue,
  useDeleteQueue,
  useAdvanceTurn,
  usePreviousTurn,
  useStartQueue,
  useStopQueue,
  useResetQueue,
  useSetActiveItem,
} from "@/hooks/useQueues";
import { useQueueRealtime } from "@/hooks/useQueueRealtime";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { getHttpStatus } from "@/lib/errorMessage";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { QueueControls } from "@/components/queues/QueueControls";
import { QueueItemRow } from "@/components/queues/QueueItemRow";
import { AddQueueItemDialog } from "@/components/queues/AddQueueItemDialog";
import { EditQueueItemDialog } from "@/components/queues/EditQueueItemDialog";
import type { QueueItemRead } from "@/api/generated/initiativeAPI.schemas";

export function QueueDetailPage() {
  const { t } = useTranslation(["queues", "common"]);
  const { queueId } = useParams({ strict: false }) as { queueId: string };
  const parsedId = Number(queueId);
  const navigate = useNavigate();
  const gp = useGuildPath();

  const queueQuery = useQueue(Number.isFinite(parsedId) ? parsedId : null);
  const queue = queueQuery.data;

  // Connect WebSocket for live updates
  useQueueRealtime(Number.isFinite(parsedId) ? parsedId : null);

  // Get initiative name for breadcrumb
  const initiativesQuery = useInitiatives();
  const initiativeName = useMemo(() => {
    if (!queue) return null;
    const initiative = initiativesQuery.data?.find((i) => i.id === queue.initiative_id);
    return initiative?.name ?? null;
  }, [queue, initiativesQuery.data]);

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

  // Delete queue
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const deleteQueue = useDeleteQueue({
    onSuccess: () => {
      toast.success(t("queueDeleted"));
      void navigate({ to: gp("/queues") });
    },
  });

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

  const isControlLoading =
    startQueue.isPending ||
    stopQueue.isPending ||
    advanceTurn.isPending ||
    previousTurn.isPending ||
    resetQueue.isPending;

  // Item dialogs
  const [addItemOpen, setAddItemOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<QueueItemRead | null>(null);

  const canEdit = queue?.my_permission_level === "owner" || queue?.my_permission_level === "write";

  // Sort items by position descending (highest initiative goes first)
  const sortedItems = useMemo(() => {
    if (!queue?.items) return [];
    return [...queue.items].sort((a, b) => b.position - a.position);
  }, [queue?.items]);

  // Error / loading states
  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (queueQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingQueue")}
      </div>
    );
  }

  if (queueQuery.isError || !queue) {
    const status = getHttpStatus(queueQuery.error);
    const backTo = gp("/queues");
    const backLabel = t("backToQueues");

    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("noAccess")}
          description={t("noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("notFound")}
        description={t("notFoundDescription")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  const currentItemId = queue.current_item?.id ?? null;

  return (
    <div className="space-y-6">
      {/* Breadcrumb header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Breadcrumb>
          <BreadcrumbList>
            {initiativeName && (
              <>
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <Link to={gp(`/initiatives/${queue.initiative_id}`)}>{initiativeName}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator />
              </>
            )}
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to={gp("/queues")}>{t("title")}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{queue.name}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex items-center gap-2">
          <Badge variant={queue.is_active ? "default" : "secondary"}>
            {queue.is_active ? t("active") : t("inactive")}
          </Badge>
          {canEdit && (
            <Button variant="ghost" size="sm" asChild>
              <Link to={gp(`/queues/${queue.id}/settings`)}>
                <Settings className="h-4 w-4" />
              </Link>
            </Button>
          )}
          {canEdit && (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleteConfirmOpen(true)}
            >
              <Trash2 className="h-4 w-4" />
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
              className="text-2xl font-semibold"
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
            className="text-2xl font-semibold tracking-tight"
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
        isLoading={isControlLoading}
      />

      {/* Items list */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">
            {t("items")} ({sortedItems.length})
          </h2>
          {canEdit && (
            <Button variant="outline" size="sm" onClick={() => setAddItemOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              {t("addItem")}
            </Button>
          )}
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
                  <Plus className="mr-1 h-4 w-4" />
                  {t("addItem")}
                </Button>
              )}
            </CardContent>
          </Card>
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
              />
            ))}
          </div>
        )}
      </div>

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
        />
      )}

      {/* Delete Queue Confirmation */}
      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("deleteQueue")}
        description={t("deleteQueueConfirm")}
        confirmLabel={t("deleteQueue")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => deleteQueue.mutate(parsedId)}
        isLoading={deleteQueue.isPending}
        destructive
      />
    </div>
  );
}
