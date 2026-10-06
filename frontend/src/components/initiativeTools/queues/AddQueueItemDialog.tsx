import { Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { QueueItemFields } from "@/components/initiativeTools/queues/QueueItemFields";
import { useQueueItemForm } from "@/components/initiativeTools/queues/useQueueItemForm";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateQueueItem, useSetQueueItemLinks } from "@/hooks/useQueues";
import { toast } from "@/lib/mascotToast";
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
  const { t } = useTranslation(["queues", "common"]);

  const form = useQueueItemForm({ open, initiativeId });
  const { label, position, color, notes, isVisible, selectedTags, userId, links } = form;

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
      <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("addItem")}</DialogTitle>
          <DialogDescription className="sr-only">{t("noItemsDescription")}</DialogDescription>
        </DialogHeader>

        <QueueItemFields
          form={form}
          queueId={queueId}
          initiativeId={initiativeId}
          onEnter={canSubmit ? handleSubmit : undefined}
        />

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
