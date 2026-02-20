import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  approveUserApiV1UsersUserIdApprovePost,
  deleteUserApiV1UsersUserIdDelete,
} from "@/api/generated/users/users";
import { useUsers } from "@/hooks/useUsers";
import {
  listGuildInvitesApiV1GuildsGuildIdInvitesGet,
  createGuildInviteApiV1GuildsGuildIdInvitesPost,
  deleteGuildInviteApiV1GuildsGuildIdInvitesInviteIdDelete,
  updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch,
} from "@/api/generated/guilds/guilds";
import { invalidateUsersList } from "@/api/query-keys";
import { getErrorMessage } from "@/lib/errorMessage";
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
import { useDateLocale } from "@/hooks/useDateLocale";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import type { GuildInviteRead, GuildRole, UserGuildMember } from "@/types/api";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import { useGuilds } from "@/hooks/useGuilds";
import { formatDistanceToNow } from "date-fns";
import { Copy, RefreshCcw, Trash2 } from "lucide-react";

const GUILD_ROLE_OPTIONS: GuildRole[] = ["admin", "member"];
const inviteLinkForCode = (code: string) => {
  const base = import.meta.env.VITE_APP_URL?.trim() || window.location.origin;
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${normalizedBase}/invite/${encodeURIComponent(code)}`;
};

export const SettingsUsersPage = () => {
  const { user } = useAuth();
  const { t } = useTranslation("guilds");
  const dateLocale = useDateLocale();

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
      const data = await (listGuildInvitesApiV1GuildsGuildIdInvitesGet(
        activeGuildId
      ) as unknown as Promise<GuildInviteRead[]>);
      setInvites(data);
    } catch (error) {
      console.error("Failed to load invites", error);
      setInvitesError(t("users.unableToLoadInvites"));
    } finally {
      setInvitesLoading(false);
    }
  }, [activeGuildId, t]);

  useEffect(() => {
    if (isGuildAdmin) {
      void loadInvites();
    }
  }, [isGuildAdmin, loadInvites]);

  const inviteRows = useMemo(() => invites, [invites]);

  const usersQuery = useUsers({ enabled: isGuildAdmin });

  const approveUser = useMutation({
    mutationFn: async (userId: number) => {
      await approveUserApiV1UsersUserIdApprovePost(userId);
    },
    onSuccess: () => {
      void invalidateUsersList();
    },
  });

  const updateGuildMembership = useMutation({
    mutationFn: async ({ userId, role }: { userId: number; role: GuildRole }) => {
      await updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch(activeGuildId!, userId, {
        role,
      } as Parameters<typeof updateGuildMembershipApiV1GuildsGuildIdMembersUserIdPatch>[2]);
    },
    onSuccess: () => {
      void invalidateUsersList();
    },
    onError: (error: unknown) => {
      const message = getErrorMessage(error, "guilds:users.failedToUpdateRole");
      toast.error(message);
    },
  });

  const deleteUser = useMutation({
    mutationFn: async (userId: number) => {
      await deleteUserApiV1UsersUserIdDelete(userId);
    },
    onSuccess: () => {
      void invalidateUsersList();
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
      <p className="text-muted-foreground text-sm">{t("users.adminRequired", { adminLabel })}</p>
    );
  }

  if (usersQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("users.loadingSettings")}</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("users.unableToLoadSettings")}</p>;
  }

  const userColumns: ColumnDef<UserGuildMember>[] = [
    {
      id: "user",
      header: t("users.userColumn"),
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
      header: t("users.emailColumn"),
      cell: ({ row }) => {
        const guildMember = row.original;
        return <p className="text-muted-foreground text-sm">{guildMember.email}</p>;
      },
    },
    {
      accessorKey: "guild_role",
      header: t("users.guildRoleColumn"),
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
      accessorKey: "oidc_managed",
      header: t("users.sourceColumn"),
      cell: ({ row }) => {
        return row.original.oidc_managed ? (
          <span className="bg-muted text-muted-foreground inline-flex items-center rounded-md px-2 py-1 text-sm font-medium">
            {t("users.sourceOidc")}
          </span>
        ) : (
          <span className="text-muted-foreground text-sm">{t("users.sourceManual")}</span>
        );
      },
    },
    {
      id: "actions",
      header: t("users.actionsColumn"),
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
                {t("users.reactivate")}
              </Button>
            ) : null}
            <Button
              type="button"
              variant="destructive"
              onClick={() => handleDeleteUser(guildMember.id, guildMember.email)}
              disabled={deleteUser.isPending || isSelf}
            >
              {t("users.removeFromGuild")}
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
      const payload = {
        max_uses: inviteMaxUses > 0 ? inviteMaxUses : null,
        expires_at: expiresAt,
      };
      await createGuildInviteApiV1GuildsGuildIdInvitesPost(
        activeGuildId,
        payload as Parameters<typeof createGuildInviteApiV1GuildsGuildIdInvitesPost>[1]
      );
      await loadInvites();
    } catch (error) {
      console.error(error);
      setInvitesError(t("users.unableToCreateInvite"));
    } finally {
      setInviteSubmitting(false);
    }
  };

  const deleteInvite = async (inviteId: number) => {
    if (!activeGuildId) {
      return;
    }
    try {
      await deleteGuildInviteApiV1GuildsGuildIdInvitesInviteIdDelete(activeGuildId, inviteId);
      await loadInvites();
    } catch (error) {
      console.error(error);
      setInvitesError(t("users.unableToDeleteInvite"));
    }
  };

  const copyInviteLink = async (code: string) => {
    try {
      await navigator.clipboard.writeText(inviteLinkForCode(code));
      toast.success(t("users.inviteLinkCopied"));
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>{t("users.invitesTitle")}</CardTitle>
            <p className="text-muted-foreground text-sm">{t("users.invitesDescription")}</p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => loadInvites()}>
            <RefreshCcw className="h-4 w-4" />
            <span className="sr-only">{t("users.refreshInvites")}</span>
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="grid gap-4 md:grid-cols-3" onSubmit={createInvite}>
            <div className="space-y-2">
              <Label htmlFor="invite-uses">{t("users.maxUsesLabel")}</Label>
              <Input
                id="invite-uses"
                type="number"
                min={1}
                value={inviteMaxUses}
                onChange={(event) => setInviteMaxUses(Number(event.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-days">{t("users.expiresDaysLabel")}</Label>
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
                {inviteSubmitting ? t("users.generatingInvite") : t("users.generateInvite")}
              </Button>
            </div>
          </form>
          <div className="bg-border h-px" />
          {invitesLoading ? (
            <p className="text-muted-foreground text-sm">{t("users.loadingInvites")}</p>
          ) : null}
          {invitesError ? <p className="text-destructive text-sm">{invitesError}</p> : null}
          {!invitesLoading && !inviteRows.length ? (
            <p className="text-muted-foreground text-sm">{t("users.noActiveInvites")}</p>
          ) : null}
          <div className="space-y-3">
            {inviteRows.map((invite) => {
              const link = inviteLinkForCode(invite.code);
              const expires =
                invite.expires_at != null
                  ? formatDistanceToNow(new Date(invite.expires_at), {
                      addSuffix: true,
                      locale: dateLocale,
                    })
                  : t("users.neverExpires");
              return (
                <div
                  key={invite.id}
                  className="bg-muted/30 flex flex-col gap-3 rounded border p-4 text-sm md:flex-row md:items-center md:justify-between"
                >
                  <div>
                    <p className="font-medium">{link}</p>
                    <p className="text-muted-foreground">
                      {t("users.usesFormat", {
                        uses: invite.uses,
                        max: invite.max_uses ?? "\u221e",
                        expires,
                      })}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => copyInviteLink(invite.code)}
                    >
                      <Copy className="h-4 w-4" />
                      <span className="sr-only">{t("users.copyInviteLink")}</span>
                    </Button>
                    <Button variant="outline" size="icon" onClick={() => deleteInvite(invite.id)}>
                      <Trash2 className="h-4 w-4" />
                      <span className="sr-only">{t("users.deleteInviteLink")}</span>
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
          <CardTitle>{t("users.usersTitle")}</CardTitle>
          <CardDescription>{t("users.usersDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={usersQuery.data}
            enableFilterInput
            filterInputColumnKey="email"
            filterInputPlaceholder={t("users.filterByEmail")}
            enableResetSorting
            enablePagination
          />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleteUserConfirm !== null}
        onOpenChange={(open) => !open && setDeleteUserConfirm(null)}
        title={t("users.removeUserTitle")}
        description={t("users.removeUserDescription", {
          email: deleteUserConfirm?.email ?? "this user",
        })}
        confirmLabel={t("users.removeConfirmLabel")}
        onConfirm={confirmDeleteUser}
        isLoading={deleteUser.isPending}
        destructive
      />
    </div>
  );
};
