import { Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { EntityLinkField } from "@/components/entities/EntityLinkField";
import { useQueueItemForm } from "@/components/initiativeTools/queues/useQueueItemForm";
import { MemberSelect } from "@/components/members/MemberSearchSelect";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
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
import { useCreateQueueItem, useSetQueueItemLinks } from "@/hooks/useQueues";
import { toast } from "@/lib/chesterToast";
import type { LinkedRef } from "@/lib/relationships";
import type { DialogProps } from "@/types/dialog";

type AddQueueItemDialogProps = DialogProps & {
  queueId: number;
  initiativeId: number;
  onSuccess?: () => void;
};

export const AddQueueItemDialog = ({
  open,
  onOpenChange,
  queueId,
  initiativeId,
  onSuccess,
}: AddQueueItemDialogProps) => {
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
  } = useQueueItemForm({ open, initiativeId });

  const setLinksMutation = useSetQueueItemLinks(queueId);

  /**
   * The item this sitting already made, if it made one.
   *
   * An item is created first and its links written against the id that comes
   * back, so a link that fails leaves a real item behind. Pressing Add again
   * has to finish *that* item rather than make a second one — a link failing
   * twice would otherwise leave two items behind it.
   */
  const created = useRef<number | null>(null);
  /**
   * What the last attempt asked for.
   *
   * A retry has to undo as well as finish: links are written a kind at a time,
   * so an earlier kind may already be on the item while a later one failed —
   * and if somebody takes one of those off before trying again, the item is
   * still carrying it. Handing the previous attempt back as what is already
   * there is what lets the difference be worked out.
   */
  const attempted = useRef<LinkedRef[]>([]);
  useEffect(() => {
    created.current = null;
    attempted.current = [];
  }, [open]);

  /** Write the links, and only then call the whole thing done. */
  const finish = async (itemId: number) => {
    const retry = created.current !== null && attempted.current.length > 0;
    if (links.length > 0 || retry) {
      const previous = attempted.current;
      attempted.current = links;
      // A retry writes every kind rather than only the ones that look changed:
      // the kind that failed reads as unchanged against what was asked before.
      await setLinksMutation.mutateAsync({ itemId, links, previous, force: retry });
    }
    created.current = null;
    attempted.current = [];
    toast.success(t("itemAdded"));
    onOpenChange(false);
    onSuccess?.();
  };

  const createItem = useCreateQueueItem(queueId, {
    onSuccess: async (item) => {
      created.current = item.id;
      try {
        await finish(item.id);
      } catch {
        // `useSetQueueItemLinks` has already said what went wrong, and the
        // dialog stays open holding everything, ready to try the links again.
        onSuccess?.();
      }
    },
  });

  const isAdding = createItem.isPending || setLinksMutation.isPending;
  const canSubmit = label.trim() && !isAdding;

  const handleSubmit = () => {
    const trimmedLabel = label.trim();
    if (!trimmedLabel) return;

    const already = created.current;
    if (already !== null) {
      // The item is there; it was its links that did not land.
      void finish(already).catch(() => {});
      return;
    }

    createItem.mutate({
      label: trimmedLabel,
      position: position ? Number(position) : undefined,
      color: color || undefined,
      notes: notes.trim() || undefined,
      is_visible: isVisible,
      tag_ids: selectedTags.length > 0 ? selectedTags.map((tg) => tg.id) : undefined,
      user_id: userId ?? undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-screen w-full overflow-y-auto rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("addItem")}</DialogTitle>
          <DialogDescription>{t("noItemsDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Label */}
          <div className="space-y-2">
            <Label htmlFor="add-item-label">{t("label")}</Label>
            <Input
              id="add-item-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t("labelPlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              autoFocus
            />
          </div>

          {/* Position (Initiative Roll) */}
          <div className="space-y-2">
            <Label htmlFor="add-item-position">{t("position")}</Label>
            <Input
              id="add-item-position"
              type="number"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
              placeholder="0"
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
            />
          </div>

          {/* Notes */}
          <div className="space-y-2">
            <Label htmlFor="add-item-notes">{t("notes")}</Label>
            <Textarea
              id="add-item-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t("notesPlaceholder")}
              rows={2}
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
            <Switch checked={isVisible} onCheckedChange={setIsVisible} aria-label={t("visible")} />
          </div>

          {/* Tags */}
          <div className="space-y-2">
            <Label>{t("tags")}</Label>
            <TagPicker
              selectedTags={selectedTags}
              onChange={setSelectedTags}
              placeholder={t("tags")}
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
                placeholder={t("selectUser")}
                emptyMessage={t("noUser")}
              />
              {userId !== null && (
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
              tasks-only one. No subject to leave out: the item does not exist
              yet. */}
          <EntityLinkField
            label={t("relations:groups.attached.title")}
            initiativeId={initiativeId}
            value={links}
            onChange={setLinks}
          />
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isAdding ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("adding")}
              </>
            ) : (
              t("addItem")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
