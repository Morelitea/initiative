import { Loader2, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type QueueItemRead, SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { EntityLinkField } from "@/components/entities/EntityLinkField";
import { useQueueItemForm } from "@/components/initiativeTools/queues/useQueueItemForm";
import { MemberSelect } from "@/components/members/MemberSearchSelect";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  useDeleteQueueItem,
  useSetQueueItemLinks,
  useSetQueueItemTags,
  useUpdateQueueItem,
} from "@/hooks/useQueues";
import { toast } from "@/lib/chesterToast";
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
  const { t } = useTranslation(["queues", "common", "relations"]);

  const {
    label,
    setLabel,
    position,
    setPosition,
    color,
    setColor,
    notes,
    setNotes,
    isVisible,
    setIsVisible,
    selectedTags,
    setSelectedTags,
    userId,
    setUserId,
    links,
    setLinks,
    initialLinks,
    linksLoading,
    selectedUser,
  } = useQueueItemForm({ open, initiativeId, item });

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const setTags = useSetQueueItemTags(queueId);
  const setLinksMutation = useSetQueueItemLinks(queueId);

  const updateItem = useUpdateQueueItem(queueId, {
    onSuccess: async (_data, vars) => {
      // Tags are compared as sets: the rows are rebuilt on every read, so the
      // order they arrive in says nothing about whether they changed.
      const newTagIds = selectedTags.map((tg) => tg.id);
      // Awaited, both of them: an item's tags and its links are saved by
      // requests of their own, and reporting the save before those land would
      // call it done while part of it may still fail. A failure leaves the
      // dialog open with the change still in it, to be tried again.
      try {
        if (
          !sameIds(
            newTagIds,
            item.tags.map((tg) => tg.id)
          )
        ) {
          await setTags.mutateAsync({ itemId: vars.itemId, tagIds: newTagIds });
        }
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

  const isSaving = updateItem.isPending;
  const isDeleting = deleteItem.isPending;
  // Not until the links have arrived: saving diffs what is on screen against
  // what was loaded, and an empty screen would read as "take them all off".
  const canSubmit = !readOnly && label.trim() && !isSaving && !isDeleting && !linksLoading;

  const handleSubmit = () => {
    const trimmedLabel = label.trim();
    if (!trimmedLabel) return;
    updateItem.mutate({
      itemId: item.id,
      data: {
        label: trimmedLabel,
        position: position ? Number(position) : undefined,
        color: color || undefined,
        notes: notes.trim() || undefined,
        is_visible: isVisible,
        user_id: userId,
      },
    });
  };

  const handleDelete = () => {
    deleteItem.mutate(item.id);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-screen w-full overflow-y-auto rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("editItem")}</DialogTitle>
            <DialogDescription>{item.label}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Label */}
            <div className="space-y-2">
              <Label htmlFor="edit-item-label">{t("label")}</Label>
              <Input
                id="edit-item-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t("labelPlaceholder")}
                disabled={readOnly}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && canSubmit) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
              />
            </div>

            {/* Position (Initiative Roll) */}
            <div className="space-y-2">
              <Label htmlFor="edit-item-position">{t("position")}</Label>
              <Input
                id="edit-item-position"
                type="number"
                value={position}
                onChange={(e) => setPosition(e.target.value)}
                placeholder="0"
                disabled={readOnly}
              />
              <p className="text-muted-foreground text-xs">{t("positionHelp")}</p>
            </div>

            {/* Color */}
            <div className="space-y-2">
              <Label>{t("color")}</Label>
              <ColorPickerPopover
                value={color}
                onChange={setColor}
                triggerLabel={t("color")}
                className="h-9"
                disabled={readOnly}
              />
            </div>

            {/* Notes */}
            <div className="space-y-2">
              <Label htmlFor="edit-item-notes">{t("notes")}</Label>
              <Textarea
                id="edit-item-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t("notesPlaceholder")}
                rows={2}
                disabled={readOnly}
              />
            </div>

            {/* Visible toggle */}
            <div className="flex items-center justify-between rounded-lg border bg-muted/40 p-3">
              <div>
                <p className="font-medium text-sm">{t("visible")}</p>
                <p className="text-muted-foreground text-xs">
                  {isVisible ? t("visible") : t("hidden")}
                </p>
              </div>
              <Switch
                checked={isVisible}
                onCheckedChange={setIsVisible}
                aria-label={t("visible")}
                disabled={readOnly}
              />
            </div>

            {/* Tags */}
            <div className="space-y-2">
              <Label>{t("tags")}</Label>
              <TagPicker
                selectedTags={selectedTags}
                onChange={setSelectedTags}
                placeholder={t("tags")}
                disabled={readOnly}
              />
            </div>

            {/* Linked User */}
            <div className="space-y-2">
              <Label>{t("linkedUser")}</Label>
              <div className="flex items-center gap-2">
                <MemberSelect
                  scope={{ type: "initiative", initiativeId }}
                  value={userId}
                  onChange={setUserId}
                  selectedUser={selectedUser}
                  placeholder={t("selectUser")}
                  emptyMessage={t("noUser")}
                  disabled={readOnly}
                />
                {userId !== null && !readOnly && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setUserId(null)}
                    className="shrink-0"
                  >
                    {t("clearUser")}
                  </Button>
                )}
              </div>
            </div>

            {/* One list, any kind — in place of a documents-only picker beside a
                tasks-only one. */}
            <EntityLinkField
              label={t("relations:groups.attached.title")}
              subject={{ type: SearchEntityType.queue_item, id: item.id }}
              initiativeId={initiativeId}
              value={links}
              onChange={setLinks}
              readOnly={readOnly}
            />
          </div>

          {!readOnly && (
            <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
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
