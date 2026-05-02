import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle, ChevronLeft, Loader2 } from "lucide-react";

import { toast } from "@/lib/chesterToast";
import { useDeleteOwnAccount } from "@/hooks/useUsers";
import { useMyDeletionEligibility } from "@/hooks/useAdmin";
import { getMyInitiativeMembersApiV1UsersMeInitiativeMembersInitiativeIdGet } from "@/api/generated/users/users";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import type { DialogWithSuccessProps } from "@/types/dialog";

/**
 * Self-deletion is constrained to two actions:
 *   - ``deactivate`` — reversible, PII intact, admin can reactivate later.
 *   - ``soft_delete`` — anonymize (PII removed), permanent.
 * Hard delete is admin-only and lives on the admin endpoint; the
 * self-service endpoint rejects ``hard_delete`` with 403.
 */
type SelfAction = "deactivate" | "soft_delete";
type DeletionStep = "choose-type" | "check-blockers" | "transfer-projects" | "confirm";

interface ProjectBasic {
  id: number;
  name: string;
  initiative_id: number;
}

interface DeletionEligibilityResponse {
  can_delete: boolean;
  blockers: string[];
  warnings: string[];
  owned_projects: ProjectBasic[];
  last_admin_guilds: string[];
}

interface DeleteAccountDialogProps extends DialogWithSuccessProps {
  user: UserRead;
  /** When provided, the dialog skips the choose-type step and starts
   *  directly on the eligibility check for that action. This lets the
   *  Danger Zone page surface "Deactivate" and "Delete" as separate
   *  buttons instead of a single ambiguous opener. */
  initialAction?: SelfAction;
}

const CONFIRMATION_PHRASES: Record<SelfAction, string> = {
  deactivate: "DEACTIVATE MY ACCOUNT",
  soft_delete: "DELETE MY ACCOUNT",
};

export function DeleteAccountDialog({
  open,
  onOpenChange,
  onSuccess,
  user,
  initialAction,
}: DeleteAccountDialogProps) {
  const { t } = useTranslation("settings");
  const [step, setStep] = useState<DeletionStep>(initialAction ? "check-blockers" : "choose-type");
  const [action, setAction] = useState<SelfAction>(initialAction ?? "deactivate");
  const [eligibility, setEligibility] = useState<DeletionEligibilityResponse | null>(null);
  const [projectTransfers, setProjectTransfers] = useState<Record<number, number>>({});
  const [password, setPassword] = useState("");
  const [confirmationText, setConfirmationText] = useState("");

  // Sync internal state to ``open`` / ``initialAction``. The dialog
  // stays mounted across openings (the parent only flips ``open``), so
  // ``useState`` initial values run once and would never honor a new
  // ``initialAction`` on a subsequent open. We reset on every
  // transition so:
  //   - On open: ``step`` and ``action`` reflect this open's
  //     ``initialAction``. Without this, clicking "Delete Account"
  //     would still show ``action === "deactivate"`` from the initial
  //     mount.
  //   - On close: per-attempt fields (eligibility, password,
  //     confirmation text, project transfers) are cleared so the next
  //     open is a clean slate.
  useEffect(() => {
    setStep(initialAction ? "check-blockers" : "choose-type");
    setAction(initialAction ?? "deactivate");
    if (!open) {
      setEligibility(null);
      setProjectTransfers({});
      setPassword("");
      setConfirmationText("");
    }
  }, [open, initialAction]);

  // Fetch deletion eligibility
  const { refetch: checkEligibility, isFetching: isCheckingEligibility } =
    useMyDeletionEligibility();

  // Fetch initiative members for project transfer
  const [initiativeMembers, setInitiativeMembers] = useState<Record<number, UserRead[]>>({});
  const fetchInitiativeMembers = useCallback(
    async (initiativeId: number) => {
      if (initiativeMembers[initiativeId]) return;

      try {
        const data = (await getMyInitiativeMembersApiV1UsersMeInitiativeMembersInitiativeIdGet(
          initiativeId
        )) as unknown as UserRead[];
        setInitiativeMembers((prev) => ({
          ...prev,
          [initiativeId]: data.filter((u) => u.id !== user.id),
        }));
      } catch (error) {
        console.error("Failed to fetch initiative members:", error);
      }
    },
    [initiativeMembers, user.id]
  );

  const deleteAccount = useDeleteOwnAccount({
    onSuccess: () => {
      toast.success(
        action === "deactivate"
          ? t("deleteAccount.deactivateSuccess")
          : t("deleteAccount.softDeleteSuccess")
      );
      onSuccess();
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("deleteAccount.deleteError");
      toast.error(message);
    },
  });

  // Run the eligibility check and advance past ``check-blockers`` when
  // the user is eligible. Shared between the explicit "Next" press
  // from the chooser step and the auto-fire on dialog open when
  // ``initialAction`` skipped the chooser.
  const runEligibilityCheck = useCallback(async () => {
    const result = await checkEligibility();
    if (!result.data) return;
    setEligibility(result.data);

    // Load initiative members for any projects we'd need to transfer.
    for (const project of result.data.owned_projects) {
      await fetchInitiativeMembers(project.initiative_id);
    }

    // Project transfers are required for both actions when the user
    // owns projects — only owners hold certain permissions, and a
    // deactivated/anonymized owner row can't act on them.
    if (result.data.can_delete) {
      if (result.data.owned_projects.length > 0) {
        setStep("transfer-projects");
      } else {
        setStep("confirm");
      }
    }
  }, [checkEligibility, fetchInitiativeMembers]);

  // When opened with ``initialAction``, the chooser step is bypassed
  // and we land directly on ``check-blockers`` — kick off the check.
  // Guard with a ref so a re-render doesn't refetch.
  const eligibilityFiredRef = useRef(false);
  useEffect(() => {
    if (!open) {
      eligibilityFiredRef.current = false;
      return;
    }
    if (!initialAction || eligibilityFiredRef.current) return;
    eligibilityFiredRef.current = true;
    void runEligibilityCheck();
  }, [open, initialAction, runEligibilityCheck]);

  // Step navigation handlers
  const handleNext = async () => {
    if (step === "choose-type") {
      setStep("check-blockers");
      await runEligibilityCheck();
    } else if (step === "check-blockers") {
      if (eligibility?.can_delete) {
        if (eligibility.owned_projects.length > 0) {
          setStep("transfer-projects");
        } else {
          setStep("confirm");
        }
      }
    } else if (step === "transfer-projects") {
      setStep("confirm");
    }
  };

  const handleBack = () => {
    if (step === "confirm") {
      if (eligibility?.owned_projects.length) {
        setStep("transfer-projects");
      } else {
        setStep("check-blockers");
      }
    } else if (step === "transfer-projects") {
      setStep("check-blockers");
    } else if (step === "check-blockers" && !initialAction) {
      // Only step back to the chooser if it exists — when the dialog
      // was opened from a per-action button, ``check-blockers`` is the
      // first step and Back is disabled.
      setStep("choose-type");
    }
  };

  const handleSubmit = () => {
    deleteAccount.mutate({
      action,
      password,
      confirmation_text: confirmationText,
      project_transfers: eligibility?.owned_projects.length ? projectTransfers : undefined,
    });
  };

  const expectedConfirmation = CONFIRMATION_PHRASES[action];
  // OIDC-provisioned accounts have no usable password (the random hash
  // assigned at SSO callback was never shown to the user). The backend
  // skips the password gate for these users; the dialog hides the
  // password field accordingly.
  const isOidcUser = user.oidc_sub != null;

  // Validation
  const canProceedFromChooseType = action !== null;
  const canProceedFromBlockers = eligibility?.can_delete === true;
  const canProceedFromTransfers =
    !eligibility?.owned_projects.length ||
    eligibility.owned_projects.every((project) => !!projectTransfers[project.id]);
  const canConfirm =
    (isOidcUser || password.length > 0) && confirmationText === expectedConfirmation;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {/* When the dialog was opened with a specific action (the
                Danger Zone's per-action buttons), reflect that in the
                title — the user already chose, no point still calling
                it "Delete Account" while they're deactivating. */}
            {initialAction === "deactivate"
              ? t("deleteAccount.deactivateTitle")
              : t("deleteAccount.title")}
          </DialogTitle>
          <DialogDescription>
            {step === "choose-type" && t("deleteAccount.chooseTypeDescription")}
            {step === "check-blockers" &&
              t(
                action === "deactivate"
                  ? "deleteAccount.checkBlockersDeactivateDescription"
                  : "deleteAccount.checkBlockersDescription"
              )}
            {step === "transfer-projects" && t("deleteAccount.transferProjectsDescription")}
            {step === "confirm" &&
              t(
                action === "deactivate"
                  ? "deleteAccount.confirmDeactivationDescription"
                  : "deleteAccount.confirmDeletionDescription"
              )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Step 1: Choose action */}
          {step === "choose-type" && (
            <RadioGroup value={action} onValueChange={(value) => setAction(value as SelfAction)}>
              <div className="space-y-4">
                <div className="flex items-start space-x-3 rounded-lg border p-4">
                  <RadioGroupItem value="deactivate" id="deactivate" className="mt-0.5" />
                  <div className="flex-1 space-y-1">
                    <Label htmlFor="deactivate" className="cursor-pointer text-base font-medium">
                      {t("deleteAccount.deactivateLabel")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t("deleteAccount.deactivateRadioDescription")}
                    </p>
                  </div>
                </div>

                <div className="border-destructive/50 flex items-start space-x-3 rounded-lg border p-4">
                  <RadioGroupItem value="soft_delete" id="soft_delete" className="mt-0.5" />
                  <div className="flex-1 space-y-1">
                    <Label
                      htmlFor="soft_delete"
                      className="text-destructive cursor-pointer text-base font-medium"
                    >
                      {t("deleteAccount.softDeleteLabel")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t("deleteAccount.softDeleteRadioDescription")}
                    </p>
                  </div>
                </div>
              </div>
            </RadioGroup>
          )}

          {/* Step 2: Check Blockers */}
          {step === "check-blockers" && (
            <div className="space-y-4">
              {isCheckingEligibility && (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
                </div>
              )}

              {eligibility && !eligibility.can_delete && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    <div className="mb-2 font-semibold">
                      {t(
                        action === "deactivate"
                          ? "deleteAccount.cannotDeactivate"
                          : "deleteAccount.cannotDelete"
                      )}
                    </div>
                    <ul className="list-inside list-disc space-y-1">
                      {eligibility.blockers.map((blocker, idx) => (
                        <li key={idx}>{blocker}</li>
                      ))}
                    </ul>
                    <p className="mt-2 text-sm">
                      {t(
                        action === "deactivate"
                          ? "deleteAccount.resolveIssuesDeactivate"
                          : "deleteAccount.resolveIssues"
                      )}
                    </p>
                  </AlertDescription>
                </Alert>
              )}

              {eligibility && eligibility.can_delete && (
                <>
                  {eligibility.warnings.length > 0 && (
                    <Alert>
                      <AlertCircle className="h-4 w-4" />
                      <AlertDescription>
                        <div className="mb-2 font-semibold">{t("deleteAccount.important")}</div>
                        <ul className="list-inside list-disc space-y-1">
                          {eligibility.warnings.map((warning, idx) => (
                            <li key={idx}>{warning}</li>
                          ))}
                        </ul>
                      </AlertDescription>
                    </Alert>
                  )}

                  <Alert className="border-green-500/50 bg-green-50 dark:bg-green-950">
                    <AlertDescription>
                      {t(
                        action === "deactivate"
                          ? "deleteAccount.eligibleDeactivate"
                          : "deleteAccount.eligible"
                      )}
                    </AlertDescription>
                  </Alert>
                </>
              )}
            </div>
          )}

          {/* Step 3: Transfer Projects */}
          {step === "transfer-projects" && eligibility && (
            <div className="space-y-4">
              <p className="text-muted-foreground text-sm">
                {t(
                  action === "deactivate"
                    ? "deleteAccount.selectNewOwnersDeactivate"
                    : "deleteAccount.selectNewOwners"
                )}
              </p>

              {eligibility.owned_projects.map((project) => (
                <div key={project.id} className="space-y-2 rounded-lg border p-4">
                  <Label htmlFor={`project-${project.id}`} className="font-medium">
                    {project.name}
                  </Label>
                  <Select
                    value={projectTransfers[project.id]?.toString()}
                    onValueChange={(value) =>
                      setProjectTransfers((prev) => ({
                        ...prev,
                        [project.id]: parseInt(value),
                      }))
                    }
                  >
                    <SelectTrigger id={`project-${project.id}`}>
                      <SelectValue placeholder={t("deleteAccount.selectNewOwnerPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      {initiativeMembers[project.initiative_id]?.map((member) => (
                        <SelectItem key={member.id} value={member.id.toString()}>
                          {member.full_name || member.email}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ))}
            </div>
          )}

          {/* Step 4: Confirm */}
          {step === "confirm" && (
            <div className="space-y-4">
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  <div className="mb-2 font-semibold">{t("deleteAccount.actionSerious")}</div>
                  <p className="text-sm">
                    {t(
                      action === "deactivate"
                        ? "deleteAccount.deactivateConfirmDescription"
                        : "deleteAccount.softDeleteConfirmDescription"
                    )}
                  </p>
                </AlertDescription>
              </Alert>

              {!isOidcUser && (
                <div className="space-y-2">
                  <Label htmlFor="password">{t("deleteAccount.confirmPasswordLabel")}</Label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t("deleteAccount.enterPassword")}
                  />
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="confirmation">
                  {t("deleteAccount.typeToConfirmPrefix")}{" "}
                  <span className="font-mono font-bold">{expectedConfirmation}</span>{" "}
                  {t("deleteAccount.typeToConfirmSuffix")}
                </Label>
                <Input
                  id="confirmation"
                  value={confirmationText}
                  onChange={(e) => setConfirmationText(e.target.value)}
                  placeholder={expectedConfirmation}
                />
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <div className="flex w-full justify-between">
            <Button
              variant="outline"
              onClick={handleBack}
              disabled={
                step === "choose-type" ||
                (step === "check-blockers" && !!initialAction) ||
                deleteAccount.isPending
              }
            >
              <ChevronLeft className="mr-1 h-4 w-4" />
              {t("deleteAccount.back")}
            </Button>

            <div className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={deleteAccount.isPending}
              >
                {t("deleteAccount.cancel")}
              </Button>

              {step !== "confirm" ? (
                <Button
                  onClick={handleNext}
                  disabled={
                    (step === "choose-type" && !canProceedFromChooseType) ||
                    (step === "check-blockers" && !canProceedFromBlockers) ||
                    (step === "transfer-projects" && !canProceedFromTransfers) ||
                    isCheckingEligibility
                  }
                >
                  {isCheckingEligibility ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t("deleteAccount.checking")}
                    </>
                  ) : (
                    t("deleteAccount.next")
                  )}
                </Button>
              ) : (
                <Button
                  variant="destructive"
                  onClick={handleSubmit}
                  disabled={!canConfirm || deleteAccount.isPending}
                >
                  {deleteAccount.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t("deleteAccount.deleting")}
                    </>
                  ) : action === "deactivate" ? (
                    t("deleteAccount.deactivateAccount")
                  ) : (
                    t("deleteAccount.deleteAccountButton")
                  )}
                </Button>
              )}
            </div>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
