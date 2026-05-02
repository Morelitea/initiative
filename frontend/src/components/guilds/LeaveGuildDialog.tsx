import { useCallback, useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Loader2, AlertTriangle } from "lucide-react";

import { toast } from "@/lib/chesterToast";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  checkLeaveEligibilityApiV1GuildsGuildIdLeaveEligibilityGet,
  leaveGuildApiV1GuildsGuildIdLeaveDelete,
} from "@/api/generated/guilds/guilds";
import { getMyInitiativeMembersApiV1UsersMeInitiativeMembersInitiativeIdGet } from "@/api/generated/users/users";
import type {
  GuildRead,
  LeaveGuildEligibilityResponse,
  UserRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useGuilds } from "@/hooks/useGuilds";
import type { DialogProps } from "@/types/dialog";

interface LeaveGuildDialogProps extends DialogProps {
  guild: GuildRead;
}

export const LeaveGuildDialog = ({ guild, open, onOpenChange }: LeaveGuildDialogProps) => {
  const { t } = useTranslation(["guilds", "common"]);
  const { guilds, refreshGuilds, switchGuild, activeGuildId } = useGuilds();
  const [loading, setLoading] = useState(true);
  const [leaving, setLeaving] = useState(false);
  const [eligibility, setEligibility] = useState<LeaveGuildEligibilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Per-project: id of the user the leaver is handing the project to.
  const [projectTransfers, setProjectTransfers] = useState<Record<number, number>>({});
  // Per-initiative cache of candidate transfer recipients. The leave
  // path only renders Selects for projects in initiatives where the
  // user has visibility; the helper endpoint filters to active members
  // (excluding the current user).
  const [initiativeMembers, setInitiativeMembers] = useState<Record<number, UserRead[]>>({});

  const fetchInitiativeMembers = useCallback(async (initiativeId: number) => {
    setInitiativeMembers((prev) => {
      // Skip refetch if we've already loaded this initiative.
      if (prev[initiativeId]) return prev;
      return prev;
    });
    try {
      const data = (await getMyInitiativeMembersApiV1UsersMeInitiativeMembersInitiativeIdGet(
        initiativeId
      )) as unknown as UserRead[];
      setInitiativeMembers((prev) =>
        prev[initiativeId] ? prev : { ...prev, [initiativeId]: data }
      );
    } catch (err) {
      console.error("Failed to fetch initiative members", err);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      setEligibility(null);
      setError(null);
      setLoading(true);
      setProjectTransfers({});
      setInitiativeMembers({});
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
        // Pre-load member lists for any initiative whose project
        // we'll render a Select for, so the dropdown is populated by
        // the time the user opens it.
        const uniqueInitiativeIds = Array.from(
          new Set(data.owned_projects.map((p) => p.initiative_id))
        );
        await Promise.all(uniqueInitiativeIds.map(fetchInitiativeMembers));
      } catch (err) {
        console.error("Failed to check leave eligibility", err);
        setError(t("leave.failedToCheckEligibility"));
      } finally {
        setLoading(false);
      }
    };

    void checkEligibility();
  }, [open, guild.id, t, fetchInitiativeMembers]);

  const ownedProjects = eligibility?.owned_projects ?? [];
  const hasOwnedProjects = ownedProjects.length > 0;
  const allTransfersPicked =
    !hasOwnedProjects || ownedProjects.every((project) => !!projectTransfers[project.id]);
  const hasHardBlocker =
    !!eligibility && (eligibility.is_last_admin || eligibility.sole_pm_initiatives.length > 0);

  const handleLeave = async () => {
    setLeaving(true);
    try {
      // Pass the body unconditionally — the backend treats absent and
      // empty as equivalent, but always sending lets us reuse one code
      // path here regardless of whether transfers were needed.
      await leaveGuildApiV1GuildsGuildIdLeaveDelete(guild.id, {
        project_transfers: projectTransfers,
      });

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

    if (hasHardBlocker) {
      return (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t("leave.cannotLeaveTitle")}</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-inside list-disc space-y-1">
              {eligibility.is_last_admin && <li>{t("leave.lastAdminWarning")}</li>}
              {eligibility.sole_pm_initiatives.length > 0 && (
                <li>
                  <Trans
                    i18nKey="leave.solePmWarning"
                    ns="guilds"
                    values={{ initiatives: eligibility.sole_pm_initiatives.join(", ") }}
                    components={{ bold: <strong /> }}
                  />
                </li>
              )}
            </ul>
          </AlertDescription>
        </Alert>
      );
    }

    if (hasOwnedProjects) {
      return (
        <div className="space-y-4">
          <AlertDialogDescription>
            <Trans
              i18nKey="leave.transferDescription"
              ns="guilds"
              values={{ name: guild.name }}
              components={{ bold: <strong /> }}
            />
          </AlertDialogDescription>
          {ownedProjects.map((project) => {
            const candidates = initiativeMembers[project.initiative_id] ?? [];
            const value = projectTransfers[project.id]?.toString() ?? "";
            return (
              <div key={project.id} className="space-y-2 rounded-md border p-3">
                <Label htmlFor={`transfer-${project.id}`} className="font-medium">
                  {project.name}
                </Label>
                {candidates.length === 0 ? (
                  <p className="text-muted-foreground text-sm">{t("leave.noTransferCandidates")}</p>
                ) : (
                  <Select
                    value={value}
                    onValueChange={(next) =>
                      setProjectTransfers((prev) => ({
                        ...prev,
                        [project.id]: Number(next),
                      }))
                    }
                  >
                    <SelectTrigger id={`transfer-${project.id}`}>
                      <SelectValue placeholder={t("leave.selectNewOwnerPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      {candidates.map((member) => (
                        <SelectItem key={member.id} value={member.id.toString()}>
                          {member.full_name || member.email}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            );
          })}
        </div>
      );
    }

    return (
      <AlertDialogDescription>
        <Trans
          i18nKey="leave.description"
          ns="guilds"
          values={{ name: guild.name }}
          components={{ bold: <strong /> }}
        />
      </AlertDialogDescription>
    );
  };

  // The button is shown for every non-blocked, non-error state. The
  // disabled state additionally requires every owned-project transfer
  // to be filled in — clicking with a half-filled map would just bounce
  // off the backend's CANNOT_LEAVE_OWNS_PROJECTS guard, so we gate it
  // here for a faster signal.
  const canShowLeaveButton = !loading && !error && eligibility && !hasHardBlocker;
  const leaveDisabled = leaving || !allTransfersPicked;

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
              disabled={leaveDisabled}
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
