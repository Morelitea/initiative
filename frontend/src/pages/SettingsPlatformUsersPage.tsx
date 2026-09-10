import type { LucideIcon } from "lucide-react";
import {
  CalendarClock,
  Crown,
  Download,
  LifeBuoy,
  Mail,
  PenLine,
  Shield,
  ShieldCheck,
  ShieldOff,
  Snowflake,
  Trash2,
  UserCheck,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AdminUserRead, UserRole } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { AdminDeleteUserDialog } from "@/components/admin/AdminDeleteUserDialog";
import { SortIcon } from "@/components/SortIcon";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { UserHandle } from "@/components/UserHandle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  useAdminClearAgeBlock,
  useAdminReactivateUser,
  useAdminSetSuspension,
  useAdminSetUsername,
  useAdminTriggerPasswordReset,
  useAdminUpdatePlatformRole,
  useExportPlatformUsersCsv,
  usePlatformAdminCount,
  usePlatformUsers,
} from "@/hooks/useAdmin";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";
import type { AppColumn, AppColumnDef } from "@/lib/table";
import { getUserHandle } from "@/lib/userDisplay";
import type { TranslateFn } from "@/types/i18n";

// Platform roles ordered least → most privileged. A user can only assign a
// role at or below their own rank (mirrors the backend ``can_assign_role``
// subset rule), so rank-by-index is a faithful client-side gate.
const PLATFORM_ROLE_ORDER: UserRole[] = ["member", "support", "moderator", "operator", "owner"];

const platformRoleRank = (role: UserRole): number => PLATFORM_ROLE_ORDER.indexOf(role);

const platformRoleLabel = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roles.${role}`);

const platformRoleDescription = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roleDescriptions.${role}`);

/**
 * The header of a sortable column: the label, and the arrow that says which
 * way it is pointing. Every sortable column on this table uses it, so they
 * click alike and none of them is the odd one out that looks like plain text.
 */
const sortableHeader =
  (label: string) =>
  ({ column }: { column: AppColumn<AdminUserRead> }) => {
    const isSorted = column.getIsSorted();
    return (
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
          {label}
          <SortIcon isSorted={isSorted} />
        </Button>
      </div>
    );
  };

// Accounts ordered by how much of the app is left to them, rather than
// alphabetically — "anonymized, active, deactivated, suspended" is an order
// no one is looking for. Sorting brings the accounts needing attention
// together at one end.
const STATUS_ORDER: Record<string, number> = {
  active: 0,
  suspended: 1,
  deactivated: 2,
  anonymized: 3,
};

const ROLE_BADGE: Record<
  UserRole,
  { icon: LucideIcon | null; variant: "default" | "secondary" | "outline" }
> = {
  owner: { icon: Crown, variant: "default" },
  operator: { icon: Shield, variant: "default" },
  moderator: { icon: ShieldCheck, variant: "secondary" },
  support: { icon: LifeBuoy, variant: "secondary" },
  member: { icon: null, variant: "outline" },
};

// A role badge with a hover tooltip describing the role. Used wherever the
// role isn't editable (read-only viewers, the actor's own row, higher-ranked
// targets) so the meaning of each role is still discoverable.
const PlatformRoleBadge = ({ role, t }: { role: UserRole; t: TranslateFn }) => {
  const { icon: Icon, variant } = ROLE_BADGE[role];
  return (
    <TooltipProvider>
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <span className="inline-flex cursor-help">
            <Badge variant={variant} className="inline-flex items-center gap-1">
              {Icon && <Icon className="h-3 w-3" />}
              {platformRoleLabel(role, t)}
            </Badge>
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          {platformRoleDescription(role, t)}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export const SettingsPlatformUsersPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState<{
    userId: number;
    email: string;
  } | null>(null);
  const [roleChangeConfirm, setRoleChangeConfirm] = useState<{
    userId: number;
    email: string;
    currentRole: UserRole;
    newRole: UserRole;
  } | null>(null);
  const [deleteUserTarget, setDeleteUserTarget] = useState<AdminUserRead | null>(null);

  // Viewing the roster needs ``users.read`` (support+); changing roles needs
  // ``roles.assign`` (operator+). The actor can only assign roles at or below
  // their own rank.
  const canView = hasCapability(user, Capability.usersRead);
  const canManageRoles = hasCapability(user, Capability.rolesAssign);
  const canManageUsers = hasCapability(user, Capability.usersManage);
  const canDeleteUsers = hasCapability(user, Capability.usersDelete);
  const canModerateContent = hasCapability(user, Capability.contentModerate);
  // The support tier holds this one and nothing else that writes to an
  // account: getting somebody back in after a typo is support work.
  const canUnblockAge = hasCapability(user, Capability.usersAgeUnblock);
  const actorRank = platformRoleRank(user?.role ?? "member");

  const usersQuery = usePlatformUsers({ enabled: canView });

  const adminCountQuery = usePlatformAdminCount({ enabled: canView });

  const resetPassword = useAdminTriggerPasswordReset({
    onSuccess: (_data, userId) => {
      const userEmail = usersQuery.data?.find((u) => u.id === userId)?.email ?? "user";
      toast.success(t("platformUsers.resetSuccess", { email: userEmail }));
      setResettingUserId(null);
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "settings:platformUsers.resetError"));
      setResettingUserId(null);
    },
  });

  const [renameTarget, setRenameTarget] = useState<AdminUserRead | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [suspendTarget, setSuspendTarget] = useState<AdminUserRead | null>(null);
  const [suspendReason, setSuspendReason] = useState("");

  const setUsername = useAdminSetUsername({
    onSuccess: () => {
      toast.success(t("platformUsers.usernameChanged"));
      setRenameTarget(null);
      setRenameValue("");
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
  });

  const clearAgeBlock = useAdminClearAgeBlock({
    onSuccess: () => toast.success(t("settings:platformUsers.ageBlockCleared")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
  });

  const setSuspension = useAdminSetSuspension({
    onSuccess: () => {
      setSuspendTarget(null);
      setSuspendReason("");
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
  });

  const reactivateUser = useAdminReactivateUser({
    onSuccess: (_data, userId) => {
      const userEmail = usersQuery.data?.find((u) => u.id === userId)?.email ?? "user";
      toast.success(t("platformUsers.reactivateSuccess", { email: userEmail }));
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "settings:platformUsers.reactivateError"));
    },
  });

  const handleResetPassword = (userId: number, email: string) => {
    setResetPasswordConfirm({ userId, email });
  };

  const confirmResetPassword = () => {
    if (resetPasswordConfirm) {
      setResettingUserId(resetPasswordConfirm.userId);
      resetPassword.mutate(resetPasswordConfirm.userId);
      setResetPasswordConfirm(null);
    }
  };

  const updatePlatformRole = useAdminUpdatePlatformRole({
    onSuccess: (_data, variables) => {
      // Read the new role off the mutation variables, not off
      // ``roleChangeConfirm`` — the confirm dialog may have already closed
      // by the time this fires.
      toast.success(
        t("platformUsers.roleChangeSuccess", {
          role: platformRoleLabel(variables.role, t as TranslateFn),
        })
      );
      setRoleChangeConfirm(null);
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "settings:platformUsers.roleChangeError"));
    },
  });

  const confirmRoleChange = () => {
    if (roleChangeConfirm) {
      updatePlatformRole.mutate({
        userId: roleChangeConfirm.userId,
        role: roleChangeConfirm.newRole,
      });
    }
  };

  const exportPlatformUsers = useExportPlatformUsersCsv({
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:platformUsers.exportError"));
    },
  });

  const exportUserCsv = (platformUser: AdminUserRead) => {
    // Named by handle. The address never arrives here in full any more, and a
    // filename outlives the download — in a directory listing, in whatever it
    // gets mailed on to.
    const safeHandle = platformUser.username.replace(/[^a-zA-Z0-9._-]+/g, "_");
    exportPlatformUsers.mutate({
      params: { user_id: [platformUser.id] },
      filename: `user-${platformUser.id}-${safeHandle}.csv`,
    });
  };

  const exportAllUsersCsv = () => {
    const datestamp = new Date().toISOString().slice(0, 10);
    exportPlatformUsers.mutate({
      params: {},
      filename: `platform-users-${datestamp}.csv`,
    });
  };

  if (!canView) {
    return <p className="text-muted-foreground text-sm">{t("platformUsers.permissionRequired")}</p>;
  }

  if (usersQuery.isLoading) {
    return (
      <SkeletonRegion label={t("platformUsers.loading")}>
        <TableSkeleton rows={8} columns={6} />
      </SkeletonRegion>
    );
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("platformUsers.loadError")}</p>;
  }

  const userColumns: AppColumnDef<AdminUserRead>[] = [
    {
      accessorKey: "id",
      header: sortableHeader(t("platformUsers.columnId")),
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.id}</p>
      ),
      // The id counts up as accounts are made, so sorting it is sorting by
      // when somebody joined — which is why there is no separate date column.
      enableSorting: true,
    },
    {
      accessorKey: "username",
      header: sortableHeader(t("platformUsers.columnHandle")),
      // The handle leads identification here the way it does on a guild
      // roster: it is unique, it is what the person is addressed by, and —
      // now that the address is masked — it is the only thing on the row you
      // can search for and expect to find.
      cell: ({ row }) => <UserHandle user={row.original} className="text-sm" />,
      enableSorting: true,
      sortFn: "alphanumeric",
    },
    {
      id: "name",
      accessorFn: (row) => row.full_name?.trim() ?? "",
      header: sortableHeader(t("platformUsers.columnName")),
      enableSorting: true,
      sortFn: "alphanumeric",
      cell: ({ row }) => {
        const platformUser = row.original;
        const displayName = platformUser.full_name?.trim() || "—";
        return (
          <div>
            <p className="font-medium">{displayName}</p>
          </div>
        );
      },
    },
    {
      accessorKey: "email",
      header: sortableHeader(t("platformUsers.columnEmail")),
      // Masked before it leaves the server (``AdminUserRead``), so this
      // renders whatever arrived rather than masking it here — a client-side
      // mask would still ship the address to the browser.
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.email}</p>
      ),
      enableSorting: true,
    },
    {
      id: "platform_role",
      accessorFn: (row) => row.role,
      header: sortableHeader(t("platformUsers.columnRole")),
      enableSorting: true,
      // By privilege, not by name: alphabetically "owner" lands between
      // "operator" and "support", which is the one ordering nobody wants.
      // Ascending puts members first and owners last.
      sortFn: (rowA, rowB) =>
        platformRoleRank(rowA.original.role) - platformRoleRank(rowB.original.role),
      cell: ({ row }) => {
        const platformUser = row.original;
        const isSelf = platformUser.id === user?.id;
        const targetRank = platformRoleRank(platformUser.role);
        // You can't edit your own role, a non-active account, or a user who
        // outranks you. The backend enforces the same; this just hides
        // controls that would 403.
        const editable =
          canManageRoles && platformUser.status === "active" && !isSelf && actorRank >= targetRank;
        // Don't let the last platform owner be demoted out of ownership.
        const isLastOwner =
          platformUser.role === "owner" && (adminCountQuery.data?.count ?? 0) <= 1;

        if (!editable) {
          return (
            <div className="flex">
              <PlatformRoleBadge role={platformUser.role} t={t as TranslateFn} />
            </div>
          );
        }

        return (
          <Select
            value={platformUser.role}
            onValueChange={(value) =>
              setRoleChangeConfirm({
                userId: platformUser.id,
                email: platformUser.email,
                currentRole: platformUser.role,
                newRole: value as UserRole,
              })
            }
            disabled={updatePlatformRole.isPending}
          >
            <SelectTrigger className="h-8 w-[160px]">
              {/* Render the label directly rather than <SelectValue> so the
                  per-item descriptions below don't leak into the trigger. */}
              {platformRoleLabel(platformUser.role, t as TranslateFn)}
            </SelectTrigger>
            <SelectContent className="max-w-xs">
              {PLATFORM_ROLE_ORDER.map((role) => {
                // Can't assign above your own rank; the last owner can only
                // stay an owner.
                const disabled =
                  platformRoleRank(role) > actorRank || (isLastOwner && role !== "owner");
                return (
                  <SelectItem key={role} value={role} disabled={disabled}>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium">
                        {platformRoleLabel(role, t as TranslateFn)}
                      </span>
                      <span className="text-muted-foreground text-xs leading-snug">
                        {platformRoleDescription(role, t as TranslateFn)}
                      </span>
                    </div>
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
        );
      },
    },
    {
      id: "status",
      accessorFn: (row) => row.status,
      header: sortableHeader(t("platformUsers.columnStatus")),
      enableSorting: true,
      sortFn: (rowA, rowB) =>
        (STATUS_ORDER[rowA.original.status] ?? 99) - (STATUS_ORDER[rowB.original.status] ?? 99),
      cell: ({ row }) => {
        const platformUser = row.original;
        const labelKey =
          platformUser.status === "active"
            ? "platformUsers.active"
            : platformUser.status === "anonymized"
              ? "platformUsers.anonymized"
              : "platformUsers.deactivated";
        const className =
          platformUser.status === "active"
            ? "text-sm text-green-600 dark:text-green-400"
            : "text-muted-foreground text-sm";
        return <span className={className}>{t(labelKey)}</span>;
      },
    },
    {
      id: "actions",
      header: t("platformUsers.columnActions"),
      enableSorting: false,
      cell: ({ row }) => {
        const platformUser = row.original;
        const isResetting = resettingUserId === platformUser.id;
        const isSelf = platformUser.id === user?.id;
        // Reset password is a no-op on non-active accounts (the backend
        // rejects it with ADMIN_CANNOT_RESET_INACTIVE), so hide it here too.

        return (
          <RowActionsMenu subject={getUserHandle(platformUser)}>
            {canManageUsers && platformUser.status === "deactivated" && (
              <DropdownMenuItem onSelect={() => reactivateUser.mutate(platformUser.id)}>
                <UserCheck className="h-4 w-4" />
                {t("platformUsers.reactivate")}
              </DropdownMenuItem>
            )}
            {canManageUsers && platformUser.status === "active" && (
              <DropdownMenuItem
                onSelect={() => handleResetPassword(platformUser.id, platformUser.email)}
                disabled={isResetting || resetPassword.isPending}
              >
                <Mail className="h-4 w-4" />
                {isResetting ? t("common:submitting") : t("platformUsers.resetPassword")}
              </DropdownMenuItem>
            )}
            {canModerateContent && !isSelf && platformUser.status !== "anonymized" && (
              <DropdownMenuItem onSelect={() => setRenameTarget(platformUser)}>
                <PenLine className="h-4 w-4" />
                {t("platformUsers.changeUsername")}
              </DropdownMenuItem>
            )}
            {canUnblockAge && platformUser.age_below_minimum_at && (
              <DropdownMenuItem
                onSelect={() => clearAgeBlock.mutate(platformUser.id)}
                disabled={clearAgeBlock.isPending}
              >
                <CalendarClock className="h-4 w-4" />
                {t("platformUsers.clearAgeBlock")}
              </DropdownMenuItem>
            )}
            {canManageUsers &&
              !isSelf &&
              (platformUser.status === "active" || platformUser.status === "suspended") && (
                <DropdownMenuItem
                  onSelect={() =>
                    platformUser.status === "suspended"
                      ? setSuspension.mutate({ userId: platformUser.id, suspended: false })
                      : setSuspendTarget(platformUser)
                  }
                  disabled={setSuspension.isPending}
                >
                  {platformUser.status === "suspended" ? (
                    <>
                      <ShieldOff className="h-4 w-4" />
                      {t("platformUsers.unsuspend")}
                    </>
                  ) : (
                    <>
                      <Snowflake className="h-4 w-4" />
                      {t("platformUsers.suspend")}
                    </>
                  )}
                </DropdownMenuItem>
              )}
            <DropdownMenuItem onSelect={() => exportUserCsv(platformUser)}>
              <Download className="h-4 w-4" />
              {t("platformUsers.exportUser")}
            </DropdownMenuItem>
            {canDeleteUsers && !isSelf && (
              <>
                {/* Deleting an account is the one thing here that cannot be
                    undone, so it sits below a rule rather than in the run. */}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive"
                  onSelect={() => setDeleteUserTarget(platformUser)}
                >
                  <Trash2 className="h-4 w-4" />
                  {t("platformUsers.deleteUser")}
                </DropdownMenuItem>
              </>
            )}
          </RowActionsMenu>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>{t("platformUsers.title")}</CardTitle>
            <CardDescription>{t("platformUsers.description")}</CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={exportAllUsersCsv}
            disabled={!usersQuery.data?.length}
          >
            <Download className="h-4 w-4" />
            {t("platformUsers.exportAll")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={usersQuery.data}
            enableFilterInput
            filterInputColumnKey="username"
            filterInputPlaceholder={t("platformUsers.filterPlaceholder")}
            enableResetSorting
            enablePagination
          />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={resetPasswordConfirm !== null}
        onOpenChange={(open) => !open && setResetPasswordConfirm(null)}
        title={t("platformUsers.resetPassword")}
        description={t("platformUsers.resetDescription", {
          email: resetPasswordConfirm?.email ?? "this user",
        })}
        confirmLabel={t("common:send")}
        onConfirm={confirmResetPassword}
        isLoading={resetPassword.isPending}
      />

      <ConfirmDialog
        open={roleChangeConfirm !== null}
        onOpenChange={(open) => !open && setRoleChangeConfirm(null)}
        title={t("platformUsers.changeRoleTitle")}
        description={t("platformUsers.changeRoleDescription", {
          email: roleChangeConfirm?.email ?? "this user",
          role: roleChangeConfirm
            ? platformRoleLabel(roleChangeConfirm.newRole, t as TranslateFn)
            : "",
        })}
        confirmLabel={t("common:confirm")}
        onConfirm={confirmRoleChange}
        isLoading={updatePlatformRole.isPending}
      />

      {/* A rename is typed, so it needs a field rather than a confirmation. */}
      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRenameTarget(null);
            setRenameValue("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("platformUsers.changeUsernameTitle", {
                handle: renameTarget ? getUserHandle(renameTarget) : "",
              })}
            </DialogTitle>
            <DialogDescription>{t("platformUsers.changeUsernameBody")}</DialogDescription>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value.toLowerCase())}
            autoCapitalize="none"
            placeholder={t("platformUsers.changeUsername")}
          />
          <DialogFooter>
            <Button
              type="button"
              disabled={!renameValue.trim() || setUsername.isPending}
              onClick={() =>
                renameTarget &&
                setUsername.mutate({
                  userId: renameTarget.id,
                  username: renameValue.trim().toLowerCase(),
                })
              }
            >
              {setUsername.isPending ? t("common:submitting") : t("common:save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Suspending takes nothing away, and the reason is shown to the person
          it is about — so it is a field here, not an internal note. */}
      <Dialog
        open={suspendTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSuspendTarget(null);
            setSuspendReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("platformUsers.suspendTitle", {
                handle: suspendTarget ? getUserHandle(suspendTarget) : "",
              })}
            </DialogTitle>
            <DialogDescription>{t("platformUsers.suspendBody")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="suspend-reason">{t("platformUsers.suspendReasonLabel")}</Label>
            <Textarea
              id="suspend-reason"
              value={suspendReason}
              onChange={(event) => setSuspendReason(event.target.value)}
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="destructive"
              disabled={setSuspension.isPending}
              onClick={() =>
                suspendTarget &&
                setSuspension.mutate({
                  userId: suspendTarget.id,
                  suspended: true,
                  reason: suspendReason.trim() || undefined,
                })
              }
            >
              {setSuspension.isPending ? t("common:submitting") : t("platformUsers.suspend")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {deleteUserTarget && (
        <AdminDeleteUserDialog
          open={deleteUserTarget !== null}
          onOpenChange={(open) => !open && setDeleteUserTarget(null)}
          onSuccess={() => {
            void invalidate(q.adminUsers());
          }}
          targetUser={deleteUserTarget}
        />
      )}
    </div>
  );
};
