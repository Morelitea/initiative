import { Link } from "@tanstack/react-router";
import { Copy, Download, HandCoins, RefreshCcw, Trash2 } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createGuildInviteApiV1GuildsGuildIdInvitesPost,
  deleteGuildInviteApiV1GuildsGuildIdInvitesInviteIdDelete,
  listGuildInvitesApiV1GuildsGuildIdInvitesGet,
} from "@/api/generated/guilds/guilds";
import type {
  GuildInviteRead,
  GuildRole,
  UserGuildMember,
} from "@/api/generated/initiativeAPI.schemas";
import { RemoveGuildMemberDialog } from "@/components/guilds/RemoveGuildMemberDialog";
import { TransferContentOwnershipDialog } from "@/components/guilds/TransferContentOwnershipDialog";
import { UnownedContentCard } from "@/components/guilds/UnownedContentCard";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useGuilds } from "@/hooks/useGuilds";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import {
  useApproveUser,
  useExportGuildUsersCsv,
  useUpdateGuildMembership,
  useUsers,
} from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";

const GUILD_ROLE_OPTIONS: GuildRole[] = ["admin", "member"];
const inviteLinkForCode = (code: string) => {
  const base = import.meta.env.VITE_APP_URL?.trim() || window.location.origin;
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${normalizedBase}/invite/${encodeURIComponent(code)}`;
};

/**
 * Live "N uses · expires M" line for one invite. A component (not an inline
 * hook) so `useRelativeTime` can run per invite inside the invites map.
 */
const InviteUsesLine = ({
  uses,
  maxUses,
  expiresAt,
}: {
  uses: number;
  maxUses: number | null;
  expiresAt: string | null;
}) => {
  const { t } = useTranslation("guilds");
  const relativeExpiry = useRelativeTime(expiresAt);
  const expires = expiresAt != null ? relativeExpiry : t("users.neverExpires");
  return (
    <p className="text-muted-foreground">
      {t("users.usesFormat", { uses, max: maxUses ?? "∞", expires })}
    </p>
  );
};

export const SettingsUsersPage = () => {
  const { user } = useAuth();
  const { t } = useTranslation("guilds");

  const { activeGuild } = useGuilds();
  const { billing, openPortal } = useBillingPortal();
  // Guild admin check is based on guild membership role only (independent from platform role)
  const isGuildAdmin = activeGuild?.role === "admin";

  const activeGuildId = activeGuild?.id ?? null;

  // Seat cap, admin-only on the payload and null when uncapped. A full guild
  // mints no invite (the server refuses), so the form says so up front instead
  // of failing on submit. Where a billing portal exists the cap travels with
  // the plan — raising it is an upgrade, not a request to an operator — so the
  // message and its action differ from the self-hosted one.
  const maxUsers = activeGuild?.max_users ?? null;
  const usedSeats = activeGuild?.member_count ?? 0;
  const atUserLimit = maxUsers !== null && usedSeats >= maxUsers;
  const planName = activeGuild?.tier_name ?? null;

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
  // `member: null` opens the dialog in "claim everything unowned" mode.
  const [transferTarget, setTransferTarget] = useState<{ member: UserGuildMember | null } | null>(
    null
  );

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

  const approveUser = useApproveUser();

  // Ownership can only be handed to a guild admin, so the picker is the guild's
  // admin roster rather than every member.
  const guildAdmins = useMemo(
    () =>
      (usersQuery.data ?? []).filter((m) => m.guild_role === "admin" && m.status !== "anonymized"),
    [usersQuery.data]
  );

  const updateGuildMembership = useUpdateGuildMembership({
    onError: (error: unknown) => {
      const message = getErrorMessage(error, "guilds:users.failedToUpdateRole");
      toast.error(message);
    },
  });

  const handleRoleChange = (userId: number, role: GuildRole) => {
    // Update guild membership role
    updateGuildMembership.mutate({ guildId: activeGuildId!, userId, role });
  };

  const handleDeleteUser = (userId: number, email: string) => {
    // Backend handles validation (e.g., cannot delete last platform admin)
    setDeleteUserConfirm({ userId, email });
  };

  const exportGuildUsers = useExportGuildUsersCsv({
    onError: (err) => {
      toast.error(getErrorMessage(err, "guilds:users.exportError"));
    },
  });

  const exportUserCsv = (guildMember: UserGuildMember) => {
    const safeHandle = guildMember.username.replace(/[^a-zA-Z0-9._-]+/g, "_");
    exportGuildUsers.mutate({
      params: { user_id: [guildMember.id] },
      filename: `user-${guildMember.id}-${safeHandle}.csv`,
    });
  };

  const exportAllUsersCsv = () => {
    const safeGuildName = (activeGuild?.name ?? "guild").replace(/[^a-zA-Z0-9._-]+/g, "_");
    const datestamp = new Date().toISOString().slice(0, 10);
    exportGuildUsers.mutate({
      params: {},
      filename: `${safeGuildName}-users-${datestamp}.csv`,
    });
  };

  if (!isGuildAdmin) {
    return <p className="text-muted-foreground text-sm">{t("users.adminRequired")}</p>;
  }

  if (usersQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("users.loadingSettings")}</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("users.unableToLoadSettings")}</p>;
  }

  // The handle leads: every guild has one for every member. A guild that
  // renders handles sends no names, so that column would be a full one of
  // em-dashes.
  const showsNames = Boolean(activeGuild?.show_member_names);

  const userColumns: AppColumnDef<UserGuildMember>[] = [
    {
      accessorKey: "id",
      header: t("users.userIdColumn"),
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.id}</p>
      ),
    },
    {
      accessorKey: "username",
      header: t("users.handleColumn"),
      // The handle is what identifies someone, so it is also what opens them.
      cell: ({ row }) => (
        <Link
          to="/u/$userId"
          params={{ userId: String(row.original.id) }}
          className="text-sm hover:underline"
        >
          <UserHandle user={row.original} />
        </Link>
      ),
    },
    ...(showsNames
      ? [
          {
            id: "user",
            header: t("users.userColumn"),
            cell: ({ row }) => (
              <div>
                <p className="font-medium">{row.original.full_name?.trim() || "—"}</p>
              </div>
            ),
          } satisfies AppColumnDef<UserGuildMember>,
        ]
      : []),
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
                    {t(`users.guildRole.${roleOption}` as never)}
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
          <span className="inline-flex items-center rounded-md bg-muted px-2 py-1 font-medium text-muted-foreground text-sm">
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
            {guildMember.status === "deactivated" ? (
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
              variant="outline"
              size="sm"
              onClick={() => exportUserCsv(guildMember)}
            >
              <Download className="h-4 w-4" />
              {t("users.exportUser")}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setTransferTarget({ member: guildMember })}
            >
              <HandCoins className="h-4 w-4" />
              {t("transferOwnership.action")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => handleDeleteUser(guildMember.id, getUserDisplayName(guildMember))}
              disabled={isSelf}
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
    if (!activeGuildId || atUserLimit) {
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
      setInvitesError(getErrorMessage(error, "guilds:users.unableToCreateInvite"));
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
              <Button type="submit" disabled={inviteSubmitting || atUserLimit}>
                {inviteSubmitting ? t("users.generatingInvite") : t("users.generateInvite")}
              </Button>
            </div>
          </form>
          {atUserLimit && billing && activeGuildId ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-muted-foreground text-sm">
                {planName
                  ? t("users.inviteSeatsFullPlan", { plan: planName, count: maxUsers ?? 0 })
                  : t("users.inviteSeatsFullUpgrade", { count: maxUsers ?? 0 })}
              </p>
              <Button size="sm" onClick={() => void openPortal(activeGuildId, "upgrade")}>
                {t("usagePanel.upgrade")}
              </Button>
            </div>
          ) : atUserLimit ? (
            <p className="text-muted-foreground text-sm">
              {t("users.inviteSeatsFull", { max: maxUsers })}
            </p>
          ) : null}
          <div className="h-px bg-border" />
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
              return (
                <div
                  key={invite.id}
                  className="flex flex-col gap-3 rounded border bg-muted/30 p-4 text-sm md:flex-row md:items-center md:justify-between"
                >
                  <div>
                    <p className="font-medium">{link}</p>
                    <InviteUsesLine
                      uses={invite.uses}
                      maxUses={invite.max_uses ?? null}
                      expiresAt={invite.expires_at ?? null}
                    />
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
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>{t("users.usersTitle")}</CardTitle>
            <CardDescription>{t("users.usersDescription")}</CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={exportAllUsersCsv}
            disabled={!usersQuery.data?.length}
          >
            <Download className="h-4 w-4" />
            {t("users.exportAll")}
          </Button>
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

      <UnownedContentCard onClaim={() => setTransferTarget({ member: null })} />

      <RemoveGuildMemberDialog
        open={deleteUserConfirm !== null}
        onOpenChange={(open) => !open && setDeleteUserConfirm(null)}
        userId={deleteUserConfirm?.userId ?? null}
        email={deleteUserConfirm?.email ?? ""}
      />

      <TransferContentOwnershipDialog
        open={transferTarget !== null}
        onOpenChange={(open) => !open && setTransferTarget(null)}
        member={transferTarget?.member ?? null}
        admins={guildAdmins}
        defaultRecipientId={user?.id}
        onSuccess={() => void usersQuery.refetch()}
      />
    </div>
  );
};
