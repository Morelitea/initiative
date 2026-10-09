/**
 * Holding something for the platform, from the operations case working it.
 *
 * A platform moderator under a `moderate` grant on the community: the content
 * is kept exactly as it is, out of the whole community's sight, until they
 * release it. A community's own moderators hand a report over hidden from its
 * card instead (`SendToPlatformDialog`).
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  emptyHoldWhy,
  HoldFields,
  holdWhyBody,
  holdWhyReady,
} from "@/components/moderation/HoldFields";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePlaceHold } from "@/hooks/useHolds";
import { toast } from "@/lib/mascotToast";

export interface HoldDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The community the content is in. */
  communityId: number;
  /** A `SearchEntityType` value, and the id. */
  targetType: string;
  targetId: number;
  /** The operations case it is held under. */
  caseTaskId?: number;
  onHeld?: () => void;
}

export const HoldDialog = ({
  open,
  onOpenChange,
  communityId,
  targetType,
  targetId,
  caseTaskId,
  onHeld,
}: HoldDialogProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [why, setWhy] = useState(emptyHoldWhy);

  const place = usePlaceHold(communityId, {
    onSuccess: () => {
      toast.success(t("hold.held"));
      onOpenChange(false);
      setWhy(emptyHoldWhy());
      onHeld?.();
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("hold.title")}</DialogTitle>
          <DialogDescription>{t("hold.description")}</DialogDescription>
        </DialogHeader>
        <HoldFields value={why} onChange={setWhy} />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={!holdWhyReady(why) || place.isPending}
            onClick={() =>
              place.mutate({
                target_type: targetType,
                target_id: targetId,
                ...holdWhyBody(why),
                case_task_id: caseTaskId ?? null,
              })
            }
          >
            {t("hold.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
