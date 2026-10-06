import { Copy, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { QueueItemRead } from "@/api/generated/initiativeAPI.schemas";
import { QueueItemFields } from "@/components/initiativeTools/queues/QueueItemFields";
import { useQueueItemForm } from "@/components/initiativeTools/queues/useQueueItemForm";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useDeleteQueueItem,
  useDuplicateQueueItem,
  useSetQueueItemLinks,
  useUpdateQueueItem,
} from "@/hooks/useQueues";
import { toast } from "@/lib/mascotToast";
import { sameIds } from "@/lib/relationships";
import type { DialogProps } from "@/types/dialog";

type EditQueueItemDialogProps = DialogProps & {
  queueId: number;
  initiativeId: number;
  item: QueueItemRead;
  readOnly?: boolean;
  onSuccess?: () => void;
};

export const EditQueueItemDialog = ({
  open,
  onOpenChange,
  queueId,
  initiativeId,
  item,
  readOnly = false,
  onSuccess,
}: EditQueueItemDialogProps) => {
  const { t } = useTranslation(["queues", "common"]);

  const form = useQueueItemForm({ open, initiativeId, item });
  const {
    label,
    position,
    color,
    notes,
    isVisible,
    selectedTags,
    userId,
    links,
    initialLinks,
    linksLoading,
  } = form;

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const setLinksMutation = useSetQueueItemLinks(queueId);

  const updateItem = useUpdateQueueItem(queueId, {
    onSuccess: async (_data, vars) => {
      // Awaited: an item's links are saved by a request of their own, and
      // reporting the save before it lands would call it done while part of it
      // may still fail. A failure leaves the dialog open with the change still
      // in it, to be tried again.
      try {
        // One call for every kind of link, which works out per kind what moved.
        await setLinksMutation.mutateAsync({
          itemId: vars.itemId,
          links,
          previous: initialLinks,
        });
      } catch {
        // The hooks have already said what went wrong.
        onSuccess?.();
        return;
      }

      toast.success(t("itemUpdated"));
      onOpenChange(false);
      onSuccess?.();
    },
  });

  const deleteItem = useDeleteQueueItem(queueId, {
    onSuccess: () => {
      toast.success(t("itemRemoved"));
      setDeleteConfirmOpen(false);
      onOpenChange(false);
      onSuccess?.();
    },
  });

  const duplicateItem = useDuplicateQueueItem(queueId, {
    onSuccess: () => {
      toast.success(t("common:subToolDuplicate.done"));
      onOpenChange(false);
      onSuccess?.();
    },
  });

  const isSaving = updateItem.isPending;
  const isDeleting = deleteItem.isPending;
  // Not until the links have arrived: saving diffs what is on screen against
  // what was loaded, and an empty screen would read as "take them all off".
  const canSubmit = !readOnly && label.trim() && !isSaving && !isDeleting && !linksLoading;

  const handleSubmit = () => {
    const trimmedLabel = label.trim();
    if (!trimmedLabel) return;
    // Tags are compared as sets: the rows are rebuilt on every read, so the
    // order they arrive in says nothing about whether they changed.
    const tagIds = selectedTags.map((tg) => tg.id);
    const tagsChanged = !sameIds(
      tagIds,
      item.tags.map((tg) => tg.id)
    );
    updateItem.mutate({
      itemId: item.id,
      data: {
        label: trimmedLabel,
        position: position ? Number(position) : undefined,
        color: color || undefined,
        notes: notes.trim() || null,
        is_visible: isVisible,
        user_id: userId,
        ...(tagsChanged ? { tag_ids: tagIds } : {}),
      },
    });
  };

  const handleDelete = () => {
    deleteItem.mutate(item.id);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("editItem")}</DialogTitle>
            <DialogDescription>{item.label}</DialogDescription>
          </DialogHeader>

          <QueueItemFields
            form={form}
            queueId={queueId}
            initiativeId={initiativeId}
            item={item}
            readOnly={readOnly}
            onEnter={canSubmit ? handleSubmit : undefined}
          />

          {!readOnly && (
            <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={() => setDeleteConfirmOpen(true)}
                  disabled={isSaving || isDeleting}
                >
                  <Trash2 className="h-4 w-4" />
                  {t("removeItem")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => duplicateItem.mutate(item.id)}
                  disabled={isSaving || isDeleting || duplicateItem.isPending}
                >
                  <Copy className="h-4 w-4" />
                  {duplicateItem.isPending
                    ? t("common:subToolDuplicate.duplicating")
                    : t("common:subToolDuplicate.action")}
                </Button>
              </div>
              <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
                {isSaving ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t("saving")}
                  </>
                ) : (
                  t("common:save")
                )}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("removeItem")}
        description={t("removeItemConfirm")}
        confirmLabel={t("removeItem")}
        cancelLabel={t("common:cancel")}
        onConfirm={handleDelete}
        isLoading={isDeleting}
        destructive
      />
    </>
  );
};
