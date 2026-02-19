import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  checkLeaveEligibilityApiV1GuildsGuildIdLeaveEligibilityGet,
  leaveGuildApiV1GuildsGuildIdLeaveDelete,
} from "@/api/generated/guilds/guilds";
import type { Guild, LeaveGuildEligibilityResponse } from "@/types/api";
import { useGuilds } from "@/hooks/useGuilds";

interface LeaveGuildDialogProps {
  guild: Guild;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

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
          <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
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

    if (!eligibility.can_leave) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t("leave.cannotLeaveTitle")}</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-inside list-disc space-y-1">
              {eligibility.is_last_admin && <li>{t("leave.lastAdminWarning")}</li>}
              {eligibility.sole_pm_initiatives.length > 0 && (
                <li>
                  {t("leave.solePmWarning", {
                    initiatives: eligibility.sole_pm_initiatives.join(", "),
                  })}
                </li>
              )}
            </ul>
          </AlertDescription>
        </Alert>
      );
    }

    return (
      <AlertDialogDescription>
        {t("leave.description", { name: guild.name })}
      </AlertDialogDescription>
    );
  };

  const canLeave = eligibility?.can_leave && !loading && !error;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("leave.title", { name: guild.name })}</AlertDialogTitle>
        </AlertDialogHeader>
        {renderContent()}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={leaving}>{t("common:cancel")}</AlertDialogCancel>
          {canLeave && (
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
