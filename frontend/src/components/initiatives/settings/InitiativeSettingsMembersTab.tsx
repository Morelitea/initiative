import type { PaginationState } from "@tanstack/react-table";
import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeJoinPolicy,
  InitiativeMemberRead,
  InitiativeRoleRead,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { JoinPolicySection } from "@/components/initiatives/JoinPolicySection";
import { InitiativeJoinRequestQueue } from "@/components/initiatives/settings/InitiativeJoinRequestQueue";
import { useSeenMembers } from "@/components/members/MemberSearchSelect";
import { UserHandle } from "@/components/UserHandle";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useAddInitiativeMember,
  useInitiativeRoster,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import {
  type MemberSearchScope,
  USER_ID_LOOKUP_MAX,
  useInitiativeMemberSearch,
  useUserSearch,
} from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { isAdminRole } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";

const GUILD_SCOPE: MemberSearchScope = { type: "guild" };
const NONE: never[] = [];

interface InitiativeSettingsMembersTabProps {
  initiativeId: number;
  roles: InitiativeRoleRead[] | undefined;
  canManageMembers: boolean;
  /** How guild members may join this initiative. */
  joinPolicy: InitiativeJoinPolicy;
  onChangeJoinPolicy: (value: InitiativeJoinPolicy) => void;
  /** Whether every new guild member is enrolled here on arrival. */
  autoJoin: boolean;
  onChangeAutoJoin: (next: boolean) => void;
  /** Auto-join is the guild admin's to set, even among initiative managers. */
  canManageAutoJoin: boolean;
  /** A policy or auto-join save is in flight. */
  isSavingJoinPolicy: boolean;
  activeGuildId: number | undefined;
  selectedUserId: string;
  setSelectedUserId: (value: string) => void;
  selectedRoleId: string;
  setSelectedRoleId: (value: string) => void;
  onRemoveMember: (member: InitiativeMemberRead) => void;
}

export const InitiativeSettingsMembersTab = ({
  initiativeId,
  roles,
  canManageMembers,
  joinPolicy,
  onChangeJoinPolicy,
  autoJoin,
  onChangeAutoJoin,
  canManageAutoJoin,
  isSavingJoinPolicy,
  activeGuildId,
  selectedUserId,
  setSelectedUserId,
  selectedRoleId,
  setSelectedRoleId,
  onRemoveMember,
}: InitiativeSettingsMembersTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  // The roster is searched and paged on the server: the table only ever holds
  // the page on screen.
  const [draft, setDraft] = useState("");
  const rosterSearch = useDebouncedValue(draft, 250);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const rosterQuery = useInitiativeRoster(initiativeId, {
    search: rosterSearch.trim() || undefined,
    page,
    page_size: pageSize,
  });
  const members = useMemo(() => rosterQuery.data?.items ?? [], [rosterQuery.data]);
  const totalCount = rosterQuery.data?.total_count ?? 0;

  // The add-member picker asks the guild for the people matching what was
  // typed, once it is open, and leaves out the ones already here. Only a
  // members manager is shown it.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState("");
  const candidatesQuery = useUserSearch({
    search,
    enabled: canManageMembers && !!activeGuildId && pickerOpen,
  });
  const candidateIds = useMemo(
    () => (candidatesQuery.data?.items ?? []).map((candidate) => candidate.id),
    [candidatesQuery.data]
  );
  const alreadyInQuery = useInitiativeMemberSearch(initiativeId, {
    userIds: candidateIds,
    pageSize: USER_ID_LOOKUP_MAX,
    enabled: candidateIds.length > 0,
  });
  const availableUsers = useMemo(() => {
    const existingIds = new Set((alreadyInQuery.data?.items ?? []).map((member) => member.id));
    return (candidatesQuery.data?.items ?? []).filter(
      (candidate) => !existingIds.has(candidate.id) && candidate.status !== "anonymized"
    );
  }, [candidatesQuery.data, alreadyInQuery.data]);
  const memberIds = useMemo(() => members.map((member) => member.user.id), [members]);
  // The person picked, held so the trigger keeps their name (and the role
  // select their standing) after the search moves on.
  const [picked, setPicked] = useState<UserSummary | null>(null);
  const pickedUser = picked && String(picked.id) === selectedUserId ? picked : null;

  // A guild admin's standing already reaches every initiative, so their row
  // lands on the moderator role — the server settles that on the way in. The
  // picker says so up front rather than offering a choice that would be
  // rewritten. Who is an admin is the guild's to say, so the members already
  // here are looked up by id.
  const knownMembers = useSeenMembers(
    GUILD_SCOPE,
    canManageMembers ? memberIds : NONE,
    undefined,
    NONE
  );
  const adminIds = useMemo(
    () =>
      new Set(
        [...knownMembers.values()]
          .filter((member) => isAdminRole(member.guild_role))
          .map((member) => member.id)
      ),
    [knownMembers]
  );
  const adminRole = useMemo(
    () =>
      roles?.find((role) => role.name === "moderator") ?? roles?.find((role) => role.is_manager),
    [roles]
  );
  const addingAdmin = isAdminRole(pickedUser?.guild_role);
  const effectiveRoleId = addingAdmin && adminRole ? String(adminRole.id) : selectedRoleId;

  const addMember = useAddInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.memberAdded"));
      setSelectedUserId("");
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.addMemberError"));
    },
  });

  const removeMember = useRemoveInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.memberRemoved"));
    },
    // Surfaces the backend's specific reason (e.g. removing the last project
    // manager — INITIATIVE_MUST_HAVE_MANAGER) instead of a generic failure.
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.removeMemberError"));
    },
  });

  const updateMemberRole = useUpdateInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.roleUpdated"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleUpdateError"));
    },
  });

  const handleAddMember = () => {
    if (!selectedUserId || !effectiveRoleId) {
      return;
    }
    const userId = Number(selectedUserId);
    const roleId = Number(effectiveRoleId);
    if (!Number.isFinite(userId) || !Number.isFinite(roleId)) {
      return;
    }
    addMember.mutate({ initiativeId, data: { user_id: userId, role_id: roleId } });
  };

  const { activeGuild } = useGuilds();

  // What this guild calls people, which decides whether a handle column adds
  // anything to the member column beside it. A name a member set here counts
  // too, wherever the guild otherwise renders handles.
  const showsNames =
    Boolean(activeGuild?.show_member_names) ||
    members.some((member) => member.user.full_name?.trim());

  const memberColumns: AppColumnDef<InitiativeMemberRead>[] = useMemo(() => {
    const getRoleDisplayName = (member: InitiativeMemberRead): string => {
      if (member.role_display_name) {
        return member.role_display_name;
      }
      const roleFromList = roles?.find((role) => role.name === member.role_name)?.display_name;
      return roleFromList ?? member.role_name ?? "";
    };

    return [
      // The handle leads: every guild has one for every member, and it is the
      // identifier the rest of the app shows.
      {
        id: "handle",
        accessorKey: "user.username",
        header: t("settings.handleColumn"),
        cell: ({ row }) => <UserHandle user={row.original.user} />,
      },
      // A guild that renders handles sends no names, so this column would be a
      // full one of em-dashes.
      ...(showsNames
        ? [
            {
              id: "name",
              accessorKey: "user.full_name",
              header: t("settings.nameColumn"),
              cell: ({ row }) => (
                <span className="font-medium">{row.original.user.full_name?.trim() || "—"}</span>
              ),
            } satisfies AppColumnDef<InitiativeMemberRead>,
          ]
        : []),
      {
        accessorKey: "role_name",
        header: t("settings.roleColumn"),
        cell: ({ row }) => {
          const member = row.original;
          if (!canManageMembers || !roles) {
            return <Badge variant="outline">{getRoleDisplayName(member)}</Badge>;
          }
          // A community admin already on a manager role has nothing to choose:
          // it is the only role their row can hold. One that is not — promoted
          // to admin after joining, so their row kept the role they joined
          // with — keeps the picker, narrowed to the manager roles, because
          // this is where that row gets put right.
          const isAdmin = adminIds.has(member.user.id);
          if (isAdmin && member.is_manager) {
            return <Badge variant="outline">{getRoleDisplayName(member)}</Badge>;
          }
          const options = isAdmin ? roles.filter((role) => role.is_manager) : roles;
          return (
            <Select
              value={String(member.role_id || "")}
              onValueChange={(value) =>
                updateMemberRole.mutate({
                  initiativeId,
                  userId: member.user.id,
                  data: { role_id: Number(value) },
                })
              }
              disabled={updateMemberRole.isPending}
            >
              <SelectTrigger className="w-44">
                <SelectValue placeholder="Role" />
              </SelectTrigger>
              <SelectContent>
                {options.map((role) => (
                  <SelectItem key={role.id} value={String(role.id)}>
                    {role.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          );
        },
      },
      {
        accessorKey: "oidc_managed",
        header: t("settings.sourceColumn"),
        cell: ({ row }) => {
          return row.original.oidc_managed ? (
            <span className="inline-flex items-center rounded-md bg-muted px-2 py-1 font-medium text-muted-foreground text-sm">
              {t("settings.sourceOidc")}
            </span>
          ) : (
            <span className="text-muted-foreground text-sm">{t("settings.sourceManual")}</span>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => {
          const member = row.original;
          if (!canManageMembers) {
            return null;
          }
          return (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemoveMember(member)}
              disabled={removeMember.isPending}
              className="text-destructive"
            >
              {t("settings.removeMember")}
            </Button>
          );
        },
      },
    ];
  }, [
    t,
    adminIds,
    canManageMembers,
    roles,
    showsNames,
    removeMember,
    updateMemberRole,
    initiativeId,
    onRemoveMember,
  ]);

  return (
    <div className="space-y-6">
      {/* Requests come before the roster: they are the roster's inbox, and
          answering one is the same act as adding a member by hand. Manager-only,
          matching who may answer them. */}
      {canManageMembers ? <InitiativeJoinRequestQueue initiativeId={initiativeId} /> : null}
      {/* The door, above the people who came through it. It saves on change —
          it is a single setting, not a field of a form with a Save button. */}
      <JoinPolicySection
        value={joinPolicy}
        onChange={onChangeJoinPolicy}
        canManage={canManageMembers}
        isSaving={isSavingJoinPolicy}
        autoJoin={autoJoin}
        // Absent for a manager who is not a guild admin: the server refuses the
        // field from them, so the control is not offered rather than shown inert.
        onChangeAutoJoin={canManageAutoJoin ? onChangeAutoJoin : undefined}
      />
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.membersTitle")}</CardTitle>
          <CardDescription>{t("settings.membersDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={memberColumns}
            data={members}
            getRowId={(row) => String(row.user.id)}
            enableFilterInput
            filterInputPlaceholder={t("settings.filterByName")}
            filterValue={draft}
            onFilterValueChange={(value) => {
              setDraft(value);
              setPage(1);
            }}
            enablePagination
            manualPagination
            pageCount={Math.max(1, Math.ceil(totalCount / pageSize))}
            rowCount={totalCount}
            // The page the server answered with: a page emptied by a removal
            // comes back as page 1.
            pageIndex={(rosterQuery.data?.page ?? page) - 1}
            onPaginationChange={(next: PaginationState) => {
              if (next.pageSize !== pageSize) {
                setPageSize(next.pageSize);
                setPage(1);
              } else {
                setPage(next.pageIndex + 1);
              }
            }}
          />
          {canManageMembers ? (
            <>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <AsyncCombobox
                  items={availableUsers.map((candidate) => ({
                    value: String(candidate.id),
                    label: getUserDisplayName(candidate),
                  }))}
                  value={selectedUserId}
                  onValueChange={(value) => {
                    setPicked(availableUsers.find((c) => String(c.id) === value) ?? null);
                    setSelectedUserId(value);
                  }}
                  onSearchChange={setSearch}
                  onOpenChange={setPickerOpen}
                  selectedLabel={pickedUser ? getUserDisplayName(pickedUser) : null}
                  loading={candidatesQuery.isFetching && availableUsers.length === 0}
                  placeholder={t("settings.selectUser")}
                  emptyMessage={t("settings.noOneToAdd")}
                  aria-label={t("settings.selectUser")}
                />
                {roles && (
                  <Select
                    value={effectiveRoleId}
                    onValueChange={setSelectedRoleId}
                    disabled={addingAdmin}
                  >
                    <SelectTrigger className="w-44">
                      <SelectValue placeholder={t("settings.selectRole")} />
                    </SelectTrigger>
                    <SelectContent>
                      {roles.map((role) => (
                        <SelectItem key={role.id} value={String(role.id)}>
                          {role.display_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleAddMember}
                  disabled={!selectedUserId || !effectiveRoleId || addMember.isPending}
                >
                  {addMember.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      {t("settings.adding")}
                    </>
                  ) : (
                    t("settings.addMember")
                  )}
                </Button>
              </div>
              {candidatesQuery.isError ? (
                <p className="text-destructive text-xs">{t("settings.unableToLoadMembers")}</p>
              ) : null}
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
};
