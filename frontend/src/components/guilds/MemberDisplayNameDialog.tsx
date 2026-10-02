import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
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
import { useSetMemberDisplayName } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { DialogProps } from "@/types/dialog";

/** The longest name the server takes (`MEMBER_DISPLAY_NAME_MAX_LENGTH`). */
const MAX_LENGTH = 64;

interface MemberDisplayNameDialogProps extends DialogProps {
  guildId: number;
  /** The member an administrator is naming; left out, the caller names themselves. */
  member?: { id: number; name: string };
  /** The name as it is set now, or null when none is. */
  current: string | null | undefined;
}

/**
 * What somebody is called in one community. Empty clears it, and the
 * community's usual name for them shows again.
 */
export const MemberDisplayNameDialog = ({
  guildId,
  member,
  current,
  open,
  onOpenChange,
}: MemberDisplayNameDialogProps) => {
  const { t } = useTranslation(["guilds", "common"]);
  const [value, setValue] = useState(current ?? "");
  const setDisplayName = useSetMemberDisplayName({
    onSuccess: () => {
      toast.success(t("displayName.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(getErrorMessage(error, "guilds:displayName.saveFailed")),
  });

  useEffect(() => {
    if (open) setValue(current ?? "");
  }, [open, current]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setDisplayName.mutate({
      guildId,
      userId: member?.id,
      displayName: value.trim() || null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {member
              ? t("displayName.memberTitle", { name: member.name })
              : t("displayName.ownTitle")}
          </DialogTitle>
          <DialogDescription>
            {member ? t("displayName.memberDescription") : t("displayName.ownDescription")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="member-display-name">{t("displayName.label")}</Label>
            <Input
              id="member-display-name"
              value={value}
              maxLength={MAX_LENGTH}
              onChange={(event) => setValue(event.target.value)}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={setDisplayName.isPending}>
              {t("common:save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
