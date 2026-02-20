import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AlertCircle, ChevronLeft, Loader2, Trash2 } from "lucide-react";

import {
  checkUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGet,
  getCheckUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGetQueryKey,
  deleteUserApiV1AdminUsersUserIdDelete,
  adminDeleteGuildApiV1AdminGuildsGuildIdDelete,
  adminUpdateGuildMemberRoleApiV1AdminGuildsGuildIdMembersUserIdRolePatch,
  adminUpdateInitiativeMemberRoleApiV1AdminInitiativesInitiativeIdMembersUserIdRolePatch,
} from "@/api/generated/admin/admin";
import { getInitiativeMembersApiV1InitiativesInitiativeIdMembersGet } from "@/api/generated/initiatives/initiatives";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import type {
  User,
  DeletionEligibilityResponse,
  AdminUserDeleteRequest,
  AccountDeletionResponse,
  GuildBlockerInfo,
  InitiativeBlockerInfo,
} from "@/types/api";

type DeletionType = "soft" | "hard";
type DeletionStep =
  | "choose-type"
  | "check-blockers"
  | "resolve-blockers"
  | "transfer-projects"
  | "confirm";

interface AdminDeleteUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  targetUser: User;
}

export function AdminDeleteUserDialog({
  open,
  onOpenChange,
  onSuccess,
  targetUser,
}: AdminDeleteUserDialogProps) {
  const { t } = useTranslation("settings");
  const [step, setStep] = useState<DeletionStep>("choose-type");
  const [deletionType, setDeletionType] = useState<DeletionType>("soft");
  const [eligibility, setEligibility] = useState<DeletionEligibilityResponse | null>(null);
  const [projectTransfers, setProjectTransfers] = useState<Record<number, number>>({});
  const [confirmationText, setConfirmationText] = useState("");
  const [agreedToConsequences, setAgreedToConsequences] = useState(false);

  // State for blocker resolution
  const [guildDeleteConfirm, setGuildDeleteConfirm] = useState<GuildBlockerInfo | null>(null);
  const [isResolvingBlocker, setIsResolvingBlocker] = useState(false);

  // Reset state when dialog opens/closes
  useEffect(() => {
    if (!open) {
      setStep("choose-type");
      setDeletionType("soft");
      setEligibility(null);
      setProjectTransfers({});
      setConfirmationText("");
      setAgreedToConsequences(false);
      setGuildDeleteConfirm(null);
      setIsResolvingBlocker(false);
    }
  }, [open]);

  // Fetch deletion eligibility
  const { refetch: checkEligibility, isFetching: isCheckingEligibility } = useQuery({
    queryKey: getCheckUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGetQueryKey(
      targetUser.id
    ),
    queryFn: () =>
      checkUserDeletionEligibilityApiV1AdminUsersUserIdDeletionEligibilityGet(
        targetUser.id
      ) as unknown as Promise<DeletionEligibilityResponse>,
    enabled: false,
  });

  // Fetch initiative members for project transfer
  const [initiativeMembers, setInitiativeMembers] = useState<Record<number, User[]>>({});
  const fetchInitiativeMembers = useCallback(
    async (initiativeId: number) => {
      if (initiativeMembers[initiativeId]) return;

      try {
        const members = await (getInitiativeMembersApiV1InitiativesInitiativeIdMembersGet(
          initiativeId
        ) as unknown as Promise<User[]>);
        setInitiativeMembers((prev) => ({
          ...prev,
          [initiativeId]: members.filter((u) => u.id !== targetUser.id),
        }));
      } catch (error) {
        console.error("Failed to fetch initiative members:", error);
      }
    },
    [initiativeMembers, targetUser.id]
  );

  // Mutations for resolving blockers
  const promoteGuildMember = useMutation({
    mutationFn: async ({ guildId, userId }: { guildId: number; userId: number }) => {
      await adminUpdateGuildMemberRoleApiV1AdminGuildsGuildIdMembersUserIdRolePatch(
        guildId,
        userId,
        { role: "admin" }
      );
    },
    onSuccess: async () => {
      toast.success(t("adminDeleteUser.promoteSuccess"));
      await refreshEligibility();
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("adminDeleteUser.promoteError");
      toast.error(message);
    },
    onSettled: () => setIsResolvingBlocker(false),
  });

  const deleteGuild = useMutation({
    mutationFn: async (guildId: number) => {
      await adminDeleteGuildApiV1AdminGuildsGuildIdDelete(guildId);
    },
    onSuccess: async () => {
      toast.success(t("adminDeleteUser.deleteGuildSuccess"));
      setGuildDeleteConfirm(null);
      await refreshEligibility();
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("adminDeleteUser.deleteGuildError");
      toast.error(message);
    },
    onSettled: () => setIsResolvingBlocker(false),
  });

  const promoteInitiativeMember = useMutation({
    mutationFn: async ({ initiativeId, userId }: { initiativeId: number; userId: number }) => {
      await adminUpdateInitiativeMemberRoleApiV1AdminInitiativesInitiativeIdMembersUserIdRolePatch(
        initiativeId,
        userId,
        { role: "project_manager" }
      );
    },
    onSuccess: async () => {
      toast.success(t("adminDeleteUser.promoteSuccess"));
      await refreshEligibility();
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("adminDeleteUser.promoteError");
      toast.error(message);
    },
    onSettled: () => setIsResolvingBlocker(false),
  });

  // Delete user mutation
  const deleteUser = useMutation({
    mutationFn: async (request: AdminUserDeleteRequest) => {
      return deleteUserApiV1AdminUsersUserIdDelete(
        targetUser.id,
        request
      ) as unknown as Promise<AccountDeletionResponse>;
    },
    onSuccess: (data) => {
      toast.success(data.message);
      onSuccess();
      onOpenChange(false);
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("adminDeleteUser.deleteError");
      toast.error(message);
    },
  });

  // Refresh eligibility after resolving a blocker
  const refreshEligibility = async () => {
    const result = await checkEligibility();
    if (result.data) {
      setEligibility(result.data);

      // Load initiative members for all owned projects
      for (const project of result.data.owned_projects) {
        await fetchInitiativeMembers(project.initiative_id);
      }

      // If blockers are now resolved, move forward
      if (result.data.can_delete) {
        if (deletionType === "hard" && result.data.owned_projects.length > 0) {
          setStep("transfer-projects");
        } else {
          setStep("confirm");
        }
      }
    }
  };

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

        // Check if there are blockers that can be resolved
        const hasResolvableBlockers =
          result.data.guild_blockers.length > 0 || result.data.initiative_blockers.length > 0;

        if (!result.data.can_delete && hasResolvableBlockers) {
          setStep("resolve-blockers");
        } else if (
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
    } else if (step === "check-blockers" || step === "resolve-blockers") {
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
      } else if (hasBlockers) {
        setStep("resolve-blockers");
      } else {
        setStep("check-blockers");
      }
    } else if (step === "transfer-projects") {
      if (hasBlockers) {
        setStep("resolve-blockers");
      } else {
        setStep("check-blockers");
      }
    } else if (step === "resolve-blockers") {
      setStep("check-blockers");
    } else if (step === "check-blockers") {
      setStep("choose-type");
    }
  };

  const handleDelete = () => {
    deleteUser.mutate({
      deletion_type: deletionType,
      project_transfers: deletionType === "hard" ? projectTransfers : undefined,
    });
  };

  const handlePromoteGuildMember = (guildId: number, userId: number) => {
    setIsResolvingBlocker(true);
    promoteGuildMember.mutate({ guildId, userId });
  };

  const handleDeleteGuild = (guildId: number) => {
    setIsResolvingBlocker(true);
    deleteGuild.mutate(guildId);
  };

  const handlePromoteInitiativeMember = (initiativeId: number, userId: number) => {
    setIsResolvingBlocker(true);
    promoteInitiativeMember.mutate({ initiativeId, userId });
  };

  // Check if there are blockers (guild or initiative)
  const hasBlockers =
    (eligibility?.guild_blockers.length ?? 0) > 0 ||
    (eligibility?.initiative_blockers.length ?? 0) > 0;

  // Validation
  const canProceedFromChooseType = deletionType !== null;
  const canProceedFromBlockers = eligibility?.can_delete === true;
  const canProceedFromTransfers =
    !eligibility?.owned_projects.length ||
    eligibility.owned_projects.every((project) => !!projectTransfers[project.id]);
  const confirmationRequired = targetUser.email.split("@")[0].toUpperCase();
  const canConfirm =
    confirmationText === confirmationRequired && (deletionType === "soft" || agreedToConsequences);

  const displayName = targetUser.full_name || targetUser.email;

  // Helper to format member for combobox display
  const formatMemberLabel = (member: { full_name?: string | null; email: string }) => {
    if (member.full_name) {
      return `${member.full_name} (${member.email})`;
    }
    return member.email;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("adminDeleteUser.subtitle", { email: displayName })}</DialogTitle>
          <DialogDescription>
            {step === "choose-type" && t("adminDeleteUser.stepType")}
            {step === "check-blockers" && t("adminDeleteUser.checkingEligibility")}
            {step === "resolve-blockers" && t("adminDeleteUser.stepBlockers")}
            {step === "transfer-projects" && t("adminDeleteUser.stepTransfer")}
            {step === "confirm" && t("adminDeleteUser.confirmTitle")}
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
                      {t("adminDeleteUser.softDeleteTitle")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t("adminDeleteUser.softDeleteDescription")}
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
                      {t("adminDeleteUser.hardDeleteTitle")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {t("adminDeleteUser.hardDeleteDescription")}
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
                    <div className="mb-2 font-semibold">{t("adminDeleteUser.blockersTitle")}</div>
                    <ul className="list-inside list-disc space-y-1">
                      {eligibility.blockers.map((blocker, idx) => (
                        <li key={idx}>{blocker}</li>
                      ))}
                    </ul>
                    <p className="mt-2 text-sm">{t("adminDeleteUser.blockersDescription")}</p>
                  </AlertDescription>
                </Alert>
              )}

              {eligibility && eligibility.can_delete && (
                <>
                  {eligibility.warnings.length > 0 && (
                    <Alert>
                      <AlertCircle className="h-4 w-4" />
                      <AlertDescription>
                        <div className="mb-2 font-semibold">
                          {t("adminDeleteUser.warningsTitle")}
                        </div>
                        <ul className="list-inside list-disc space-y-1">
                          {eligibility.warnings.map((warning, idx) => (
                            <li key={idx}>{warning}</li>
                          ))}
                        </ul>
                      </AlertDescription>
                    </Alert>
                  )}

                  <Alert className="border-green-500/50 bg-green-50 dark:bg-green-950">
                    <AlertDescription>{t("adminDeleteUser.confirmDescription")}</AlertDescription>
                  </Alert>
                </>
              )}
            </div>
          )}

          {/* Step 2.5: Resolve Blockers */}
          {step === "resolve-blockers" && eligibility && (
            <div className="space-y-6">
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{t("adminDeleteUser.blockersDescription")}</AlertDescription>
              </Alert>

              {/* Group blockers by guild */}
              {(() => {
                // Build a map of guild_id -> { guildBlocker?, initiativeBlockers[] }
                const guildGroups = new Map<
                  number,
                  {
                    guildBlocker: GuildBlockerInfo | null;
                    guildName: string;
                    initiativeBlockers: InitiativeBlockerInfo[];
                  }
                >();

                // Add guild blockers
                for (const blocker of eligibility.guild_blockers) {
                  guildGroups.set(blocker.guild_id, {
                    guildBlocker: blocker,
                    guildName: blocker.guild_name,
                    initiativeBlockers: [],
                  });
                }

                // Add initiative blockers, grouped by guild
                for (const blocker of eligibility.initiative_blockers) {
                  const existing = guildGroups.get(blocker.guild_id);
                  if (existing) {
                    existing.initiativeBlockers.push(blocker);
                  } else {
                    // Initiative blocker without a guild blocker - need to get guild name from initiative
                    guildGroups.set(blocker.guild_id, {
                      guildBlocker: null,
                      guildName: "", // Will show just initiatives
                      initiativeBlockers: [blocker],
                    });
                  }
                }

                return Array.from(guildGroups.entries()).map(
                  ([guildId, { guildBlocker, initiativeBlockers }]) => (
                    <div key={guildId} className="space-y-3 rounded-lg border p-4">
                      {/* Guild blocker section */}
                      {guildBlocker && (
                        <>
                          <div className="flex items-center justify-between">
                            <div>
                              <h4 className="font-medium">
                                {t("adminDeleteUser.guildBlockerTitle", {
                                  guildName: guildBlocker.guild_name,
                                })}
                              </h4>
                              <p className="text-muted-foreground text-sm">
                                {t("adminDeleteUser.guildBlockerDescription")}
                              </p>
                            </div>
                            <Button
                              variant="outline"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              onClick={() => setGuildDeleteConfirm(guildBlocker)}
                              disabled={isResolvingBlocker}
                            >
                              <Trash2 className="mr-1 h-4 w-4" />
                              {t("adminDeleteUser.deleteGuild")}
                            </Button>
                          </div>

                          {guildBlocker.other_members.length > 0 ? (
                            <div className="space-y-2">
                              <Label className="text-sm">
                                {t("adminDeleteUser.promoteToGuildAdmin")}
                              </Label>
                              <div className="flex items-center gap-2">
                                <SearchableCombobox
                                  items={guildBlocker.other_members.map((member) => ({
                                    value: member.id.toString(),
                                    label: formatMemberLabel(member),
                                  }))}
                                  onValueChange={(value) =>
                                    handlePromoteGuildMember(guildBlocker.guild_id, parseInt(value))
                                  }
                                  placeholder={t("adminDeleteUser.transferSelectPlaceholder")}
                                  emptyMessage={t("adminDeleteUser.noUsersAvailable")}
                                  disabled={isResolvingBlocker}
                                  className="flex-1"
                                />
                                {isResolvingBlocker && <Loader2 className="h-5 w-5 animate-spin" />}
                              </div>
                            </div>
                          ) : (
                            <p className="text-muted-foreground text-sm italic">
                              {t("adminDeleteUser.noUsersAvailable")}
                            </p>
                          )}
                        </>
                      )}

                      {/* Initiative blockers nested under the guild */}
                      {initiativeBlockers.length > 0 && (
                        <div
                          className={
                            guildBlocker ? "border-l-muted ml-4 space-y-3 border-l-2 pl-4" : ""
                          }
                        >
                          {initiativeBlockers.map((initBlocker) => (
                            <div
                              key={initBlocker.initiative_id}
                              className={guildBlocker ? "space-y-2" : "space-y-3"}
                            >
                              <div>
                                <h4 className="font-medium">
                                  {t("adminDeleteUser.initiativeBlockerTitle", {
                                    initiativeName: initBlocker.initiative_name,
                                  })}
                                </h4>
                                <p className="text-muted-foreground text-sm">
                                  {t("adminDeleteUser.initiativeBlockerDescription")}
                                </p>
                              </div>

                              {initBlocker.other_members.length > 0 ? (
                                <div className="space-y-2">
                                  <Label className="text-sm">
                                    {t("adminDeleteUser.promoteToInitiativePM")}
                                  </Label>
                                  <div className="flex items-center gap-2">
                                    <SearchableCombobox
                                      items={initBlocker.other_members.map((member) => ({
                                        value: member.id.toString(),
                                        label: formatMemberLabel(member),
                                      }))}
                                      onValueChange={(value) =>
                                        handlePromoteInitiativeMember(
                                          initBlocker.initiative_id,
                                          parseInt(value)
                                        )
                                      }
                                      placeholder={t("adminDeleteUser.transferSelectPlaceholder")}
                                      emptyMessage={t("adminDeleteUser.noUsersAvailable")}
                                      disabled={isResolvingBlocker}
                                      className="flex-1"
                                    />
                                    {isResolvingBlocker && (
                                      <Loader2 className="h-5 w-5 animate-spin" />
                                    )}
                                  </div>
                                </div>
                              ) : (
                                <p className="text-muted-foreground text-sm italic">
                                  {t("adminDeleteUser.noUsersAvailable")}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                );
              })()}

              {eligibility.can_delete && (
                <Alert className="border-green-500/50 bg-green-50 dark:bg-green-950">
                  <AlertDescription>{t("adminDeleteUser.confirmDescription")}</AlertDescription>
                </Alert>
              )}
            </div>
          )}

          {/* Step 3: Transfer Projects */}
          {step === "transfer-projects" && eligibility && (
            <div className="space-y-4">
              <p className="text-muted-foreground text-sm">
                {t("adminDeleteUser.transferDescription")}
              </p>

              {eligibility.owned_projects.map((project) => (
                <div key={project.id} className="space-y-2 rounded-lg border p-4">
                  <Label className="font-medium">{project.name}</Label>
                  <SearchableCombobox
                    items={
                      initiativeMembers[project.initiative_id]?.map((member) => ({
                        value: member.id.toString(),
                        label: formatMemberLabel(member),
                      })) ?? []
                    }
                    value={projectTransfers[project.id]?.toString()}
                    onValueChange={(value) =>
                      setProjectTransfers((prev) => ({
                        ...prev,
                        [project.id]: parseInt(value),
                      }))
                    }
                    placeholder={t("adminDeleteUser.transferSelectPlaceholder")}
                    emptyMessage={t("adminDeleteUser.noUsersAvailable")}
                  />
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
                  <div className="mb-2 font-semibold">{t("adminDeleteUser.confirmTitle")}</div>
                  {deletionType === "soft" ? (
                    <p className="text-sm">
                      {t("adminDeleteUser.confirmSoftDelete", { email: displayName })}
                    </p>
                  ) : (
                    <p className="text-sm">
                      {t("adminDeleteUser.confirmHardDelete", { email: displayName })}
                    </p>
                  )}
                </AlertDescription>
              </Alert>

              <div className="space-y-2">
                <Label htmlFor="confirmation">{t("adminDeleteUser.confirmDescription")}</Label>
                <Input
                  id="confirmation"
                  value={confirmationText}
                  onChange={(e) => setConfirmationText(e.target.value.toUpperCase())}
                  placeholder={confirmationRequired}
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
                    {t("adminDeleteUser.confirmDescription")}
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
              disabled={step === "choose-type" || deleteUser.isPending || isResolvingBlocker}
            >
              <ChevronLeft className="mr-1 h-4 w-4" />
              {t("adminDeleteUser.back")}
            </Button>

            <div className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={deleteUser.isPending || isResolvingBlocker}
              >
                {t("adminDeleteUser.cancel")}
              </Button>

              {step !== "confirm" ? (
                <Button
                  onClick={handleNext}
                  disabled={
                    (step === "choose-type" && !canProceedFromChooseType) ||
                    (step === "check-blockers" && !canProceedFromBlockers) ||
                    (step === "resolve-blockers" && !canProceedFromBlockers) ||
                    (step === "transfer-projects" && !canProceedFromTransfers) ||
                    isCheckingEligibility ||
                    isResolvingBlocker
                  }
                >
                  {isCheckingEligibility ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t("adminDeleteUser.loading")}
                    </>
                  ) : (
                    t("adminDeleteUser.next")
                  )}
                </Button>
              ) : (
                <Button
                  variant="destructive"
                  onClick={handleDelete}
                  disabled={!canConfirm || deleteUser.isPending}
                >
                  {deleteUser.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {deletionType === "soft"
                        ? t("adminDeleteUser.deactivating")
                        : t("adminDeleteUser.deleting")}
                    </>
                  ) : deletionType === "soft" ? (
                    t("adminDeleteUser.deactivateButton")
                  ) : (
                    t("adminDeleteUser.deleteButton")
                  )}
                </Button>
              )}
            </div>
          </div>
        </DialogFooter>
      </DialogContent>

      {/* Guild deletion confirmation dialog */}
      <ConfirmDialog
        open={guildDeleteConfirm !== null}
        onOpenChange={(open) => !open && setGuildDeleteConfirm(null)}
        title={t("adminDeleteUser.deleteGuild")}
        description={t("adminDeleteUser.deleteGuildConfirm", {
          guildName: guildDeleteConfirm?.guild_name,
        })}
        confirmLabel={t("adminDeleteUser.deleteGuild")}
        destructive
        onConfirm={() => guildDeleteConfirm && handleDeleteGuild(guildDeleteConfirm.guild_id)}
        isLoading={deleteGuild.isPending}
      />
    </Dialog>
  );
}
