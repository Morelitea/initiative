import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
  checkGuildRemovalEligibilityApiV1UsersUserIdGuildRemovalEligibilityGet,
  deleteUserApiV1UsersUserIdDelete,
} from "@/api/generated/users/users";
import type { GuildRemovalEligibilityResponse } from "@/api/generated/initiativeAPI.schemas";
import { getErrorMessage } from "@/lib/errorMessage";
import { invalidateUsersList } from "@/api/query-keys";

interface RemoveGuildMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  userId: number | null;
  email: string;
  onSuccess?: () => void;
}

/**
 * Guild-admin counterpart to ``LeaveGuildDialog``. The simple
 * "are you sure?" confirm we used to ship here would silently orphan
 * any project owned by the target user — guild admins have no DAC
 * bypass on projects, so a project owned by a sole-member becomes
 * unreachable once their initiative membership is dropped.
 *
 * The dialog now pre-flights a ``GET .../guild-removal-eligibility``
 * request: when the target user owns projects in the active guild,
 * it shows a Select per project so the admin nominates a new owner,
 * and the underlying ``DELETE`` only fires once every nominee is set.
 *
 * Eligibility carries the candidate transfer recipients per-project,
 * so the dialog renders the picker without a second round trip — the
 * leave-guild path can reuse ``/users/me/initiative-members`` because
 * it's the same user, but a guild admin removing someone may not
 * themselves belong to every initiative involved.
 */
export const RemoveGuildMemberDialog = ({
  open,
  onOpenChange,
  userId,
  email,
  onSuccess,
}: RemoveGuildMemberDialogProps) => {
  const { t } = useTranslation(["guilds", "common"]);
  const [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState(false);
  const [eligibility, setEligibility] = useState<GuildRemovalEligibilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectTransfers, setProjectTransfers] = useState<Record<number, number>>({});

  useEffect(() => {
    if (!open || userId === null) {
      setEligibility(null);
      setError(null);
      setLoading(true);
      setProjectTransfers({});
      return;
    }

    const checkEligibility = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = (await checkGuildRemovalEligibilityApiV1UsersUserIdGuildRemovalEligibilityGet(
          userId
        )) as unknown as GuildRemovalEligibilityResponse;
        setEligibility(data);
      } catch (err) {
        console.error("Failed to check removal eligibility", err);
        setError(t("removeMember.failedToCheckEligibility"));
      } finally {
        setLoading(false);
      }
    };

    void checkEligibility();
  }, [open, userId, t]);

  const ownedProjects = eligibility?.owned_projects ?? [];
  const hasOwnedProjects = ownedProjects.length > 0;
  const allTransfersPicked =
    !hasOwnedProjects || ownedProjects.every((project) => !!projectTransfers[project.id]);
  const hasHardBlocker = !!eligibility && eligibility.sole_pm_initiatives.length > 0;

  const handleRemove = async () => {
    if (userId === null) return;
    setRemoving(true);
    try {
      await deleteUserApiV1UsersUserIdDelete(userId, {
        project_transfers: projectTransfers,
      });
      void invalidateUsersList();
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
          <AlertTitle>{t("removeMember.cannotRemoveTitle")}</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-inside list-disc space-y-1">
              {eligibility.sole_pm_initiatives.length > 0 && (
                <li>
                  {t("removeMember.solePmWarning", {
                    initiatives: eligibility.sole_pm_initiatives.join(", "),
                  })}
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
            {t("removeMember.transferDescription", { email })}
          </AlertDialogDescription>
          {ownedProjects.map((project) => {
            const candidates = project.candidates ?? [];
            const value = projectTransfers[project.id]?.toString() ?? "";
            return (
              <div key={project.id} className="space-y-2 rounded-md border p-3">
                <Label htmlFor={`transfer-${project.id}`} className="font-medium">
                  {project.name}
                </Label>
                {candidates.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    {t("removeMember.noTransferCandidates")}
                  </p>
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
                      <SelectValue placeholder={t("removeMember.selectNewOwnerPlaceholder")} />
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
      <AlertDialogDescription>{t("removeMember.description", { email })}</AlertDialogDescription>
    );
  };

  const canShowRemoveButton = !loading && !error && eligibility && !hasHardBlocker;
  const removeDisabled = removing || !allTransfersPicked;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("removeMember.title")}</AlertDialogTitle>
        </AlertDialogHeader>
        {renderContent()}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={removing}>{t("common:cancel")}</AlertDialogCancel>
          {canShowRemoveButton && (
            <AlertDialogAction
              onClick={handleRemove}
              disabled={removeDisabled}
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
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
