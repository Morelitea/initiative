import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Mail, UserCheck } from "lucide-react";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useAuth } from "@/hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import type { User } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { SortIcon } from "@/components/SortIcon";

const PLATFORM_USERS_QUERY_KEY = ["admin", "users"];

export const SettingsPlatformUsersPage = () => {
  const { user } = useAuth();
  const { data: roleLabels } = useRoleLabels();
  const adminLabel = getRoleLabel("admin", roleLabels);
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState<{
    userId: number;
    email: string;
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
        return (
          <div className="flex flex-wrap gap-2">
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
                {isResetting ? "Sending..." : "Send password reset"}
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
    </div>
  );
};
