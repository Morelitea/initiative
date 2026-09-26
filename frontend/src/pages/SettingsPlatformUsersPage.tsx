import type { PaginationState, SortingState } from "@tanstack/react-table";
import { CalendarClock, Download, LockOpen, Mail, Trash2, UserCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { OperatorUserRead, UserRole } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { OperatorDeleteUserDialog } from "@/components/platform/OperatorDeleteUserDialog";
import {
  canManageUser,
  UserOperatorSettingsSheet,
} from "@/components/platform/UserOperatorSettingsSheet";
import { SortHeader } from "@/components/SortIcon";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { UserHandle } from "@/components/UserHandle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import { useAuth } from "@/hooks/useAuth";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  useExportPlatformUsersCsv,
  useOperatorClearAgeBlock,
  useOperatorLiftSignInLock,
  useOperatorReactivateUser,
  useOperatorRestoreUser,
  useOperatorTriggerPasswordReset,
  usePlatformUsers,
} from "@/hooks/useOperatorUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";
import { getUserHandle } from "@/lib/userDisplay";

/** How long typing settles before the roster is asked again. */
const SEARCH_SETTLES_MS = 250;

/** The columns the server sorts the roster by. Status sorts by how much of the
 *  app is left to an account, which brings the ones needing attention together
 *  at one end. */
const SORT_FIELDS = new Set(["id", "username", "status"]);

export const SettingsPlatformUsersPage = () => {
  const { t, i18n } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState<{
    userId: number;
    handle: string;
  } | null>(null);
  const [deleteUserTarget, setDeleteUserTarget] = useState<OperatorUserRead | null>(null);
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

  // Searched, sorted and paged on the server: the roster is every account on
  // the deployment, so the table only ever holds the page on screen.
  const [draft, setDraft] = useState("");
  const search = useDebouncedValue(draft, SEARCH_SETTLES_MS);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const sort = sorting[0];
  const usersQuery = usePlatformUsers(
    {
      search: search.trim() || undefined,
      page,
      page_size: pageSize,
      ...(sort && SORT_FIELDS.has(sort.id)
        ? {
            sort_by: sort.id as "id" | "username" | "status",
            sort_dir: sort.desc ? ("desc" as const) : ("asc" as const),
          }
        : {}),
    },
    { enabled: canView }
  );
  const rows = usersQuery.data?.items ?? [];
  const totalCount = usersQuery.data?.total_count ?? 0;

  // Read the row back out of the query, so a save re-renders the sheet with
  // what was actually persisted.
  const managing = rows.find((row) => row.id === managingId) ?? null;

  const resetPassword = useOperatorTriggerPasswordReset({
    onSuccess: (_data, userId) => {
      const handle = rows.find((u) => u.id === userId)?.username ?? "account";
      toast.success(t("platformUsers.resetSuccess", { handle }));
      setResettingUserId(null);
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "settings:platformUsers.resetError"));
      setResettingUserId(null);
    },
  });

  const clearAgeBlock = useOperatorClearAgeBlock({
    onSuccess: () => toast.success(t("settings:platformUsers.ageBlockCleared")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
  });

  const liftSignInLock = useOperatorLiftSignInLock({
    onSuccess: () => toast.success(t("settings:platformUsers.signInLockLifted")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:platformUsers.actionError")),
  });

  const reactivateUser = useOperatorReactivateUser({
    onSuccess: (_data, userId) => {
      const handle = rows.find((u) => u.id === userId)?.username ?? "account";
      toast.success(t("platformUsers.reactivateSuccess", { handle }));
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "settings:platformUsers.reactivateError"));
    },
  });

  const restoreUser = useOperatorRestoreUser({
    onSuccess: (_data, userId) => {
      const handle = rows.find((u) => u.id === userId)?.username ?? "account";
      toast.success(t("platformUsers.restoreSuccess", { handle }));
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "settings:platformUsers.restoreError"));
    },
  });

  const handleResetPassword = (userId: number, handle: string) => {
    setResetPasswordConfirm({ userId, handle });
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

  const exportUserCsv = (platformUser: OperatorUserRead) => {
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

  const userColumns: AppColumnDef<OperatorUserRead>[] = [
    {
      accessorKey: "id",
      header: ({ column }) => <SortHeader column={column} label={t("platformUsers.columnId")} />,
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.id}</p>
      ),
      // The id counts up as accounts are made, so sorting it is sorting by
      // when somebody joined — which is why there is no separate date column.
      enableSorting: true,
    },
    {
      id: "username",
      accessorFn: (row) => getUserHandle(row),
      header: ({ column }) => (
        <SortHeader column={column} label={t("platformUsers.columnHandle")} />
      ),
      // The handle is the whole of the identification here. An account's real
      // name is its own to give out, and an operator does not need it to do
      // any of this.
      cell: ({ row }) => <UserHandle user={row.original} className="text-sm" />,
      enableSorting: true,
    },
    {
      id: "status",
      accessorFn: (row) => row.status,
      header: ({ column }) => (
        <SortHeader column={column} label={t("platformUsers.columnStatus")} />
      ),
      enableSorting: true,
      cell: ({ row }) => {
        const platformUser = row.original;
        // A deleted account is the one status with a date attached and a way
        // back, so it is a tag rather than a word — the same tag a deleted
        // community carries in the Communities table.
        if (platformUser.status === "deleted") {
          return (
            <div className="space-y-0.5">
              <Badge variant="destructive">{t("platformUsers.deleted")}</Badge>
              {platformUser.purge_at ? (
                <p className="text-muted-foreground text-xs">
                  {t("platformUsers.erasedOn", {
                    date: new Date(platformUser.purge_at).toLocaleDateString(
                      i18n.resolvedLanguage ?? i18n.language,
                      { year: "numeric", month: "short", day: "numeric" }
                    ),
                  })}
                </p>
              ) : (
                <p className="text-muted-foreground text-xs">{t("platformUsers.erasedNever")}</p>
              )}
            </div>
          );
        }
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
        const signInLocked = platformUser.sign_in_held_at || platformUser.sign_in_locked_until;
        return (
          <div className="space-y-0.5">
            <span className={className}>{t(labelKey)}</span>
            {signInLocked && (
              <div>
                <Badge variant="outline">{t("platformUsers.signInLocked")}</Badge>
              </div>
            )}
          </div>
        );
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
        // rejects it with OPERATOR_CANNOT_RESET_INACTIVE), so hide it here too.

        return (
          <RowActionsMenu subject={getUserHandle(platformUser)}>
            {canReactivate && platformUser.status === "deactivated" && (
              <DropdownMenuItem onSelect={() => reactivateUser.mutate(platformUser.id)}>
                <UserCheck className="h-4 w-4" />
                {t("platformUsers.reactivate")}
              </DropdownMenuItem>
            )}
            {/* Distinct from reactivating: nothing was dropped, so this puts
                the account back exactly where it was. Its holder can do the
                same thing by simply signing in. */}
            {canReactivate && platformUser.status === "deleted" && (
              <DropdownMenuItem
                onSelect={() => restoreUser.mutate(platformUser.id)}
                disabled={restoreUser.isPending}
              >
                <UserCheck className="h-4 w-4" />
                {t("platformUsers.restore")}
              </DropdownMenuItem>
            )}
            {canReactivate && platformUser.status === "active" && (
              <DropdownMenuItem
                onSelect={() => handleResetPassword(platformUser.id, platformUser.username)}
                disabled={isResetting || resetPassword.isPending}
              >
                <Mail className="h-4 w-4" />
                {isResetting ? t("common:submitting") : t("platformUsers.resetPassword")}
              </DropdownMenuItem>
            )}
            {abilities.canManageUsers &&
              (platformUser.sign_in_held_at || platformUser.sign_in_locked_until) && (
                <DropdownMenuItem
                  onSelect={() => liftSignInLock.mutate(platformUser.id)}
                  disabled={liftSignInLock.isPending}
                >
                  <LockOpen className="h-4 w-4" />
                  {t("platformUsers.liftSignInLock")}
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
            disabled={!totalCount}
          >
            <Download className="h-4 w-4" />
            {t("platformUsers.exportAll")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={rows}
            getRowId={(row) => String(row.id)}
            enableFilterInput
            filterInputPlaceholder={t("platformUsers.filterPlaceholder")}
            filterValue={draft}
            onFilterValueChange={(value) => {
              setDraft(value);
              setPage(1);
            }}
            manualSorting
            sorting={sorting}
            onSortingChange={(next) => {
              setSorting(next);
              setPage(1);
            }}
            enableResetSorting
            enablePagination
            manualPagination
            pageCount={Math.max(1, Math.ceil(totalCount / pageSize))}
            rowCount={totalCount}
            pageIndex={page - 1}
            onPaginationChange={(next: PaginationState) => {
              if (next.pageSize !== pageSize) {
                setPageSize(next.pageSize);
                setPage(1);
              } else {
                setPage(next.pageIndex + 1);
              }
            }}
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
        />
      </Card>

      <ConfirmDialog
        open={resetPasswordConfirm !== null}
        onOpenChange={(open) => !open && setResetPasswordConfirm(null)}
        title={t("platformUsers.resetPassword")}
        description={t("platformUsers.resetDescription", {
          handle: resetPasswordConfirm?.handle ?? "this account",
        })}
        confirmLabel={t("common:send")}
        cancelLabel={t("common:cancel")}
        onConfirm={confirmResetPassword}
        isLoading={resetPassword.isPending}
      />

      {deleteUserTarget && (
        <OperatorDeleteUserDialog
          open={deleteUserTarget !== null}
          onOpenChange={(open) => !open && setDeleteUserTarget(null)}
          onSuccess={() => {
            void invalidate(q.operatorUsers());
          }}
          targetUser={deleteUserTarget}
        />
      )}
    </div>
  );
};
