import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { deleteUserApiV1GGuildIdUsersUserIdDelete } from "@/api/generated/users/users";
import { invalidateAllGuilds, invalidateGuildMembers } from "@/api/query-keys";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

interface RemoveGuildMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  userId: number | null;
  email: string;
  onSuccess?: () => void;
}

/**
 * Guild-admin counterpart to ``LeaveGuildDialog``, and just as plain: removing
 * someone ends their memberships and the access those carried.
 *
 * It asks nothing about their content because nothing has to be decided here.
 * Ownership is released as they go, and what they owned turns up in guild
 * settings under unowned content for an admin to claim whenever they like.
 */
export const RemoveGuildMemberDialog = ({
  open,
  onOpenChange,
  userId,
  email,
  onSuccess,
}: RemoveGuildMemberDialogProps) => {
  const { t } = useTranslation(["guilds", "common"]);
  const guildId = useActiveGuildId();
  const [removing, setRemoving] = useState(false);

  const handleRemove = async () => {
    if (userId === null) return;
    setRemoving(true);
    try {
      await deleteUserApiV1GGuildIdUsersUserIdDelete(guildId, userId);
      void invalidateGuildMembers();
      // The guild list carries member_count, which the seat counter reads.
      void invalidateAllGuilds();
      toast.success(t("removeMember.removed", { email }));
      onSuccess?.();
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to remove member", err);
      toast.error(getErrorMessage(err, "guilds:removeMember.failedToRemove"));
    } finally {
      setRemoving(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("removeMember.title")}</AlertDialogTitle>
        </AlertDialogHeader>
        <div className="space-y-3">
          <AlertDialogDescription>
            {t("removeMember.description", { email })}
          </AlertDialogDescription>
          <p className="text-muted-foreground text-sm">{t("removeMember.ownershipReleased")}</p>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={removing}>{t("common:cancel")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleRemove}
            disabled={removing}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {removing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("removeMember.removing")}
              </>
            ) : (
              t("removeMember.removeButton")
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
