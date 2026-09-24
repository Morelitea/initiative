/**
 * Everything an operator does to one account, in one place.
 *
 * The users table had grown a column per decision — a name, a role dropdown —
 * and a dropdown menu for the rest, which put the account's handle and the
 * levers that act on it in different places. The community table had already
 * solved this: the row identifies, the sheet decides.
 *
 * Each control saves on its own, the way the cells did, because each is a
 * separate endpoint with its own capability behind it.
 *
 * Every section asks for the capability its own endpoint requires, so each
 * viewer is offered the controls their capabilities carry and no others.
 */

import { ImageOff } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { OperatorUserRead, UserRole } from "@/api/generated/initiativeAPI.schemas";
import { Section, SettingRow } from "@/components/platform/SettingRow";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import {
  useOperatorRemoveAvatar,
  useOperatorSetSuspension,
  useOperatorSetUsername,
  useOperatorUpdatePlatformRole,
} from "@/hooks/useOperatorUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { getUserHandle } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";

/** Platform roles ordered least → most privileged. */
export const PLATFORM_ROLE_ORDER: UserRole[] = [
  "member",
  "support",
  "moderator",
  "operator",
  "owner",
];

export const platformRoleRank = (role: UserRole): number => PLATFORM_ROLE_ORDER.indexOf(role);

const platformRoleLabel = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roles.${role}`);

const platformRoleDescription = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roleDescriptions.${role}`);

/**
 * What this viewer may do to this account. Each flag pairs the viewer's
 * capability with the state the endpoint requires of the target, so a control
 * that would be refused is never drawn.
 */
export type UserSheetAbilities = {
  /** ``content.moderate`` — rename, and take a picture down. */
  canModerateContent: boolean;
  /** ``users.manage`` — suspend and lift. */
  canManageUsers: boolean;
  /** ``roles.assign`` — move somebody up or down the ladder. */
  canManageRoles: boolean;
};

/** True when at least one control would be drawn, i.e. the sheet is worth opening. */
export const canManageUser = (
  abilities: UserSheetAbilities,
  target: OperatorUserRead,
  actorId: number | undefined
): boolean => {
  const isSelf = target.id === actorId;
  const anonymized = target.status === "anonymized";
  if (anonymized) return false;
  if (abilities.canModerateContent && !isSelf) return true;
  if (abilities.canModerateContent && target.avatar_url) return true;
  if (
    abilities.canManageUsers &&
    !isSelf &&
    (target.status === "active" || target.status === "suspended")
  ) {
    return true;
  }
  if (abilities.canManageRoles && !isSelf && target.status === "active") return true;
  return false;
};

export const UserOperatorSettingsSheet = ({
  user,
  open,
  onOpenChange,
  abilities,
  actorId,
  actorRole,
}: {
  user: OperatorUserRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  abilities: UserSheetAbilities;
  actorId: number | undefined;
  actorRole: UserRole;
}) => {
  const { t } = useTranslation(["settings", "common"]);

  const [usernameDraft, setUsernameDraft] = useState("");
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  const [suspendOpen, setSuspendOpen] = useState(false);
  const [suspendReason, setSuspendReason] = useState("");
  const [roleConfirm, setRoleConfirm] = useState<UserRole | null>(null);
  const [avatarConfirm, setAvatarConfirm] = useState(false);

  const setUsername = useOperatorSetUsername({
    onSuccess: () => toast.success(t("platformUsers.usernameChanged")),
    onError: (err) => {
      if (user) setUsernameDraft(user.username);
      toast.error(getErrorMessage(err, "settings:platformUsers.actionError"));
    },
  });

  const setSuspension = useOperatorSetSuspension({
    onSuccess: () => {
      setSuspendOpen(false);
      setSuspendReason("");
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
  });

  const updateRole = useOperatorUpdatePlatformRole({
    onSuccess: (_data, variables) => {
      toast.success(
        t("platformUsers.roleChangeSuccess", {
          role: platformRoleLabel(variables.role, t as TranslateFn),
        })
      );
      setRoleConfirm(null);
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:platformUsers.roleChangeError"));
      setRoleConfirm(null);
    },
  });

  const removeAvatar = useOperatorRemoveAvatar({
    onSuccess: () => {
      toast.success(t("platformUsers.sheet.avatarRemoved"));
      setAvatarConfirm(false);
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:platformUsers.actionError"));
      setAvatarConfirm(false);
    },
  });

  // The draft follows whichever account the sheet was opened for.
  if (user && loadedFor !== user.id) {
    setLoadedFor(user.id);
    setUsernameDraft(user.username);
  }

  if (!user) return null;

  const isSelf = user.id === actorId;
  const targetRank = platformRoleRank(user.role);
  const actorRank = platformRoleRank(actorRole);
  const isSuspended = user.status === "suspended";

  // Each section carries the capability its endpoint requires, and the state
  // the endpoint requires of the target.
  const showIdentity = abilities.canModerateContent && !isSelf;
  const showAvatar = abilities.canModerateContent && Boolean(user.avatar_url);
  const showSuspension =
    abilities.canManageUsers && !isSelf && (user.status === "active" || isSuspended);
  const showRole =
    abilities.canManageRoles && !isSelf && user.status === "active" && actorRank >= targetRank;

  const commitUsername = () => {
    const next = usernameDraft.trim().toLowerCase();
    if (!next || next === user.username) {
      setUsernameDraft(user.username);
      return;
    }
    setUsername.mutate({ userId: user.id, username: next });
  };

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          <SheetHeader>
            <SheetTitle>{getUserHandle(user)}</SheetTitle>
            <SheetDescription>{t("platformUsers.sheet.description")}</SheetDescription>
          </SheetHeader>

          <div className="space-y-6 py-6">
            {(showIdentity || showAvatar) && (
              <Section title={t("platformUsers.sheet.identity")}>
                {showIdentity && (
                  <SettingRow
                    label={t("platformUsers.sheet.usernameLabel")}
                    help={t("platformUsers.sheet.usernameHelp")}
                    htmlFor="operator-user-username"
                    control={
                      <Input
                        id="operator-user-username"
                        className="w-48"
                        value={usernameDraft}
                        autoCapitalize="none"
                        onChange={(event) => setUsernameDraft(event.target.value.toLowerCase())}
                        onBlur={commitUsername}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur();
                        }}
                        disabled={setUsername.isPending}
                      />
                    }
                  />
                )}
                {showAvatar && (
                  <SettingRow
                    label={t("platformUsers.sheet.avatarLabel")}
                    help={t("platformUsers.sheet.avatarHelp")}
                    control={
                      <div className="flex items-center gap-3">
                        {/* The picture itself, because deciding whether it
                            should go is looking at it. */}
                        <ProfileAvatar user={user} hidePresence className="size-10" />
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setAvatarConfirm(true)}
                          disabled={removeAvatar.isPending}
                        >
                          <ImageOff className="h-4 w-4" />
                          {t("platformUsers.sheet.avatarRemove")}
                        </Button>
                      </div>
                    }
                  />
                )}
              </Section>
            )}

            {showSuspension && (
              <Section title={t("platformUsers.sheet.access")}>
                <SettingRow
                  label={t("platformUsers.sheet.suspendLabel")}
                  help={t("platformUsers.sheet.suspendHelp")}
                  htmlFor="operator-user-suspended"
                  control={
                    <Switch
                      id="operator-user-suspended"
                      checked={isSuspended}
                      onCheckedChange={(checked) => {
                        // Lifting takes no explanation; imposing does.
                        if (checked) setSuspendOpen(true);
                        else setSuspension.mutate({ userId: user.id, suspended: false });
                      }}
                      disabled={setSuspension.isPending}
                    />
                  }
                />
              </Section>
            )}

            {showRole && (
              <Section title={t("platformUsers.sheet.role")}>
                <SettingRow
                  label={t("platformUsers.sheet.roleLabel")}
                  help={t("platformUsers.sheet.roleHelp")}
                  htmlFor="operator-user-role"
                  control={
                    <Select
                      value={user.role}
                      onValueChange={(value) => setRoleConfirm(value as UserRole)}
                      disabled={updateRole.isPending}
                    >
                      <SelectTrigger id="operator-user-role" className="h-8 w-[160px]">
                        {platformRoleLabel(user.role, t as TranslateFn)}
                      </SelectTrigger>
                      <SelectContent className="max-w-xs">
                        {PLATFORM_ROLE_ORDER.map((role) => (
                          <SelectItem
                            key={role}
                            value={role}
                            // You cannot mint a role above your own rung.
                            // Demoting the platform's last owner is refused
                            // by the server, which says so.
                            disabled={platformRoleRank(role) > actorRank}
                          >
                            <div className="flex flex-col gap-0.5">
                              <span className="font-medium">
                                {platformRoleLabel(role, t as TranslateFn)}
                              </span>
                              <span className="text-muted-foreground text-xs leading-snug">
                                {platformRoleDescription(role, t as TranslateFn)}
                              </span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  }
                />
              </Section>
            )}
          </div>
        </SheetContent>
      </Sheet>

      {/* Suspending shows its reason to the person it is about, so it is a
          field rather than an internal note. */}
      <ConfirmDialog
        open={suspendOpen}
        onOpenChange={(next) => {
          setSuspendOpen(next);
          if (!next) setSuspendReason("");
        }}
        title={t("platformUsers.suspendTitle", { handle: getUserHandle(user) })}
        description={t("platformUsers.suspendBody")}
        confirmLabel={t("platformUsers.suspend")}
        cancelLabel={t("common:cancel")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={setSuspension.isPending}
        onConfirm={() =>
          setSuspension.mutate({
            userId: user.id,
            suspended: true,
            reason: suspendReason.trim() || undefined,
          })
        }
      >
        <div className="space-y-2">
          <Label htmlFor="operator-suspend-reason">{t("platformUsers.suspendReasonLabel")}</Label>
          <Textarea
            id="operator-suspend-reason"
            value={suspendReason}
            onChange={(event) => setSuspendReason(event.target.value)}
            rows={3}
          />
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={roleConfirm !== null}
        onOpenChange={(next) => !next && setRoleConfirm(null)}
        title={t("platformUsers.changeRoleTitle")}
        description={t("platformUsers.changeRoleDescription", {
          email: user.email,
          role: roleConfirm ? platformRoleLabel(roleConfirm, t as TranslateFn) : "",
        })}
        confirmLabel={t("common:confirm")}
        cancelLabel={t("common:cancel")}
        loadingLabel={t("common:submitting")}
        isLoading={updateRole.isPending}
        onConfirm={() => roleConfirm && updateRole.mutate({ userId: user.id, role: roleConfirm })}
      />

      <ConfirmDialog
        open={avatarConfirm}
        onOpenChange={setAvatarConfirm}
        title={t("platformUsers.sheet.avatarConfirmTitle")}
        description={t("platformUsers.sheet.avatarConfirmBody", {
          handle: getUserHandle(user),
        })}
        confirmLabel={t("platformUsers.sheet.avatarRemove")}
        cancelLabel={t("common:cancel")}
        loadingLabel={t("common:submitting")}
        destructive
        isLoading={removeAvatar.isPending}
        onConfirm={() => removeAvatar.mutate(user.id)}
      />
    </>
  );
};
