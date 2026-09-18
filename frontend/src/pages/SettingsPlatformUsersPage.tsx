import { CalendarClock, Download, Mail, Trash2, UserCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AdminUserRead, UserRole } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { AdminDeleteUserDialog } from "@/components/admin/AdminDeleteUserDialog";
import {
  canManageUser,
  UserOperatorSettingsSheet,
} from "@/components/admin/UserOperatorSettingsSheet";
import { SortIcon } from "@/components/SortIcon";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import {
  useAdminClearAgeBlock,
  useAdminReactivateUser,
  useAdminTriggerPasswordReset,
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

export const SettingsPlatformUsersPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState<{
    userId: number;
    email: string;
  } | null>(null);
  const [deleteUserTarget, setDeleteUserTarget] = useState<AdminUserRead | null>(null);
  const [managingId, setManagingId] = useState<number | null>(null);

  // Viewing the roster needs ``users.read`` (support+). Everything that writes
  // to an account asks for its own capability, at the point it is offered.
  const canView = hasCapability(user, Capability.usersRead);
  const canDeleteUsers = hasCapability(user, Capability.usersDelete);
  // The support tier holds this one and nothing else that writes to an
  // account: getting somebody back in after a typo is support work.
  const canUnblockAge = hasCapability(user, Capability.usersAgeUnblock);
  const canReactivate = hasCapability(user, Capability.usersManage);

  // What the sheet may offer, by capability. Each maps to the capability its
  // endpoint actually requires: rename and picture removal are
  // ``content.moderate``, suspension is ``users.manage``, the ladder is
  // ``roles.assign``.
  const abilities = {
    canModerateContent: hasCapability(user, Capability.contentModerate),
    canManageUsers: hasCapability(user, Capability.usersManage),
    canManageRoles: hasCapability(user, Capability.rolesAssign),
  };

  const usersQuery = usePlatformUsers({ enabled: canView });

  const adminCountQuery = usePlatformAdminCount({ enabled: canView });

  // Read the row back out of the query, so a save re-renders the sheet with
  // what was actually persisted.
  const managing = usersQuery.data?.find((row) => row.id === managingId) ?? null;

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

  const clearAgeBlock = useAdminClearAgeBlock({
    onSuccess: () => toast.success(t("settings:platformUsers.ageBlockCleared")),
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
        <TableSkeleton rows={8} columns={5} />
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
      id: "username",
      // The whole handle, number included — what the cell draws and what
      // somebody pastes in from a ticket. Accessing the bare name would leave
      // the filter box unable to match the thing it is labelled for.
      accessorFn: (row) => getUserHandle(row),
      header: sortableHeader(t("platformUsers.columnHandle")),
      // The handle is the whole of the identification here. An account's real
      // name is its own to give out, and an operator does not need it to do
      // any of this.
      cell: ({ row }) => <UserHandle user={row.original} className="text-sm" />,
      enableSorting: true,
      sortFn: "alphanumeric",
    },
    {
      accessorKey: "email",
      header: sortableHeader(t("platformUsers.columnEmail")),
      // Shortened by the server (``AdminUserRead``), so this renders what
      // arrived rather than shortening it here.
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.email}</p>
      ),
      enableSorting: true,
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
              : platformUser.status === "suspended"
                ? "platformUsers.suspended"
                : "platformUsers.deactivated";
        const className =
          platformUser.status === "active"
            ? "text-sm text-green-600 dark:text-green-400"
            : "text-muted-foreground text-sm";
        return <span className={className}>{t(labelKey)}</span>;
      },
    },
    {
      id: "manage",
      header: "",
      enableSorting: false,
      cell: ({ row }) => {
        const platformUser = row.original;
        // Nothing to open if this viewer holds none of the capabilities the
        // sheet's controls require against this account.
        if (!canManageUser(abilities, platformUser, user?.id)) return null;
        return (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setManagingId(platformUser.id)}
            aria-label={t("platformUsers.sheet.openLabel", {
              handle: getUserHandle(platformUser),
            })}
          >
            {t("platformUsers.sheet.open")}
          </Button>
        );
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
            {canReactivate && platformUser.status === "deactivated" && (
              <DropdownMenuItem onSelect={() => reactivateUser.mutate(platformUser.id)}>
                <UserCheck className="h-4 w-4" />
                {t("platformUsers.reactivate")}
              </DropdownMenuItem>
            )}
            {canReactivate && platformUser.status === "active" && (
              <DropdownMenuItem
                onSelect={() => handleResetPassword(platformUser.id, platformUser.email)}
                disabled={isResetting || resetPassword.isPending}
              >
                <Mail className="h-4 w-4" />
                {isResetting ? t("common:submitting") : t("platformUsers.resetPassword")}
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
            getRowId={(row) => String(row.id)}
            enableFilterInput
            filterInputColumnKey="username"
            filterInputPlaceholder={t("platformUsers.filterPlaceholder")}
            enableResetSorting
            enablePagination
          />
        </CardContent>

        <UserOperatorSettingsSheet
          user={managing}
          open={managing !== null}
          onOpenChange={(next) => {
            if (!next) setManagingId(null);
          }}
          abilities={abilities}
          actorId={user?.id}
          actorRole={(user?.role ?? "member") as UserRole}
          platformOwnerCount={adminCountQuery.data?.count ?? 0}
        />
      </Card>

      <ConfirmDialog
        open={resetPasswordConfirm !== null}
        onOpenChange={(open) => !open && setResetPasswordConfirm(null)}
        title={t("platformUsers.resetPassword")}
        description={t("platformUsers.resetDescription", {
          email: resetPasswordConfirm?.email ?? "this user",
        })}
        confirmLabel={t("common:send")}
        cancelLabel={t("common:cancel")}
        onConfirm={confirmResetPassword}
        isLoading={resetPassword.isPending}
      />

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
