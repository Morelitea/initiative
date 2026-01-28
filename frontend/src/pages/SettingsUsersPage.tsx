import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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
import type { GuildInviteRead, GuildRole, UserGuildMember } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import { useGuilds } from "@/hooks/useGuilds";
import { formatDistanceToNow } from "date-fns";
import { Copy, RefreshCcw, Trash2 } from "lucide-react";

const USERS_QUERY_KEY = ["users"];
const GUILD_ROLE_OPTIONS: GuildRole[] = ["admin", "member"];
const inviteLinkForCode = (code: string) => {
  const base = import.meta.env.VITE_APP_URL?.trim() || window.location.origin;
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${normalizedBase}/invite/${encodeURIComponent(code)}`;
};

export const SettingsUsersPage = () => {
  const { user } = useAuth();

  const { activeGuild } = useGuilds();
  // Guild admin check is based on guild membership role only (independent from platform role)
  const isGuildAdmin = activeGuild?.role === "admin";

  const { data: roleLabels } = useRoleLabels();
  const adminLabel = getRoleLabel("admin", roleLabels);
  const activeGuildId = activeGuild?.id ?? null;

  const [invites, setInvites] = useState<GuildInviteRead[]>([]);
  const [invitesLoading, setInvitesLoading] = useState(false);
  const [invitesError, setInvitesError] = useState<string | null>(null);
  const [inviteSubmitting, setInviteSubmitting] = useState(false);
  const [inviteMaxUses, setInviteMaxUses] = useState<number>(1);
  const [inviteExpiresDays, setInviteExpiresDays] = useState<number>(7);
  const [deleteUserConfirm, setDeleteUserConfirm] = useState<{
    userId: number;
    email: string;
  } | null>(null);

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

  const usersQuery = useQuery<UserGuildMember[]>({
    queryKey: USERS_QUERY_KEY,
    enabled: isGuildAdmin,
    queryFn: async () => {
      const response = await apiClient.get<UserGuildMember[]>("/users/");
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

  const updateGuildMembership = useMutation({
    mutationFn: async ({ userId, role }: { userId: number; role: GuildRole }) => {
      await apiClient.patch(`/guilds/${activeGuildId}/members/${userId}`, { role });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });
    },
    onError: (error: unknown) => {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Failed to update role";
      toast.error(message);
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

  const handleRoleChange = (userId: number, role: GuildRole) => {
    // Update guild membership role
    updateGuildMembership.mutate({ userId, role });
  };

  const handleDeleteUser = (userId: number, email: string) => {
    // Backend handles validation (e.g., cannot delete last platform admin)
    setDeleteUserConfirm({ userId, email });
  };

  const confirmDeleteUser = () => {
    if (deleteUserConfirm) {
      deleteUser.mutate(deleteUserConfirm.userId);
      setDeleteUserConfirm(null);
    }
  };

  if (!isGuildAdmin) {
    return (
      <p className="text-muted-foreground text-sm">
        You need {adminLabel} permissions to view this page.
      </p>
    );
  }

  if (usersQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading settings…</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">Unable to load settings.</p>;
  }

  const userColumns: ColumnDef<UserGuildMember>[] = [
    {
      id: "user",
      header: "User",
      cell: ({ row }) => {
        const guildMember = row.original;
        const displayName = guildMember.full_name?.trim() || "—";
        return (
          <div>
            <p className="font-medium">{displayName}</p>
          </div>
        );
      },
    },
    {
      accessorKey: "email",
      header: "Email",
      cell: ({ row }) => {
        const guildMember = row.original;
        return <p className="text-muted-foreground text-sm">{guildMember.email}</p>;
      },
    },
    {
      accessorKey: "guild_role",
      header: "Guild Role",
      cell: ({ row }) => {
        const guildMember = row.original;
        const isSelf = guildMember.id === user?.id;
        const currentGuildRole = guildMember.guild_role ?? "member";
        return (
          <div className="flex flex-col gap-1">
            <Select
              value={currentGuildRole}
              onValueChange={(value) => handleRoleChange(guildMember.id, value as GuildRole)}
              disabled={isSelf || updateGuildMembership.isPending}
            >
              <SelectTrigger disabled={isSelf} className="min-w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GUILD_ROLE_OPTIONS.map((roleOption) => (
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
        const guildMember = row.original;
        const isSelf = guildMember.id === user?.id;
        return (
          <div className="flex flex-wrap gap-2">
            {!guildMember.is_active ? (
              <Button
                type="button"
                variant="secondary"
                onClick={() => approveUser.mutate(guildMember.id)}
                disabled={approveUser.isPending}
              >
                Reactivate
              </Button>
            ) : null}
            <Button
              type="button"
              variant="destructive"
              onClick={() => handleDeleteUser(guildMember.id, guildMember.email)}
              disabled={deleteUser.isPending || isSelf}
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
            <p className="text-muted-foreground text-sm">Generate links to invite new members.</p>
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
          <div className="bg-border h-px" />
          {invitesLoading ? (
            <p className="text-muted-foreground text-sm">Loading invites…</p>
          ) : null}
          {invitesError ? <p className="text-destructive text-sm">{invitesError}</p> : null}
          {!invitesLoading && !inviteRows.length ? (
            <p className="text-muted-foreground text-sm">No active invites.</p>
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
                  className="bg-muted/30 flex flex-col gap-3 rounded border p-4 text-sm md:flex-row md:items-center md:justify-between"
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
          <DataTable
            columns={userColumns}
            data={usersQuery.data}
            enableFilterInput
            filterInputColumnKey="email"
            filterInputPlaceholder="Filter by email..."
            enableResetSorting
          />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleteUserConfirm !== null}
        onOpenChange={(open) => !open && setDeleteUserConfirm(null)}
        title="Remove user from guild?"
        description={`This will remove ${deleteUserConfirm?.email ?? "this user"} from the guild. This cannot be undone.`}
        confirmLabel="Remove"
        onConfirm={confirmDeleteUser}
        isLoading={deleteUser.isPending}
        destructive
      />
    </div>
  );
};
