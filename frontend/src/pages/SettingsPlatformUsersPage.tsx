import { useState, useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Mail, UserCheck, Shield, ShieldOff } from "lucide-react";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import type { User } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { SortIcon } from "@/components/SortIcon";
import { Badge } from "@/components/ui/badge";

const PLATFORM_USERS_QUERY_KEY = ["admin", "users"];

export const SettingsPlatformUsersPage = () => {
  const { user } = useAuth();
  const { data: roleLabels } = useRoleLabels();
  const adminLabel = getRoleLabel("admin", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);

  const isAdmin = user?.role === "admin";

  const usersQuery = useQuery<User[]>({
    queryKey: PLATFORM_USERS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/admin/users");
      return response.data;
    },
  });

  // Count active admins to determine if user is last admin
  const activeAdminCount = useMemo(() => {
    if (!usersQuery.data) return 0;
    return usersQuery.data.filter((u) => u.role === "admin" && u.is_active).length;
  }, [usersQuery.data]);

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

  const updateUserRole = useMutation({
    mutationFn: async ({ userId, role }: { userId: number; role: "admin" | "member" }) => {
      await apiClient.patch(`/admin/users/${userId}/role`, { role });
    },
    onSuccess: (_data, { userId, role }) => {
      const targetUser = usersQuery.data?.find((u) => u.id === userId);
      const userEmail = targetUser?.email || "user";
      const roleLabel = role === "admin" ? adminLabel : memberLabel;
      toast.success(`${userEmail} is now a ${roleLabel}`);
      void usersQuery.refetch();
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Failed to update user role";
      toast.error(message);
    },
  });

  const handleResetPassword = (userId: number, email: string) => {
    if (!window.confirm(`Send password reset email to ${email}?`)) {
      return;
    }
    setResettingUserId(userId);
    resetPassword.mutate(userId);
  };

  const handleRoleChange = (platformUser: User) => {
    const newRole = platformUser.role === "admin" ? "member" : "admin";
    const roleLabel = newRole === "admin" ? adminLabel : memberLabel;
    if (!window.confirm(`Change ${platformUser.email} to ${roleLabel}?`)) {
      return;
    }
    updateUserRole.mutate({ userId: platformUser.id, role: newRole });
  };

  if (!isAdmin) {
    return (
      <p className="text-muted-foreground text-sm">
        You need {adminLabel} permissions to view this page.
      </p>
    );
  }

  if (usersQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading users...</p>;
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
        const displayName = platformUser.full_name?.trim() || "-";
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
      id: "role",
      header: "Role",
      cell: ({ row }) => {
        const platformUser = row.original;
        const isUserAdmin = platformUser.role === "admin";
        const label = isUserAdmin ? adminLabel : memberLabel;
        return <Badge variant={isUserAdmin ? "default" : "secondary"}>{label}</Badge>;
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
        const isSelf = platformUser.id === user?.id;
        const isUserAdmin = platformUser.role === "admin";
        const isLastAdmin = isUserAdmin && activeAdminCount === 1;
        const canChangeRole = !isSelf && platformUser.is_active && !isLastAdmin;

        return (
          <div className="flex flex-wrap gap-2">
            {/* Role change button */}
            {platformUser.is_active && (
              <Tooltip delayDuration={300}>
                <TooltipTrigger asChild>
                  <span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => handleRoleChange(platformUser)}
                      disabled={!canChangeRole || updateUserRole.isPending}
                    >
                      {isUserAdmin ? (
                        <>
                          <ShieldOff className="h-4 w-4" />
                          Demote
                        </>
                      ) : (
                        <>
                          <Shield className="h-4 w-4" />
                          Promote
                        </>
                      )}
                    </Button>
                  </span>
                </TooltipTrigger>
                {!canChangeRole && (
                  <TooltipContent>
                    {isSelf
                      ? "Cannot change your own role"
                      : isLastAdmin
                        ? "Cannot demote the last admin"
                        : "Cannot change role"}
                  </TooltipContent>
                )}
              </Tooltip>
            )}

            {/* Reactivate or password reset */}
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
            View all users across all guilds, manage roles, and send password reset emails.
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
    </div>
  );
};
