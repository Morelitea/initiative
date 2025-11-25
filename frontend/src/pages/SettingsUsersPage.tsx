import { FormEvent, useEffect, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import { queryClient } from "@/lib/queryClient";
import type { RegistrationSettings, User, UserRole } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";

const REGISTRATION_SETTINGS_QUERY_KEY = ["registration-settings"];
const USERS_QUERY_KEY = ["users"];
const ROLE_OPTIONS: UserRole[] = ["admin", "project_manager", "member"];
const SUPER_USER_ID = 1;

export const SettingsUsersPage = () => {
  const { user } = useAuth();
  const [domainsInput, setDomainsInput] = useState("");
  const [emailFilter, setEmailFilter] = useState("");

  const isAdmin = user?.role === "admin";

  const settingsQuery = useQuery<RegistrationSettings>({
    queryKey: REGISTRATION_SETTINGS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<RegistrationSettings>("/settings/registration");
      return response.data;
    },
  });

  useEffect(() => {
    if (settingsQuery.data) {
      setDomainsInput(settingsQuery.data.auto_approved_domains.join(", "));
    }
  }, [settingsQuery.data]);

  const { data: roleLabels } = useRoleLabels();

  const usersQuery = useQuery<User[]>({
    queryKey: USERS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
  });

  const updateAllowList = useMutation({
    mutationFn: async (domains: string[]) => {
      const response = await apiClient.put<RegistrationSettings>("/settings/registration", {
        auto_approved_domains: domains,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setDomainsInput(data.auto_approved_domains.join(", "));
      queryClient.setQueryData(REGISTRATION_SETTINGS_QUERY_KEY, data);
    },
  });

  const approveUser = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.post(`/users/${userId}/approve`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: REGISTRATION_SETTINGS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });
    },
  });

  const updateUser = useMutation({
    mutationFn: async ({
      userId,
      data,
    }: {
      userId: number;
      data: Partial<User> & { password?: string };
    }) => {
      const response = await apiClient.patch<User>(`/users/${userId}`, data);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });
    },
  });

  const deleteUser = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/users/${userId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });
    },
  });

  const handleRoleChange = (userId: number, role: UserRole) => {
    if (userId === SUPER_USER_ID) {
      toast.error("You can't change the super user's role");
      return;
    }
    updateUser.mutate({ userId, data: { role } });
  };

  const handleResetPassword = (userId: number, email: string) => {
    const nextPassword = window.prompt(`Enter a new password for ${email}`);
    if (!nextPassword) {
      return;
    }
    updateUser.mutate({ userId, data: { password: nextPassword } });
  };

  const handleDeleteUser = (userId: number, email: string) => {
    if (userId === SUPER_USER_ID) {
      toast.error("You can't delete the super user");
      return;
    }
    if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) {
      return;
    }
    deleteUser.mutate(userId);
  };

  if (!isAdmin) {
    return (
      <p className="text-sm text-muted-foreground">You need admin permissions to view this page.</p>
    );
  }

  if (settingsQuery.isLoading || usersQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading settings…</p>;
  }

  if (settingsQuery.isError || !settingsQuery.data || usersQuery.isError || !usersQuery.data) {
    return <p className="text-sm text-destructive">Unable to load settings.</p>;
  }

  const handleDomainsSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const domains = domainsInput
      .split(",")
      .map((domain) => domain.trim().toLowerCase())
      .filter(Boolean);
    updateAllowList.mutate(domains);
  };

  const normalizedEmailFilter = emailFilter.trim().toLowerCase();
  const filteredUsers = usersQuery.data.filter((workspaceUser) => {
    if (!normalizedEmailFilter) {
      return true;
    }
    return workspaceUser.email.toLowerCase().includes(normalizedEmailFilter);
  });

  const userColumns: ColumnDef<User>[] = [
    {
      id: "user",
      header: "User",
      cell: ({ row }) => {
        const workspaceUser = row.original;
        const displayName = workspaceUser.full_name?.trim() || "—";
        return (
          <div>
            <p className="font-medium">{displayName}</p>
            <p className="text-xs text-muted-foreground">
              Status: {workspaceUser.is_active ? "Active" : "Pending approval"}
            </p>
          </div>
        );
      },
      enableSorting: true,
    },
    {
      accessorKey: "email",
      header: "Email",
      cell: ({ row }) => {
        const workspaceUser = row.original;
        return <p className="text-sm text-muted-foreground">{workspaceUser.email}</p>;
      },
      enableSorting: true,
    },
    {
      accessorKey: "role",
      header: "Role",
      cell: ({ row }) => {
        const workspaceUser = row.original;
        const isSuperUser = workspaceUser.id === SUPER_USER_ID;
        return (
          <div className="flex flex-col gap-1">
            <Select
              value={workspaceUser.role}
              onValueChange={(value) => handleRoleChange(workspaceUser.id, value as UserRole)}
              disabled={isSuperUser}
            >
              <SelectTrigger disabled={isSuperUser} className="min-w-[160px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLE_OPTIONS.map((roleOption) => (
                  <SelectItem key={roleOption} value={roleOption}>
                    {getRoleLabel(roleOption, roleLabels)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      },
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => {
        const workspaceUser = row.original;
        const isSuperUser = workspaceUser.id === SUPER_USER_ID;
        const isSelf = workspaceUser.id === user?.id;
        return (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleResetPassword(workspaceUser.id, workspaceUser.email)}
              disabled={updateUser.isPending}
            >
              Reset password
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => handleDeleteUser(workspaceUser.id, workspaceUser.email)}
              disabled={isSuperUser || deleteUser.isPending || isSelf}
            >
              Delete user
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Auto-approved email domains</CardTitle>
          <CardDescription>
            Enter a comma-separated list of domains that should be auto-approved.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleDomainsSubmit}>
            <Input
              type="text"
              value={domainsInput}
              onChange={(event) => setDomainsInput(event.target.value)}
              placeholder="example.com, company.org"
            />
            <Button type="submit" disabled={updateAllowList.isPending}>
              {updateAllowList.isPending ? "Saving…" : "Save allow list"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Pending users</CardTitle>
          <CardDescription>
            Approve people who registered with non-allow-listed emails.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {settingsQuery.data.pending_users.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending accounts.</p>
          ) : (
            <div className="space-y-3">
              {settingsQuery.data.pending_users.map((pendingUser) => (
                <div
                  key={pendingUser.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-3"
                >
                  <div>
                    <p className="font-medium">{pendingUser.full_name ?? pendingUser.email}</p>
                    <p className="text-sm text-muted-foreground">{pendingUser.email}</p>
                  </div>
                  <Button
                    type="button"
                    onClick={() => approveUser.mutate(pendingUser.id)}
                    disabled={approveUser.isPending}
                  >
                    Approve
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Workspace users</CardTitle>
          <CardDescription>Update roles, reset passwords, or remove accounts.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="email-filter" className="text-xs text-muted-foreground">
              Filter by email
            </Label>
            <Input
              id="email-filter"
              value={emailFilter}
              onChange={(event) => setEmailFilter(event.target.value)}
              placeholder="user@example.com"
              autoComplete="off"
            />
          </div>
          <DataTable columns={userColumns} data={filteredUsers} />
        </CardContent>
      </Card>
    </div>
  );
};
