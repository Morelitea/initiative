import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import {
  checkLeaveEligibilityApiV1GuildsGuildIdLeaveEligibilityGet,
  leaveGuildApiV1GuildsGuildIdLeaveDelete,
} from "@/api/generated/guilds/guilds";
import type {
  GuildRead,
  LeaveGuildEligibilityResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import type { DialogProps } from "@/types/dialog";

interface LeaveGuildDialogProps extends DialogProps {
  guild: GuildRead;
}

/**
 * Being the guild's last admin is the only thing that stops someone leaving.
 * Content they own is released on the way out — left unowned for a guild admin
 * to claim from guild settings — so there is nothing to hand over first.
 */
export const LeaveGuildDialog = ({ guild, open, onOpenChange }: LeaveGuildDialogProps) => {
  const { t } = useTranslation(["guilds", "common"]);
  const { guilds, refreshGuilds, switchGuild, activeGuildId } = useGuilds();
  const [loading, setLoading] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const [eligibility, setEligibility] = useState<LeaveGuildEligibilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setEligibility(null);
      setError(null);
      setLoading(true);
      return;
    }

    const checkEligibility = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = (await checkLeaveEligibilityApiV1GuildsGuildIdLeaveEligibilityGet(
          guild.id
        )) as unknown as LeaveGuildEligibilityResponse;
        setEligibility(data);
      } catch (err) {
        console.error("Failed to check leave eligibility", err);
        setError(t("leave.failedToCheckEligibility"));
      } finally {
        setLoading(false);
      }
    };

    void checkEligibility();
  }, [open, guild.id, t]);

  const hasHardBlocker = !!eligibility && eligibility.is_last_admin;

  const handleLeave = async () => {
    setLeaving(true);
    try {
      await leaveGuildApiV1GuildsGuildIdLeaveDelete(guild.id);

      // Switch to another guild if leaving the active one
      if (activeGuildId === guild.id) {
        const otherGuild = guilds.find((g) => g.id !== guild.id);
        if (otherGuild) {
          await switchGuild(otherGuild.id);
        }
      }

      await refreshGuilds();
      toast.success(t("leave.leftGuild", { name: guild.name }));
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to leave guild", err);
      toast.error(t("leave.failedToLeave"));
    } finally {
      setLeaving(false);
    }
  };

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      );
    }

    if (error) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t("common:error")}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      );
    }

    if (!eligibility) {
      return null;
    }

    if (hasHardBlocker) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t("leave.cannotLeaveTitle")}</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-inside list-disc space-y-1">
              <li>{t("leave.lastAdminWarning")}</li>
            </ul>
          </AlertDescription>
        </Alert>
      );
    }

    return (
      <div className="space-y-3">
        <AlertDialogDescription>
          <Trans
            i18nKey="leave.description"
            ns="guilds"
            values={{ name: guild.name }}
            components={{ bold: <strong /> }}
          />
        </AlertDialogDescription>
        <p className="text-muted-foreground text-sm">{t("leave.ownershipReleased")}</p>
      </div>
    );
  };

  const canShowLeaveButton = !loading && !error && eligibility && !hasHardBlocker;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("leave.title", { name: guild.name })}</AlertDialogTitle>
        </AlertDialogHeader>
        {renderContent()}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={leaving}>{t("common:cancel")}</AlertDialogCancel>
          {canShowLeaveButton && (
            <AlertDialogAction
              onClick={handleLeave}
              disabled={leaving}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {leaving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("leave.leaving")}
                </>
              ) : (
                t("leave.leaveButton")
              )}
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
