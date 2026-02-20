import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Mail, Shield, ShieldOff, Trash2, UserCheck } from "lucide-react";

import {
  triggerPasswordResetApiV1AdminUsersUserIdResetPasswordPost,
  reactivateUserApiV1AdminUsersUserIdReactivatePost,
  updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch,
} from "@/api/generated/admin/admin";
import { usePlatformUsers, usePlatformAdminCount } from "@/hooks/useAdmin";
import { invalidateAdminUsers } from "@/api/query-keys";
import { AdminDeleteUserDialog } from "@/components/admin/AdminDeleteUserDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useAuth } from "@/hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import type { User, UserRole } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { SortIcon } from "@/components/SortIcon";

export const SettingsPlatformUsersPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const { data: roleLabels } = useRoleLabels();
  const adminLabel = getRoleLabel("admin", roleLabels);
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
  const [deleteUserTarget, setDeleteUserTarget] = useState<User | null>(null);

  const isAdmin = user?.role === "admin";

  const usersQuery = usePlatformUsers({ enabled: isAdmin });

  const adminCountQuery = usePlatformAdminCount({ enabled: isAdmin });

  const resetPassword = useMutation({
    mutationFn: async (userId: number) => {
      await triggerPasswordResetApiV1AdminUsersUserIdResetPasswordPost(userId);
    },
    onSuccess: (_data, userId) => {
      const userEmail = usersQuery.data?.find((u) => u.id === userId)?.email ?? "user";
      toast.success(t("platformUsers.resetSuccess", { email: userEmail }));
      setResettingUserId(null);
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("platformUsers.resetError");
      toast.error(message);
      setResettingUserId(null);
    },
  });

  const reactivateUser = useMutation({
    mutationFn: async (userId: number) => {
      await reactivateUserApiV1AdminUsersUserIdReactivatePost(userId);
    },
    onSuccess: (_data, userId) => {
      const userEmail = usersQuery.data?.find((u) => u.id === userId)?.email ?? "user";
      toast.success(t("platformUsers.reactivateSuccess", { email: userEmail }));
      void usersQuery.refetch();
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("platformUsers.reactivateError");
      toast.error(message);
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

  const updatePlatformRole = useMutation({
    mutationFn: async ({ userId, role }: { userId: number; role: UserRole }) => {
      await updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch(userId, { role } as Parameters<
        typeof updatePlatformRoleApiV1AdminUsersUserIdPlatformRolePatch
      >[1]);
    },
    onSuccess: () => {
      void invalidateAdminUsers();
      toast.success(
        roleChangeConfirm?.newRole === "admin"
          ? t("platformUsers.promoteSuccess")
          : t("platformUsers.demoteSuccess")
      );
      setRoleChangeConfirm(null);
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        t("platformUsers.roleChangeError");
      toast.error(message);
    },
  });

  const handlePromote = (userId: number, email: string) => {
    setRoleChangeConfirm({ userId, email, currentRole: "member", newRole: "admin" });
  };

  const handleDemote = (userId: number, email: string) => {
    setRoleChangeConfirm({ userId, email, currentRole: "admin", newRole: "member" });
  };

  const confirmRoleChange = () => {
    if (roleChangeConfirm) {
      updatePlatformRole.mutate({
        userId: roleChangeConfirm.userId,
        role: roleChangeConfirm.newRole,
      });
    }
  };

  if (!isAdmin) {
    return (
      <p className="text-muted-foreground text-sm">
        {t("platformUsers.permissionRequired", { adminLabel })}
      </p>
    );
  }

  if (usersQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("platformUsers.loading")}</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("platformUsers.loadError")}</p>;
  }

  const userColumns: ColumnDef<User>[] = [
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
        const isPlatformAdmin = platformUser.role === "admin";

        return (
          <div className="flex">
            {isPlatformAdmin ? (
              <Badge variant="default" className="inline-flex items-center gap-1">
                <Shield className="h-3 w-3" />
                {getRoleLabel("admin", roleLabels)}
              </Badge>
            ) : (
              <Badge variant="secondary">{getRoleLabel("member", roleLabels)}</Badge>
            )}
          </div>
        );
      },
    },
    {
      id: "status",
      header: t("platformUsers.columnStatus"),
      cell: ({ row }) => {
        const platformUser = row.original;
        return (
          <span
            className={
              platformUser.is_active
                ? "text-sm text-green-600 dark:text-green-400"
                : "text-muted-foreground text-sm"
            }
          >
            {platformUser.is_active ? t("platformUsers.active") : t("platformUsers.inactive")}
          </span>
        );
      },
    },
    {
      id: "actions",
      header: t("platformUsers.columnActions"),
      cell: ({ row }) => {
        const platformUser = row.original;
        const isResetting = resettingUserId === platformUser.id;
        const isPlatformAdmin = platformUser.role === "admin";
        const isSelf = platformUser.id === user?.id;
        const isLastAdmin = isPlatformAdmin && (adminCountQuery.data?.count ?? 0) <= 1;

        return (
          <div className="flex flex-wrap gap-2">
            {isPlatformAdmin && !isSelf && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => handleDemote(platformUser.id, platformUser.email)}
                disabled={isLastAdmin || updatePlatformRole.isPending}
                title={isLastAdmin ? t("platformUsers.cannotDemoteLastAdmin") : undefined}
              >
                <ShieldOff className="h-4 w-4" />
                {t("platformUsers.demoteToUser")}
              </Button>
            )}
            {!isPlatformAdmin && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => handlePromote(platformUser.id, platformUser.email)}
                disabled={updatePlatformRole.isPending}
              >
                <Shield className="h-4 w-4" />
                {t("platformUsers.promoteToAdmin")}
              </Button>
            )}
            {!platformUser.is_active ? (
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
            ) : (
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
            {!isSelf && (
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
        <CardHeader>
          <CardTitle>{t("platformUsers.title")}</CardTitle>
          <CardDescription>{t("platformUsers.description")}</CardDescription>
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
        title={
          roleChangeConfirm?.newRole === "admin"
            ? t("platformUsers.promoteToAdmin")
            : t("platformUsers.demoteToUser")
        }
        description={
          roleChangeConfirm?.newRole === "admin"
            ? t("platformUsers.promoteDescription", {
                email: roleChangeConfirm?.email ?? "this user",
              })
            : t("platformUsers.demoteDescription", {
                email: roleChangeConfirm?.email ?? "this user",
              })
        }
        confirmLabel={
          roleChangeConfirm?.newRole === "admin"
            ? t("platformUsers.promoteToAdmin")
            : t("platformUsers.demoteToUser")
        }
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
