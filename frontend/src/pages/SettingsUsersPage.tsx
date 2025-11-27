import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
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
import type { GuildInviteRead, User, UserRole } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import { useGuilds } from "@/hooks/useGuilds";
import { formatDistanceToNow } from "date-fns";
import { Copy, RefreshCcw, Trash2 } from "lucide-react";

const USERS_QUERY_KEY = ["users"];
const ROLE_OPTIONS: UserRole[] = ["admin", "member"];
const SUPER_USER_ID = 1;
const inviteLinkForCode = (code: string) => {
  const base = import.meta.env.VITE_APP_URL?.trim() || window.location.origin;
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${normalizedBase}/invite/${encodeURIComponent(code)}`;
};

export const SettingsUsersPage = () => {
  const { user } = useAuth();
  const [emailFilter, setEmailFilter] = useState("");

  const isAdmin = user?.role === "admin";
  const { activeGuild } = useGuilds();
  const isGuildAdmin = isAdmin || activeGuild?.role === "admin";

  const { data: roleLabels } = useRoleLabels();
  const adminLabel = getRoleLabel("admin", roleLabels);
  const activeGuildId = activeGuild?.id ?? null;

  const [invites, setInvites] = useState<GuildInviteRead[]>([]);
  const [invitesLoading, setInvitesLoading] = useState(false);
  const [invitesError, setInvitesError] = useState<string | null>(null);
  const [inviteSubmitting, setInviteSubmitting] = useState(false);
  const [inviteMaxUses, setInviteMaxUses] = useState<number>(1);
  const [inviteExpiresDays, setInviteExpiresDays] = useState<number>(7);

  const loadInvites = useCallback(async () => {
    if (!activeGuildId) {
      setInvites([]);
      return;
    }
    setInvitesLoading(true);
    setInvitesError(null);
    try {
      const response = await apiClient.get<GuildInviteRead[]>(`/guilds/${activeGuildId}/invites`);
      setInvites(response.data);
    } catch (error) {
      console.error("Failed to load invites", error);
      setInvitesError("Unable to load invites.");
    } finally {
      setInvitesLoading(false);
    }
  }, [activeGuildId]);

  useEffect(() => {
    if (isGuildAdmin) {
      void loadInvites();
    }
  }, [isGuildAdmin, loadInvites]);

  const inviteRows = useMemo(() => invites, [invites]);

  const usersQuery = useQuery<User[]>({
    queryKey: USERS_QUERY_KEY,
    enabled: isGuildAdmin,
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
  });

  const approveUser = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.post(`/users/${userId}/approve`, {});
    },
    onSuccess: () => {
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
    if (!window.confirm(`Remove user ${email} from guild? This cannot be undone.`)) {
      return;
    }
    deleteUser.mutate(userId);
  };

  if (!isGuildAdmin) {
    return (
      <p className="text-sm text-muted-foreground">
        You need {adminLabel} permissions to view this page.
      </p>
    );
  }

  if (usersQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading settings…</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-sm text-destructive">Unable to load settings.</p>;
  }

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
    },
    {
      accessorKey: "email",
      header: "Email",
      cell: ({ row }) => {
        const workspaceUser = row.original;
        return <p className="text-sm text-muted-foreground">{workspaceUser.email}</p>;
      },
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
            {!workspaceUser.is_active ? (
              <Button
                type="button"
                variant="secondary"
                onClick={() => approveUser.mutate(workspaceUser.id)}
                disabled={approveUser.isPending}
              >
                Approve
              </Button>
            ) : null}
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
              Remove from guild
            </Button>
          </div>
        );
      },
    },
  ];

  const createInvite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeGuildId) {
      return;
    }
    setInviteSubmitting(true);
    setInvitesError(null);
    try {
      const expiresAt =
        inviteExpiresDays > 0
          ? new Date(Date.now() + inviteExpiresDays * 24 * 60 * 60 * 1000).toISOString()
          : null;
      const payload: Record<string, unknown> = {
        max_uses: inviteMaxUses > 0 ? inviteMaxUses : null,
        expires_at: expiresAt,
      };
      await apiClient.post(`/guilds/${activeGuildId}/invites`, payload);
      await loadInvites();
    } catch (error) {
      console.error(error);
      setInvitesError("Unable to create invite.");
    } finally {
      setInviteSubmitting(false);
    }
  };

  const deleteInvite = async (inviteId: number) => {
    if (!activeGuildId) {
      return;
    }
    try {
      await apiClient.delete(`/guilds/${activeGuildId}/invites/${inviteId}`);
      await loadInvites();
    } catch (error) {
      console.error(error);
      setInvitesError("Unable to delete invite.");
    }
  };

  const copyInviteLink = async (code: string) => {
    try {
      await navigator.clipboard.writeText(inviteLinkForCode(code));
      toast.success("Invite link copied to clipboard.");
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Guild invites</CardTitle>
            <p className="text-sm text-muted-foreground">Generate links to invite new members.</p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => loadInvites()}>
            <RefreshCcw className="h-4 w-4" />
            <span className="sr-only">Refresh invites</span>
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="grid gap-4 md:grid-cols-3" onSubmit={createInvite}>
            <div className="space-y-2">
              <Label htmlFor="invite-uses">Max uses</Label>
              <Input
                id="invite-uses"
                type="number"
                min={1}
                value={inviteMaxUses}
                onChange={(event) => setInviteMaxUses(Number(event.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-days">Expires in (days)</Label>
              <Input
                id="invite-days"
                type="number"
                min={0}
                value={inviteExpiresDays}
                onChange={(event) => setInviteExpiresDays(Number(event.target.value))}
              />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={inviteSubmitting}>
                {inviteSubmitting ? "Creating…" : "Generate invite"}
              </Button>
            </div>
          </form>
          <div className="h-px bg-border" />
          {invitesLoading ? (
            <p className="text-sm text-muted-foreground">Loading invites…</p>
          ) : null}
          {invitesError ? <p className="text-sm text-destructive">{invitesError}</p> : null}
          {!invitesLoading && !inviteRows.length ? (
            <p className="text-sm text-muted-foreground">No active invites.</p>
          ) : null}
          <div className="space-y-3">
            {inviteRows.map((invite) => {
              const link = inviteLinkForCode(invite.code);
              const expires =
                invite.expires_at != null
                  ? formatDistanceToNow(new Date(invite.expires_at), { addSuffix: true })
                  : "Never";
              return (
                <div
                  key={invite.id}
                  className="flex flex-col gap-3 rounded border bg-muted/30 p-4 text-sm md:flex-row md:items-center md:justify-between"
                >
                  <div>
                    <p className="font-medium">{link}</p>
                    <p className="text-muted-foreground">
                      Uses: {invite.uses}/{invite.max_uses ?? "∞"} · Expires: {expires}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => copyInviteLink(invite.code)}
                    >
                      <Copy className="h-4 w-4" />
                      <span className="sr-only">Copy invite link</span>
                    </Button>
                    <Button variant="outline" size="icon" onClick={() => deleteInvite(invite.id)}>
                      <Trash2 className="h-4 w-4" />
                      <span className="sr-only">Delete invite</span>
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Guild users</CardTitle>
          <CardDescription>Update roles or remove accounts.</CardDescription>
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
