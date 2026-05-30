import type { ColumnDef } from "@tanstack/react-table";
import type { LucideIcon } from "lucide-react";
import {
  Crown,
  Download,
  LifeBuoy,
  Mail,
  Shield,
  ShieldCheck,
  Trash2,
  UserCheck,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead, UserRole } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAdminUsers } from "@/api/query-keys";
import { AdminDeleteUserDialog } from "@/components/admin/AdminDeleteUserDialog";
import { SortIcon } from "@/components/SortIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  useAdminReactivateUser,
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
import type { TranslateFn } from "@/types/i18n";

// Platform roles ordered least → most privileged. A user can only assign a
// role at or below their own rank (mirrors the backend ``can_assign_role``
// subset rule), so rank-by-index is a faithful client-side gate.
const PLATFORM_ROLE_ORDER: UserRole[] = ["member", "support", "moderator", "admin", "owner"];

const platformRoleRank = (role: UserRole): number => PLATFORM_ROLE_ORDER.indexOf(role);

const platformRoleLabel = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roles.${role}`);

const platformRoleDescription = (role: UserRole, t: TranslateFn): string =>
  t(`platformUsers.roleDescriptions.${role}`);

const ROLE_BADGE: Record<
  UserRole,
  { icon: LucideIcon | null; variant: "default" | "secondary" | "outline" }
> = {
  owner: { icon: Crown, variant: "default" },
  admin: { icon: Shield, variant: "default" },
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
  const [deleteUserTarget, setDeleteUserTarget] = useState<UserRead | null>(null);

  // Viewing the roster needs ``users.read`` (support+); changing roles needs
  // ``roles.assign`` (admin+). The actor can only assign roles at or below
  // their own rank.
  const canView = hasCapability(user, Capability.usersRead);
  const canManageRoles = hasCapability(user, Capability.rolesAssign);
  const canManageUsers = hasCapability(user, Capability.usersManage);
  const canDeleteUsers = hasCapability(user, Capability.usersDelete);
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

  const exportUserCsv = (platformUser: UserRead) => {
    const safeEmail = platformUser.email.replace(/[^a-zA-Z0-9._-]+/g, "_");
    exportPlatformUsers.mutate({
      params: { user_id: [platformUser.id] },
      filename: `user-${platformUser.id}-${safeEmail}.csv`,
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
    return <p className="text-muted-foreground text-sm">{t("platformUsers.loading")}</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("platformUsers.loadError")}</p>;
  }

  const userColumns: ColumnDef<UserRead>[] = [
    {
      accessorKey: "id",
      header: t("platformUsers.columnId"),
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.id}</p>
      ),
    },
    {
      id: "name",
      header: t("platformUsers.columnName"),
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
      header: ({ column }) => {
        const isSorted = column.getIsSorted();
        return (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
              {t("platformUsers.columnEmail")}
              <SortIcon isSorted={isSorted} />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const platformUser = row.original;
        return <p className="text-sm">{platformUser.email}</p>;
      },
      enableSorting: true,
    },
    {
      id: "platform_role",
      header: t("platformUsers.columnRole"),
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
      header: t("platformUsers.columnStatus"),
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
      cell: ({ row }) => {
        const platformUser = row.original;
        const isResetting = resettingUserId === platformUser.id;
        const isSelf = platformUser.id === user?.id;
        // Reset password is a no-op on non-active accounts (the backend
        // rejects it with ADMIN_CANNOT_RESET_INACTIVE), so hide it here too.

        return (
          <div className="flex flex-wrap gap-2">
            {canManageUsers && platformUser.status === "deactivated" && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => reactivateUser.mutate(platformUser.id)}
                disabled={reactivateUser.isPending}
              >
                <UserCheck className="h-4 w-4" />
                {t("platformUsers.reactivate")}
              </Button>
            )}
            {canManageUsers && platformUser.status === "active" && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => handleResetPassword(platformUser.id, platformUser.email)}
                disabled={isResetting || resetPassword.isPending}
              >
                <Mail className="h-4 w-4" />
                {isResetting ? t("common:submitting") : t("platformUsers.resetPassword")}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => exportUserCsv(platformUser)}
              title={t("platformUsers.exportUser")}
            >
              <Download className="h-4 w-4" />
              {t("platformUsers.exportUser")}
            </Button>
            {canDeleteUsers && !isSelf && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setDeleteUserTarget(platformUser)}
                className="text-destructive hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" />
                {t("platformUsers.deleteUser")}
              </Button>
            )}
          </div>
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
            <Download className="mr-1.5 h-4 w-4" />
            {t("platformUsers.exportAll")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={usersQuery.data}
            enableFilterInput
            filterInputColumnKey="email"
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

      {deleteUserTarget && (
        <AdminDeleteUserDialog
          open={deleteUserTarget !== null}
          onOpenChange={(open) => !open && setDeleteUserTarget(null)}
          onSuccess={() => {
            void invalidateAdminUsers();
          }}
          targetUser={deleteUserTarget}
        />
      )}
    </div>
  );
};
