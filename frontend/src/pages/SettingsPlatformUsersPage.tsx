import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Mail, Shield, ShieldOff, UserCheck } from "lucide-react";

import { apiClient } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useAuth } from "@/hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import type { User, UserRole } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { SortIcon } from "@/components/SortIcon";
import { queryClient } from "@/lib/queryClient";

const PLATFORM_USERS_QUERY_KEY = ["admin", "users"];
const ADMIN_COUNT_QUERY_KEY = ["admin", "platform-admin-count"];

interface PlatformAdminCountResponse {
  count: number;
}

export const SettingsPlatformUsersPage = () => {
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

  const isAdmin = user?.role === "admin";

  const usersQuery = useQuery<User[]>({
    queryKey: PLATFORM_USERS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/admin/users");
      return response.data;
    },
  });

  const adminCountQuery = useQuery<PlatformAdminCountResponse>({
    queryKey: ADMIN_COUNT_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<PlatformAdminCountResponse>(
        "/admin/platform-admin-count"
      );
      return response.data;
    },
  });

  const resetPassword = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.post(`/admin/users/${userId}/reset-password`, {});
    },
    onSuccess: (_data, userId) => {
      const targetUser = usersQuery.data?.find((u) => u.id === userId);
      const userEmail = targetUser?.email || "user";
      toast.success(`Password reset email sent to ${userEmail}`);
      setResettingUserId(null);
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Failed to send password reset email";
      toast.error(message);
      setResettingUserId(null);
    },
  });

  const reactivateUser = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.post(`/admin/users/${userId}/reactivate`, {});
    },
    onSuccess: (_data, userId) => {
      const targetUser = usersQuery.data?.find((u) => u.id === userId);
      const userEmail = targetUser?.email || "user";
      toast.success(`User ${userEmail} has been reactivated`);
      void usersQuery.refetch();
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Failed to reactivate user";
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
      await apiClient.patch(`/admin/users/${userId}/platform-role`, { role });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PLATFORM_USERS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: ADMIN_COUNT_QUERY_KEY });
      toast.success("Platform role updated");
      setRoleChangeConfirm(null);
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Failed to update platform role";
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
        You need {adminLabel} permissions to view this page.
      </p>
    );
  }

  if (usersQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading users…</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">Unable to load users.</p>;
  }

  const userColumns: ColumnDef<User>[] = [
    {
      id: "name",
      header: "Name",
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
              Email
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
      header: "Platform Role",
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
      header: "Status",
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
            {platformUser.is_active ? "Active" : "Deactivated"}
          </span>
        );
      },
    },
    {
      id: "actions",
      header: "Actions",
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
                title={isLastAdmin ? "Cannot demote the last platform admin" : undefined}
              >
                <ShieldOff className="h-4 w-4" />
                Demote
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
                Promote
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
                Reactivate
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
                {isResetting ? "Sending..." : "Reset password"}
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
          <CardTitle>Platform users</CardTitle>
          <CardDescription>
            View all users across all guilds and send password reset emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={usersQuery.data}
            enableFilterInput
            filterInputColumnKey="email"
            filterInputPlaceholder="Filter by email..."
            enableResetSorting
            enablePagination
          />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={resetPasswordConfirm !== null}
        onOpenChange={(open) => !open && setResetPasswordConfirm(null)}
        title="Send password reset email?"
        description={`This will send a password reset email to ${resetPasswordConfirm?.email ?? "this user"}.`}
        confirmLabel="Send"
        onConfirm={confirmResetPassword}
        isLoading={resetPassword.isPending}
      />

      <ConfirmDialog
        open={roleChangeConfirm !== null}
        onOpenChange={(open) => !open && setRoleChangeConfirm(null)}
        title={
          roleChangeConfirm?.newRole === "admin"
            ? "Promote to platform admin?"
            : "Demote from platform admin?"
        }
        description={
          roleChangeConfirm?.newRole === "admin"
            ? `This will give ${roleChangeConfirm?.email ?? "this user"} platform admin permissions, allowing them to manage platform settings, users, and configurations.`
            : `This will remove platform admin permissions from ${roleChangeConfirm?.email ?? "this user"}. They will no longer be able to access platform settings.`
        }
        confirmLabel={roleChangeConfirm?.newRole === "admin" ? "Promote" : "Demote"}
        onConfirm={confirmRoleChange}
        isLoading={updatePlatformRole.isPending}
      />
    </div>
  );
};
