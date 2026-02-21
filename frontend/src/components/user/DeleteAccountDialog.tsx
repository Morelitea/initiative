import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AlertCircle, ChevronLeft, Loader2 } from "lucide-react";

import { useDeleteOwnAccount } from "@/hooks/useUsers";
import { useMyDeletionEligibility } from "@/hooks/useAdmin";
import { getMyInitiativeMembersApiV1UsersMeInitiativeMembersInitiativeIdGet } from "@/api/generated/users/users";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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

type DeletionType = "soft" | "hard";
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

interface DeleteAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  user: UserRead;
}

export function DeleteAccountDialog({
  open,
  onOpenChange,
  onSuccess,
  user,
}: DeleteAccountDialogProps) {
  const { t } = useTranslation("settings");
  const [step, setStep] = useState<DeletionStep>("choose-type");
  const [deletionType, setDeletionType] = useState<DeletionType>("soft");
  const [eligibility, setEligibility] = useState<DeletionEligibilityResponse | null>(null);
  const [projectTransfers, setProjectTransfers] = useState<Record<number, number>>({});
  const [password, setPassword] = useState("");
  const [confirmationText, setConfirmationText] = useState("");
  const [agreedToConsequences, setAgreedToConsequences] = useState(false);

  // Reset state when dialog opens/closes
  useEffect(() => {
    if (!open) {
      setStep("choose-type");
      setDeletionType("soft");
      setEligibility(null);
      setProjectTransfers({});
      setPassword("");
      setConfirmationText("");
      setAgreedToConsequences(false);
    }
  }, [open]);

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

  // Delete account mutation
  const deleteAccount = useDeleteOwnAccount({
    onSuccess: () => {
      toast.success(
        deletionType === "soft"
          ? t("deleteAccount.deactivateSuccess")
          : t("deleteAccount.deleteSuccess")
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

  // Step navigation handlers
  const handleNext = async () => {
    if (step === "choose-type") {
      setStep("check-blockers");
      const result = await checkEligibility();
      if (result.data) {
        setEligibility(result.data);

        // Load initiative members for all owned projects
        for (const project of result.data.owned_projects) {
          await fetchInitiativeMembers(project.initiative_id);
        }

        // If no blockers and no projects to transfer (or soft delete), skip to confirm
        if (
          result.data.can_delete &&
          (deletionType === "soft" || result.data.owned_projects.length === 0)
        ) {
          setStep("confirm");
        } else if (
          result.data.can_delete &&
          deletionType === "hard" &&
          result.data.owned_projects.length > 0
        ) {
          setStep("transfer-projects");
        }
      }
    } else if (step === "check-blockers") {
      if (eligibility?.can_delete) {
        if (deletionType === "hard" && eligibility.owned_projects.length > 0) {
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
      if (deletionType === "hard" && eligibility?.owned_projects.length) {
        setStep("transfer-projects");
      } else {
        setStep("check-blockers");
      }
    } else if (step === "transfer-projects") {
      setStep("check-blockers");
    } else if (step === "check-blockers") {
      setStep("choose-type");
    }
  };

  const handleDelete = () => {
    deleteAccount.mutate({
      deletion_type: deletionType,
      password,
      confirmation_text: confirmationText,
      project_transfers: deletionType === "hard" ? projectTransfers : undefined,
    });
  };

  // Validation
  const canProceedFromChooseType = deletionType !== null;
  const canProceedFromBlockers = eligibility?.can_delete === true;
  const canProceedFromTransfers =
    !eligibility?.owned_projects.length ||
    eligibility.owned_projects.every((project) => !!projectTransfers[project.id]);
  const canConfirm =
    password.length > 0 &&
    confirmationText === "DELETE MY ACCOUNT" &&
    (deletionType === "soft" || agreedToConsequences);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("deleteAccount.title")}</DialogTitle>
          <DialogDescription>
            {step === "choose-type" && t("deleteAccount.chooseTypeDescription")}
            {step === "check-blockers" && t("deleteAccount.checkBlockersDescription")}
            {step === "transfer-projects" && t("deleteAccount.transferProjectsDescription")}
            {step === "confirm" && t("deleteAccount.confirmDeletionDescription")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Step 1: Choose Type */}
          {step === "choose-type" && (
            <RadioGroup
              value={deletionType}
              onValueChange={(value) => setDeletionType(value as DeletionType)}
            >
              <div className="space-y-4">
                <div className="flex items-start space-x-3 rounded-lg border p-4">
                  <RadioGroupItem value="soft" id="soft" className="mt-0.5" />
                  <div className="flex-1 space-y-1">
                    <Label htmlFor="soft" className="cursor-pointer text-base font-medium">
                      {t("deleteAccount.softDeleteLabel")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t("deleteAccount.softDeleteRadioDescription")}
                    </p>
                  </div>
                </div>

                <div className="border-destructive/50 flex items-start space-x-3 rounded-lg border p-4">
                  <RadioGroupItem value="hard" id="hard" className="mt-0.5" />
                  <div className="flex-1 space-y-1">
                    <Label
                      htmlFor="hard"
                      className="text-destructive cursor-pointer text-base font-medium"
                    >
                      {t("deleteAccount.hardDeleteLabel")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t("deleteAccount.hardDeleteRadioDescription")}
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
                    <div className="mb-2 font-semibold">{t("deleteAccount.cannotDelete")}</div>
                    <ul className="list-inside list-disc space-y-1">
                      {eligibility.blockers.map((blocker, idx) => (
                        <li key={idx}>{blocker}</li>
                      ))}
                    </ul>
                    <p className="mt-2 text-sm">{t("deleteAccount.resolveIssues")}</p>
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
                    <AlertDescription>{t("deleteAccount.eligible")}</AlertDescription>
                  </Alert>
                </>
              )}
            </div>
          )}

          {/* Step 3: Transfer Projects */}
          {step === "transfer-projects" && eligibility && (
            <div className="space-y-4">
              <p className="text-muted-foreground text-sm">{t("deleteAccount.selectNewOwners")}</p>

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
                  {deletionType === "soft" ? (
                    <p className="text-sm">{t("deleteAccount.softConfirmDescription")}</p>
                  ) : (
                    <p className="text-sm">{t("deleteAccount.hardConfirmDescription")}</p>
                  )}
                </AlertDescription>
              </Alert>

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

              <div className="space-y-2">
                <Label htmlFor="confirmation">
                  {t("deleteAccount.typeToConfirmPrefix")}{" "}
                  <span className="font-mono font-bold">
                    {t("deleteAccount.typeToConfirmCode")}
                  </span>{" "}
                  {t("deleteAccount.typeToConfirmSuffix")}
                </Label>
                <Input
                  id="confirmation"
                  value={confirmationText}
                  onChange={(e) => setConfirmationText(e.target.value)}
                  placeholder={t("deleteAccount.confirmationPlaceholder")}
                />
              </div>

              {deletionType === "hard" && (
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="agree"
                    checked={agreedToConsequences}
                    onCheckedChange={(checked) => setAgreedToConsequences(checked === true)}
                  />
                  <Label htmlFor="agree" className="cursor-pointer text-sm">
                    {t("deleteAccount.agreeConsequences")}
                  </Label>
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <div className="flex w-full justify-between">
            <Button
              variant="outline"
              onClick={handleBack}
              disabled={step === "choose-type" || deleteAccount.isPending}
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
                  onClick={handleDelete}
                  disabled={!canConfirm || deleteAccount.isPending}
                >
                  {deleteAccount.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t("deleteAccount.deleting")}
                    </>
                  ) : deletionType === "soft" ? (
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
