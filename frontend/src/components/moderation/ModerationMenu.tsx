/**
 * A moderator's actions on one thing, wherever it is shown.
 *
 * Offered to the moderation set of the thing's initiative — its community's
 * admins and the people with Full access there — and to nobody else: the
 * caller passes whether this reader is one, from what the server already
 * said about them (`initiative.can.moderate`, a thread's `can_moderate`).
 * The server refuses the rest anyway.
 *
 * - **Remove…** takes it down, with a reason its author is told.
 * - **Lock comments** closes its thread to everyone but the moderators, for
 *   things a thread hangs off. Its owner can't reopen it.
 * - **Clear reactions**, for things people react to.
 * - **Hold for the platform** keeps it exactly as it is, out of everyone's
 *   sight, the moderator's included, until the platform releases it.
 */
import { Shield } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ModerationAct } from "@/api/generated/initiativeAPI.schemas";
import { HoldDialog } from "@/components/moderation/HoldDialog";
import { RemovalDialog } from "@/components/moderation/RemovalDialog";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useModerate } from "@/hooks/useModeration";
import { toast } from "@/lib/mascotToast";

export interface ModerationMenuProps {
  /** A `SearchEntityType` value, and which one. */
  targetType: string;
  targetId: number;
  /** Whether this reader moderates the thing's initiative. Nothing renders
   *  otherwise. */
  canModerate: boolean;
  /** Its thread's lock, for things a thread hangs off. Left out for things
   *  with no thread, which then offer no lock. */
  commentsLocked?: boolean;
  /** Whether people react to it. */
  reactable?: boolean;
  /** Defaults to the community the reader is standing in. */
  communityId?: number | null;
  /** Once it has been taken down or held — to close the sheet it was opened
   *  from, say. */
  onGone?: () => void;
  className?: string;
}

export const ModerationMenu = ({
  targetType,
  targetId,
  canModerate,
  commentsLocked,
  reactable = false,
  communityId,
  onGone,
  className,
}: ModerationMenuProps) => {
  const { t } = useTranslation(["moderation", "common"]);
  const activeCommunityId = useActiveCommunityId();
  const community = communityId ?? activeCommunityId ?? 0;
  const [removing, setRemoving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [holding, setHolding] = useState(false);
  const act = useModerate(community);

  if (!canModerate || !community) return null;

  const target = { target_type: targetType, target_id: targetId };
  const lockable = commentsLocked !== undefined;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={className}
            aria-label={t("menu.label")}
          >
            <Shield className="h-4 w-4" aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>{t("menu.label")}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setRemoving(true)}>{t("menu.remove")}</DropdownMenuItem>
          {lockable && (
            <DropdownMenuItem
              disabled={act.isPending}
              onSelect={() =>
                act.mutate(
                  {
                    ...target,
                    act: commentsLocked
                      ? ModerationAct.unlock_comments
                      : ModerationAct.lock_comments,
                  },
                  {
                    onSuccess: () =>
                      toast.success(commentsLocked ? t("menu.unlocked") : t("menu.locked")),
                  }
                )
              }
            >
              {commentsLocked ? t("menu.unlock") : t("menu.lock")}
            </DropdownMenuItem>
          )}
          {reactable && (
            <DropdownMenuItem onSelect={() => setClearing(true)}>
              {t("menu.clearReactions")}
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-destructive" onSelect={() => setHolding(true)}>
            {t("menu.hold")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <RemovalDialog
        open={removing}
        onOpenChange={setRemoving}
        targetType={targetType}
        pending={act.isPending}
        onConfirm={({ reason, note }) =>
          act.mutate(
            { ...target, act: ModerationAct.remove, reason, note },
            {
              onSuccess: () => {
                setRemoving(false);
                toast.success(t("remove.done"));
                onGone?.();
              },
            }
          )
        }
      />
      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title={t("menu.clearTitle")}
        description={t("menu.clearDescription")}
        confirmLabel={t("menu.clearReactions")}
        destructive
        isLoading={act.isPending}
        onConfirm={() =>
          act.mutate(
            { ...target, act: ModerationAct.clear_reactions },
            {
              onSuccess: () => {
                setClearing(false);
                toast.success(t("menu.cleared"));
              },
            }
          )
        }
      />
      <HoldDialog
        open={holding}
        onOpenChange={setHolding}
        communityId={community}
        targetType={targetType}
        targetId={targetId}
        onHeld={onGone}
      />
    </>
  );
};
