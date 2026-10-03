import { Link } from "@tanstack/react-router";
import type { PaginationState } from "@tanstack/react-table";
import { Copy, Download, HandCoins, IdCard, RefreshCcw, Trash2, UserMinus } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createCommunityInvite,
  deleteCommunityInvite,
  listCommunityInvites,
} from "@/api/generated/communities/communities";
import type {
  CommunityInviteRead,
  CommunityRole,
  UserCommunityMember,
} from "@/api/generated/initiativeAPI.schemas";
import { MemberDisplayNameDialog } from "@/components/communities/MemberDisplayNameDialog";
import { RemoveCommunityMemberDialog } from "@/components/communities/RemoveCommunityMemberDialog";
import { TransferContentOwnershipDialog } from "@/components/communities/TransferContentOwnershipDialog";
import { UnownedContentCard } from "@/components/communities/UnownedContentCard";
import {
  FormSkeleton,
  ListSkeleton,
  SkeletonRegion,
  TableSkeleton,
} from "@/components/skeletons/PageSkeletons";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityAuthSettings } from "@/hooks/useCommunityAuthPolicy";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import {
  useExportCommunityUsersCsv,
  useSetMemberApiAccess,
  useUpdateCommunityMembership,
  useUsers,
} from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { AppColumnDef } from "@/lib/table";
import { getUrlHandle, getUserDisplayName, getUserHandle } from "@/lib/userDisplay";

//: What this community's roles are, in the order the picker offers them. The
//: seat is only on the list for somebody who already holds it — an admin can
//: neither appoint nor demote one, and the server says so too.
const COMMUNITY_ROLE_OPTIONS: CommunityRole[] = ["admin", "member"];
const SEAT_ROLE_OPTIONS: CommunityRole[] = ["superadmin", "admin", "member"];
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
  const { t } = useTranslation("communities");
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
  const { t } = useTranslation("communities");

  const { activeCommunity } = useCommunities();
  const { canSell, openPortal } = useBillingPortal();
  // Running the community, not reaching its work: the roster and its
  // invites answer to the community's own ladder, and to a settings grant
  // standing in on it. Platform role has nothing to do with it.
  const isCommunityAdmin = Boolean(activeCommunity?.can.administer);
  // Invites are handed out by whoever may change the roster, so a rung that
  // only reads it does not list them.
  const managesInvites = Boolean(activeCommunity?.can.configure);
  const roleOptions = activeCommunity?.can.seat ? SEAT_ROLE_OPTIONS : COMMUNITY_ROLE_OPTIONS;

  const activeCommunityId = activeCommunity?.id ?? null;

  // Whose personal API keys reach the community is the seat's to say, and only
  // while the operator has granted the community ``restrictions``: without it
  // every member's keys reach it, so there is nothing to set.
  const isSeat = Boolean(activeCommunity?.can.seat);
  const authSettings = useCommunityAuthSettings(activeCommunityId ?? 0, {
    enabled: isSeat && activeCommunityId != null,
  }).data;
  const showsApiAccess = isSeat && (authSettings?.auth_options ?? []).includes("restrictions");

  // Seat cap, admin-only on the payload and null when uncapped. A full community
  // mints no invite (the server refuses), so the form says so up front instead
  // of failing on submit. Where a billing portal exists the cap travels with
  // the plan — raising it is an upgrade, not a request to an operator — so the
  // message and its action differ from the self-hosted one.
  const maxUsers = activeCommunity?.max_users ?? null;
  const usedSeats = activeCommunity?.member_count ?? 0;
  const atUserLimit = maxUsers !== null && usedSeats >= maxUsers;
  const planName = activeCommunity?.tier_name ?? null;

  const [invites, setInvites] = useState<CommunityInviteRead[]>([]);
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
  const [namingMember, setNamingMember] = useState<UserCommunityMember | null>(null);
  const [transferTarget, setTransferTarget] = useState<{
    member: UserCommunityMember | null;
  } | null>(null);

  const loadInvites = useCallback(async () => {
    if (!activeCommunityId) {
      setInvites([]);
      return;
    }
    setInvitesLoading(true);
    setInvitesError(null);
    try {
      const data = await (listCommunityInvites(activeCommunityId) as unknown as Promise<
        CommunityInviteRead[]
      >);
      setInvites(data);
    } catch (error) {
      console.error("Failed to load invites", error);
      setInvitesError(t("users.unableToLoadInvites"));
    } finally {
      setInvitesLoading(false);
    }
  }, [activeCommunityId, t]);

  useEffect(() => {
    if (managesInvites) {
      void loadInvites();
    }
  }, [managesInvites, loadInvites]);

  const inviteRows = useMemo(() => invites, [invites]);

  // Searched and paged on the server: the table only ever holds the page on
  // screen.
  const [draft, setDraft] = useState("");
  const search = useDebouncedValue(draft, 250);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const usersQuery = useUsers(
    { search: search.trim() || undefined, page, page_size: pageSize },
    { enabled: isCommunityAdmin }
  );
  const rows = usersQuery.data?.items ?? [];
  const totalCount = usersQuery.data?.total_count ?? 0;

  const updateCommunityMembership = useUpdateCommunityMembership({
    onError: (error: unknown) => {
      const message = getErrorMessage(error, "communities:users.failedToUpdateRole");
      toast.error(message);
    },
  });

  const setMemberApiAccess = useSetMemberApiAccess({
    onSuccess: () => toast.success(t("users.apiAccessSaved")),
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "communities:users.apiAccessError"));
    },
  });

  const handleRoleChange = (userId: number, role: CommunityRole) => {
    // Update community membership role
    updateCommunityMembership.mutate({ communityId: activeCommunityId!, userId, role });
  };

  const handleDeleteUser = (userId: number, email: string) => {
    // Backend handles validation (e.g., cannot delete the last platform owner)
    setDeleteUserConfirm({ userId, email });
  };

  const exportCommunityUsers = useExportCommunityUsersCsv({
    onError: (err) => {
      toast.error(getErrorMessage(err, "communities:users.exportError"));
    },
  });

  const exportUserCsv = (communityMember: UserCommunityMember) => {
    const safeHandle = communityMember.username.replace(/[^a-zA-Z0-9._-]+/g, "_");
    exportCommunityUsers.mutate({
      params: { user_id: [communityMember.id] },
      filename: `user-${communityMember.id}-${safeHandle}.csv`,
    });
  };

  const exportAllUsersCsv = () => {
    const safeCommunityName = (activeCommunity?.name ?? "community").replace(
      /[^a-zA-Z0-9._-]+/g,
      "_"
    );
    const datestamp = new Date().toISOString().slice(0, 10);
    exportCommunityUsers.mutate({
      params: {},
      filename: `${safeCommunityName}-users-${datestamp}.csv`,
    });
  };

  if (!isCommunityAdmin) {
    return <p className="text-muted-foreground text-sm">{t("users.adminRequired")}</p>;
  }

  if (usersQuery.isLoading) {
    return (
      <SkeletonRegion label={t("users.loadingSettings")} className="space-y-6">
        <FormSkeleton fields={2} />
        <TableSkeleton rows={6} columns={6} />
      </SkeletonRegion>
    );
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("users.unableToLoadSettings")}</p>;
  }

  // The handle leads: every member has one. A name is only the display name
  // somebody set here, so the column shows once someone on the page has one.
  const showsNames = rows.some((row) => row.display_name?.trim());

  const userColumns: AppColumnDef<UserCommunityMember>[] = [
    {
      accessorKey: "id",
      header: t("users.userIdColumn"),
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.id}</p>
      ),
    },
    {
      id: "username",
      // The whole handle, as the cell draws it — see the platform roster.
      accessorFn: (row: UserCommunityMember) => getUserHandle(row),
      header: t("users.handleColumn"),
      // The handle is what identifies someone, so it is also what opens them.
      cell: ({ row }) => (
        <Link
          to="/u/$handle"
          params={{ handle: getUrlHandle(row.original) }}
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
                <p className="font-medium">{row.original.display_name?.trim() || "—"}</p>
              </div>
            ),
          } satisfies AppColumnDef<UserCommunityMember>,
        ]
      : []),
    {
      accessorKey: "community_role",
      header: t("users.communityRoleColumn"),
      cell: ({ row }) => {
        const communityMember = row.original;
        const isSelf = communityMember.id === user?.id;
        const currentCommunityRole = communityMember.community_role ?? "member";
        return (
          <div className="flex flex-col gap-1">
            <Select
              value={currentCommunityRole}
              onValueChange={(value) =>
                handleRoleChange(communityMember.id, value as CommunityRole)
              }
              disabled={isSelf || updateCommunityMembership.isPending}
            >
              <SelectTrigger disabled={isSelf} className="min-w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roleOptions.map((roleOption) => (
                  <SelectItem key={roleOption} value={roleOption}>
                    {t(`users.communityRole.${roleOption}` as never)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      },
    },
    ...(showsApiAccess
      ? [
          {
            accessorKey: "api_keys_allowed",
            header: t("users.apiAccessColumn"),
            cell: ({ row }) => {
              const communityMember = row.original;
              return (
                <Switch
                  checked={communityMember.api_keys_allowed ?? true}
                  aria-label={t("users.apiAccessLabel", {
                    name: getUserDisplayName(communityMember),
                  })}
                  disabled={setMemberApiAccess.isPending}
                  onCheckedChange={(allowed) =>
                    setMemberApiAccess.mutate({
                      communityId: activeCommunityId!,
                      userId: communityMember.id,
                      allowed,
                    })
                  }
                />
              );
            },
          } satisfies AppColumnDef<UserCommunityMember>,
        ]
      : []),
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
        const communityMember = row.original;
        const isSelf = communityMember.id === user?.id;
        return (
          <RowActionsMenu subject={getUserDisplayName(communityMember)}>
            <DropdownMenuItem onSelect={() => exportUserCsv(communityMember)}>
              <Download className="h-4 w-4" />
              {t("users.exportUser")}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setNamingMember(communityMember)}>
              <IdCard className="h-4 w-4" />
              {t("displayName.adminAction")}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setTransferTarget({ member: communityMember })}>
              <HandCoins className="h-4 w-4" />
              {t("transferOwnership.action")}
            </DropdownMenuItem>
            {/* Removing somebody from the community is the destructive one, and
                the only one you cannot aim at yourself. */}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive"
              onSelect={() =>
                handleDeleteUser(communityMember.id, getUserDisplayName(communityMember))
              }
              disabled={isSelf}
            >
              <UserMinus className="h-4 w-4" />
              {t("users.removeFromCommunity")}
            </DropdownMenuItem>
          </RowActionsMenu>
        );
      },
    },
  ];

  const createInvite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!activeCommunityId || atUserLimit) {
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
      await createCommunityInvite(
        activeCommunityId,
        payload as Parameters<typeof createCommunityInvite>[1]
      );
      await loadInvites();
    } catch (error) {
      console.error(error);
      setInvitesError(getErrorMessage(error, "communities:users.unableToCreateInvite"));
    } finally {
      setInviteSubmitting(false);
    }
  };

  const deleteInvite = async (inviteId: number) => {
    if (!activeCommunityId) {
      return;
    }
    try {
      await deleteCommunityInvite(activeCommunityId, inviteId);
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
      {managesInvites ? (
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
            {atUserLimit && canSell && activeCommunityId && activeCommunity?.can.seat ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-muted-foreground text-sm">
                  {planName
                    ? t("users.inviteSeatsFullPlan", { plan: planName, count: maxUsers ?? 0 })
                    : t("users.inviteSeatsFullUpgrade", { count: maxUsers ?? 0 })}
                </p>
                <Button size="sm" onClick={() => void openPortal(activeCommunityId, "upgrade")}>
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
              <SkeletonRegion label={t("users.loadingInvites")}>
                <ListSkeleton rows={2} avatar={false} />
              </SkeletonRegion>
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
      ) : null}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            {/* Named only beside the invites card; alone, the tab names it. */}
            {managesInvites ? <CardTitle>{t("users.usersTitle")}</CardTitle> : null}
            <CardDescription>{t("users.usersDescription")}</CardDescription>
            {/* Three words that get mixed up constantly, explained where the
                choice is actually made rather than in the help centre. */}
            <dl className="mt-3 space-y-1 text-muted-foreground text-xs">
              {roleOptions.map((roleOption) => (
                <div key={roleOption} className="flex gap-1.5">
                  <dt className="font-medium text-foreground">
                    {t(`users.communityRole.${roleOption}` as never)}
                  </dt>
                  <dd>{t(`users.communityRoleHelp.${roleOption}` as never)}</dd>
                </div>
              ))}
              {showsApiAccess ? (
                <div className="flex gap-1.5">
                  <dt className="font-medium text-foreground">{t("users.apiAccessColumn")}</dt>
                  <dd>{t("users.apiAccessHelp")}</dd>
                </div>
              ) : null}
            </dl>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={exportAllUsersCsv}
            disabled={totalCount === 0 && !search.trim()}
          >
            <Download className="h-4 w-4" />
            {t("users.exportAll")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={rows}
            getRowId={(row) => String(row.id)}
            enableFilterInput
            filterInputPlaceholder={t("users.filterByHandle")}
            filterValue={draft}
            onFilterValueChange={(value) => {
              setDraft(value);
              setPage(1);
            }}
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
      </Card>

      <UnownedContentCard onClaim={() => setTransferTarget({ member: null })} />

      <RemoveCommunityMemberDialog
        open={deleteUserConfirm !== null}
        onOpenChange={(open) => !open && setDeleteUserConfirm(null)}
        userId={deleteUserConfirm?.userId ?? null}
        email={deleteUserConfirm?.email ?? ""}
      />

      {activeCommunityId ? (
        <MemberDisplayNameDialog
          open={namingMember !== null}
          onOpenChange={(open) => !open && setNamingMember(null)}
          communityId={activeCommunityId}
          member={
            namingMember ? { id: namingMember.id, name: getUserHandle(namingMember) } : undefined
          }
          current={namingMember?.display_name}
        />
      ) : null}

      <TransferContentOwnershipDialog
        open={transferTarget !== null}
        onOpenChange={(open) => !open && setTransferTarget(null)}
        member={transferTarget?.member ?? null}
        defaultRecipient={user}
        onSuccess={() => void usersQuery.refetch()}
      />
    </div>
  );
};
