import { AlertCircle, ChevronLeft, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
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
import { useMyDeletionEligibility } from "@/hooks/useAdmin";
import { useDeleteOwnAccount } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { DialogWithSuccessProps } from "@/types/dialog";

/**
 * Self-deletion is constrained to two actions:
 *   - ``deactivate`` — reversible, PII intact, admin can reactivate later.
 *   - ``soft_delete`` — anonymize (PII removed), permanent.
 * Hard delete is admin-only and lives on the admin endpoint; the
 * self-service endpoint rejects ``hard_delete`` with 403.
 */
type SelfAction = "deactivate" | "soft_delete";
type DeletionStep = "choose-type" | "check-blockers" | "confirm";

interface DeletionEligibilityResponse {
  can_delete: boolean;
  blockers: string[];
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
      setPassword("");
      setConfirmationText("");
    }
  }, [open, initialAction]);

  // Fetch deletion eligibility
  const { refetch: checkEligibility, isFetching: isCheckingEligibility } =
    useMyDeletionEligibility();

  // Fetch initiative members for project transfer
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
      toast.error(getErrorMessage(error, "settings:deleteAccount.deleteError"));
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
    if (result.data.can_delete) {
      setStep("confirm");
    }
  }, [checkEligibility]);

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
        setStep("confirm");
      }
    }
  };

  const handleBack = () => {
    if (step === "confirm") {
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
    });
  };

  const expectedConfirmation = CONFIRMATION_PHRASES[action];
  // SSO accounts have no usable password (the random hash assigned at
  // provisioning was never shown to the user). The backend skips the
  // password gate for these users; the dialog hides the password field
  // accordingly.
  const isOidcUser = user.has_federated_identity;

  // Validation
  const canProceedFromChooseType = action !== null;
  const canProceedFromBlockers = eligibility?.can_delete === true;
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
                    <Label htmlFor="deactivate" className="cursor-pointer font-medium text-base">
                      {t("deleteAccount.deactivateLabel")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t("deleteAccount.deactivateRadioDescription")}
                    </p>
                  </div>
                </div>

                <div className="flex items-start space-x-3 rounded-lg border border-destructive/50 p-4">
                  <RadioGroupItem value="soft_delete" id="soft_delete" className="mt-0.5" />
                  <div className="flex-1 space-y-1">
                    <Label
                      htmlFor="soft_delete"
                      className="cursor-pointer font-medium text-base text-destructive"
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
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
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
                      {eligibility.blockers.map((blocker) => (
                        <li key={blocker}>{blocker}</li>
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

              {eligibility?.can_delete && (
                <>
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

          {/* Step 3: Confirm */}
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
                  <span className="font-bold font-mono">{expectedConfirmation}</span>{" "}
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
              <ChevronLeft className="h-4 w-4" />
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
                    isCheckingEligibility
                  }
                >
                  {isCheckingEligibility ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
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
                      <Loader2 className="h-4 w-4 animate-spin" />
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
