import { Loader2 } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeMemberRead,
  InitiativeRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeJoinRequestQueue } from "@/components/initiatives/settings/InitiativeJoinRequestQueue";
import { UserHandle } from "@/components/UserHandle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useAddInitiativeMember,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import { useUsers } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";

interface InitiativeSettingsMembersTabProps {
  initiativeId: number;
  members: InitiativeMemberRead[];
  roles: InitiativeRoleRead[] | undefined;
  canManageMembers: boolean;
  activeGuildId: number | undefined;
  selectedUserId: string;
  setSelectedUserId: (value: string) => void;
  selectedRoleId: string;
  setSelectedRoleId: (value: string) => void;
  onRemoveMember: (member: InitiativeMemberRead) => void;
}

export const InitiativeSettingsMembersTab = ({
  initiativeId,
  members,
  roles,
  canManageMembers,
  activeGuildId,
  selectedUserId,
  setSelectedUserId,
  selectedRoleId,
  setSelectedRoleId,
  onRemoveMember,
}: InitiativeSettingsMembersTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  // Fetched only for members managers (who can act on the roster) — read-only
  // viewers never pull the full guild roster.
  const usersQuery = useUsers({
    enabled: canManageMembers && !!activeGuildId,
    staleTime: 5 * 60 * 1000,
  });

  const availableUsers = useMemo(() => {
    if (!usersQuery.data) {
      return [];
    }
    const existingIds = new Set(members.map((member) => member.user.id));
    return usersQuery.data.filter(
      (candidate) => !existingIds.has(candidate.id) && candidate.status !== "anonymized"
    );
  }, [usersQuery.data, members]);

  // A guild admin's standing already reaches every initiative, so the only
  // initiative role their row can hold is the manager one — the server settles
  // that on the way in. The picker says so up front rather than offering a
  // choice that would be rewritten.
  const adminIds = useMemo(
    () =>
      new Set(
        (usersQuery.data ?? [])
          .filter((candidate) => candidate.guild_role === "admin")
          .map((candidate) => candidate.id)
      ),
    [usersQuery.data]
  );
  const managerRole = useMemo(
    () =>
      roles?.find((role) => role.is_manager) ??
      roles?.find((role) => role.name === "project_manager"),
    [roles]
  );
  const addingAdmin = adminIds.has(Number(selectedUserId));
  const effectiveRoleId = addingAdmin && managerRole ? String(managerRole.id) : selectedRoleId;

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
  // anything to the member column beside it.
  const showsNames = Boolean(activeGuild?.show_member_names);

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
          if (!canManageMembers || !roles || adminIds.has(member.user.id)) {
            return <Badge variant="outline">{getRoleDisplayName(member)}</Badge>;
          }
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
                {roles.map((role) => (
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
    <div className="space-y-4">
      {/* Requests come before the roster: they are the roster's inbox, and
          answering one is the same act as adding a member by hand. Manager-only,
          matching who may answer them. */}
      {canManageMembers ? <InitiativeJoinRequestQueue initiativeId={initiativeId} /> : null}
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.membersTitle")}</CardTitle>
          <CardDescription>{t("settings.membersDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={memberColumns}
            data={members}
            enableFilterInput
            filterInputColumnKey="name"
            filterInputPlaceholder={t("settings.filterByName")}
            enablePagination
          />
          {canManageMembers ? (
            <>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <SearchableCombobox
                  items={availableUsers.map((candidate) => ({
                    value: String(candidate.id),
                    label: getUserDisplayName(candidate),
                  }))}
                  value={selectedUserId}
                  onValueChange={setSelectedUserId}
                  placeholder={
                    usersQuery.isLoading
                      ? t("settings.loadingMembers")
                      : availableUsers.length > 0
                        ? t("settings.selectUser")
                        : t("settings.everyoneAdded")
                  }
                  disabled={usersQuery.isLoading || availableUsers.length === 0}
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
                  disabled={
                    !selectedUserId ||
                    !effectiveRoleId ||
                    addMember.isPending ||
                    usersQuery.isLoading ||
                    availableUsers.length === 0
                  }
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
              {usersQuery.isError ? (
                <p className="text-destructive text-xs">{t("settings.unableToLoadMembers")}</p>
              ) : null}
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
};
