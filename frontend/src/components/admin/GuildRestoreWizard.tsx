/**
 * Bring a deleted community back.
 *
 * Deleting a community keeps it — everything stays where it is until the
 * retention window runs out — so restoring is mostly a matter of deciding what
 * it comes back as. Two questions, and only the ones that apply:
 *
 * - **Who runs it.** Asked only when the roster no longer holds the seat that
 *   configures a community, which is what a deletion that cleared the roster
 *   leaves behind (the operator path that unblocks deleting a user). Restoring
 *   one nobody can administer produces a community that is live and
 *   unreachable, so this cannot be skipped.
 * - **What status.** The operator says, rather than the community remembering:
 *   one suspended for nonpayment and then deleted should not come back
 *   trading.
 *
 * What does not come back is its app connections. Those were revoked when it
 * was deleted — the community had withdrawn their authorization — and its
 * admins reconnect them.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformGuildStorageRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildStatus } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { WizardDialog } from "@/components/ui/wizard-dialog";
import { usePlatformUsers } from "@/hooks/useAdmin";
import { useRestoreGuild } from "@/hooks/useSettings";
import { useWizard } from "@/hooks/useWizard";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { OPERATOR_SETTABLE_STATUSES } from "@/lib/guildStatus";

type Step = "seat" | "status";

export const GuildRestoreWizard = ({
  guild,
  open,
  onOpenChange,
}: {
  guild: PlatformGuildStorageRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  // The seat step is skipped entirely when there is somebody to run it, so the
  // wizard starts wherever the first real question is.
  const needsSeat = !guild.has_seat;
  const wizard = useWizard<Step>(needsSeat ? "seat" : "status");
  const [seatUserId, setSeatUserId] = useState<string>("");
  const [status, setStatus] = useState<GuildStatus>(GuildStatus.active);

  // Only fetched when it is actually going to be asked — this is every account
  // on the deployment, and most restores never need it.
  const usersQuery = usePlatformUsers({ enabled: open && needsSeat });

  const restore = useRestoreGuild({
    onSuccess: (row) => {
      toast.success(t("guilds.restore.done", { name: row.name }));
      onOpenChange(false);
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:guilds.restore.error"));
    },
  });

  const submit = () =>
    restore.mutate({
      guildId: guild.id,
      data: {
        status,
        seat_user_id: needsSeat ? Number(seatUserId) : null,
      },
    });

  const userItems = (usersQuery.data ?? []).map((user) => ({
    value: String(user.id),
    label: user.full_name ? `${user.full_name} (${user.username})` : user.username,
    hint: user.email,
  }));

  if (wizard.step === "seat") {
    return (
      <WizardDialog
        open={open}
        onOpenChange={onOpenChange}
        title={t("guilds.restore.title", { name: guild.name })}
        description={t("guilds.restore.seatDescription")}
        progress={{ current: 1, total: 2 }}
      >
        <div className="space-y-2">
          <Label htmlFor="guild-restore-seat">{t("guilds.restore.seatLabel")}</Label>
          <SearchableCombobox
            className="w-full"
            value={seatUserId}
            onValueChange={setSeatUserId}
            items={userItems}
            disabled={usersQuery.isLoading}
            placeholder={
              usersQuery.isLoading ? t("common:loading") : t("guilds.restore.seatPlaceholder")
            }
            emptyMessage={t("guilds.restore.seatEmpty")}
            aria-label={t("guilds.restore.seatLabel")}
          />
          <p className="text-muted-foreground text-xs">{t("guilds.restore.seatHelp")}</p>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button onClick={() => wizard.go("status")} disabled={seatUserId === ""}>
            {t("common:next")}
          </Button>
        </div>
      </WizardDialog>
    );
  }

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("guilds.restore.title", { name: guild.name })}
      description={t("guilds.restore.statusDescription")}
      progress={needsSeat ? { current: 2, total: 2 } : undefined}
      onBack={needsSeat ? wizard.back : undefined}
      backLabel={t("common:back")}
      backDisabled={restore.isPending}
    >
      <div className="space-y-2">
        <Label htmlFor="guild-restore-status">{t("guilds.restore.statusLabel")}</Label>
        <Select
          value={status}
          onValueChange={(value) => setStatus(value as GuildStatus)}
          disabled={restore.isPending}
        >
          <SelectTrigger id="guild-restore-status" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OPERATOR_SETTABLE_STATUSES.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`guilds.status.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("guilds.restore.appsNote")}</p>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={() => onOpenChange(false)} disabled={restore.isPending}>
          {t("common:cancel")}
        </Button>
        <Button onClick={submit} disabled={restore.isPending}>
          {restore.isPending ? t("common:submitting") : t("guilds.restore.confirm")}
        </Button>
      </div>
    </WizardDialog>
  );
};
