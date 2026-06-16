import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, Loader2 } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeMemberRead,
  InitiativeRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TabsContent } from "@/components/ui/tabs";
import {
  useAddInitiativeMember,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import { useUsers } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

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

// Sentinel value for the "Admin (full access, no manager elevation)" choice in
// the guild-admin role selector — distinguishes it from a real role id.
const ADMIN_ROLE_VALUE = "admin";

// A guild admin with no initiative-level role (i.e. not a project manager).
// These are grouped into a collapsed section since their access comes from the
// guild role, not a per-initiative role.
const isAdminOnly = (member: { isGuildAdmin: boolean; isManager: boolean }) =>
  member.isGuildAdmin && !member.isManager;

// A unified row for the members table: a real initiative member, or a guild
// admin who is an implicit full-access member with no membership row.
type DisplayMember = {
  user: { id: number; full_name: string | null; email: string };
  role_id: number | null;
  role_display_name: string | null;
  role: string;
  oidc_managed: boolean;
  isGuildAdmin: boolean;
  // Whether this row holds a manager (project manager) initiative role.
  isManager: boolean;
  // Present only for real membership rows, for the remove action.
  original: InitiativeMemberRead | null;
};

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
  const { data: roleLabels } = useRoleLabels();

  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);
  const adminRoleLabel = t("settings.guildAdminRole");

  // Fetched only for members managers (who can act on the roster) to identify
  // guild admins for the greyed/collapsed treatment — read-only viewers never
  // pull the full guild roster. The members tab is only reachable by guild
  // admins / initiative managers, so this gate doesn't hide admins in practice.
  const usersQuery = useUsers({
    enabled: canManageMembers && !!activeGuildId,
    staleTime: 5 * 60 * 1000,
  });

  // The manager role is the one allowed elevation for a guild admin.
  const managerRole = useMemo(
    () =>
      roles?.find((role) => role.is_manager) ??
      roles?.find((role) => role.name === "project_manager"),
    [roles]
  );

  const adminUserIds = useMemo(
    () =>
      new Set(
        (usersQuery.data ?? [])
          .filter((candidate) => candidate.guild_role === "admin")
          .map((candidate) => candidate.id)
      ),
    [usersQuery.data]
  );

  // Merge explicit members with guild admins who have no membership row: admins
  // are implicit full-access members and must always appear, greyed out.
  const displayMembers = useMemo<DisplayMember[]>(() => {
    const rows: DisplayMember[] = members.map((member) => ({
      user: {
        id: member.user.id,
        full_name: member.user.full_name,
        email: member.user.email,
      },
      role_id: member.role_id ?? null,
      role_display_name: member.role_display_name ?? null,
      role: member.role,
      oidc_managed: member.oidc_managed,
      isGuildAdmin: adminUserIds.has(member.user.id),
      isManager: member.is_manager ?? false,
      original: member,
    }));

    const presentIds = new Set(members.map((member) => member.user.id));
    for (const candidate of usersQuery.data ?? []) {
      if (candidate.guild_role !== "admin" || presentIds.has(candidate.id)) {
        continue;
      }
      rows.push({
        user: {
          id: candidate.id,
          full_name: candidate.full_name,
          email: candidate.email,
        },
        role_id: null,
        role_display_name: null,
        role: "member",
        oidc_managed: false,
        isGuildAdmin: true,
        isManager: false,
        original: null,
      });
    }
    return rows;
  }, [members, usersQuery.data, adminUserIds]);

  // Admins with no initiative-level role (not a project manager) are grouped
  // into a collapsed section — they have full access by virtue of their guild
  // role, not a per-initiative role. Everyone else (members, custom roles, and
  // admins who are also project managers) appears in the main table.
  const mainMembers = useMemo(
    () => displayMembers.filter((member) => !isAdminOnly(member)),
    [displayMembers]
  );
  const adminOnlyMembers = useMemo(() => displayMembers.filter(isAdminOnly), [displayMembers]);

  const availableUsers = useMemo(() => {
    if (!usersQuery.data) {
      return [];
    }
    const existingIds = new Set(members.map((member) => member.user.id));
    // Guild admins are already shown by default and cannot be assigned a
    // standard role, so they are not offered in the add-member picker.
    return usersQuery.data.filter(
      (candidate) =>
        !existingIds.has(candidate.id) &&
        candidate.status !== "anonymized" &&
        candidate.guild_role !== "admin"
    );
  }, [usersQuery.data, members]);

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
    if (!selectedUserId || !selectedRoleId) {
      return;
    }
    const userId = Number(selectedUserId);
    const roleId = Number(selectedRoleId);
    if (!Number.isFinite(userId) || !Number.isFinite(roleId)) {
      return;
    }
    addMember.mutate({ initiativeId, data: { user_id: userId, role_id: roleId } });
  };

  // A guild admin always has complete access. Toggling "Project Manager"
  // creates a manager membership row (manager-style features like
  // notifications); toggling back to "Admin" removes it, reverting to implicit
  // full access. They can never hold a standard member or custom role.
  const handleAdminRoleChange = useCallback(
    (member: DisplayMember, value: string) => {
      if (!managerRole) {
        return;
      }
      if (value === String(managerRole.id)) {
        addMember.mutate({
          initiativeId,
          data: { user_id: member.user.id, role_id: managerRole.id },
        });
      } else if (member.role_id !== null) {
        removeMember.mutate({ initiativeId, userId: member.user.id });
      }
    },
    [managerRole, addMember, removeMember, initiativeId]
  );

  const memberColumns: ColumnDef<DisplayMember>[] = useMemo(() => {
    const getRoleDisplayName = (member: DisplayMember): string => {
      if (member.role_display_name) {
        return member.role_display_name;
      }
      return member.role === "project_manager" ? projectManagerLabel : memberLabel;
    };

    const adminMutationPending = addMember.isPending || removeMember.isPending;

    return [
      {
        id: "name",
        accessorKey: "user.full_name",
        header: t("settings.nameColumn"),
        cell: ({ row }) => {
          const member = row.original;
          return (
            <span className="flex items-center gap-2">
              <span
                className={
                  member.isGuildAdmin ? "font-medium text-muted-foreground" : "font-medium"
                }
              >
                {member.user.full_name?.trim() || "—"}
              </span>
              {member.isGuildAdmin ? (
                <Badge variant="secondary" className="font-normal">
                  {adminRoleLabel}
                </Badge>
              ) : null}
            </span>
          );
        },
      },
      {
        id: "email",
        accessorKey: "user.email",
        header: t("settings.emailColumn"),
        cell: ({ row }) => {
          const member = row.original;
          return <span className="text-muted-foreground">{member.user.email}</span>;
        },
      },
      {
        accessorKey: "role",
        header: t("settings.roleColumn"),
        cell: ({ row }) => {
          const member = row.original;
          // Guild admins: greyed out, full access by default, optionally a
          // project manager. Never a standard member or custom role.
          if (member.isGuildAdmin) {
            const isManager = managerRole != null && member.role_id === managerRole.id;
            if (!canManageMembers || !managerRole) {
              return (
                <Badge variant="outline" className="text-muted-foreground">
                  {isManager ? projectManagerLabel : adminRoleLabel}
                </Badge>
              );
            }
            return (
              <Select
                value={isManager ? String(managerRole.id) : ADMIN_ROLE_VALUE}
                onValueChange={(value) => handleAdminRoleChange(member, value)}
                disabled={adminMutationPending}
              >
                <SelectTrigger className="w-44 text-muted-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ADMIN_ROLE_VALUE}>{adminRoleLabel}</SelectItem>
                  <SelectItem value={String(managerRole.id)}>{managerRole.display_name}</SelectItem>
                </SelectContent>
              </Select>
            );
          }

          if (!canManageMembers || !roles) {
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
          // Guild admins are implicit members and cannot be removed; their
          // access is conferred by their guild role, not a membership row.
          if (!canManageMembers || member.isGuildAdmin || !member.original) {
            return null;
          }
          const original = member.original;
          return (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemoveMember(original)}
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
    canManageMembers,
    roles,
    managerRole,
    adminRoleLabel,
    addMember.isPending,
    removeMember,
    updateMemberRole,
    handleAdminRoleChange,
    projectManagerLabel,
    memberLabel,
    initiativeId,
    onRemoveMember,
  ]);

  return (
    <TabsContent value="members">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.membersTitle")}</CardTitle>
          <CardDescription>{t("settings.membersDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={memberColumns}
            data={mainMembers}
            enableFilterInput
            filterInputColumnKey="name"
            filterInputPlaceholder={t("settings.filterByName")}
            enablePagination
          />
          {adminOnlyMembers.length > 0 ? (
            <Collapsible className="rounded-md border">
              <CollapsibleTrigger className="group flex w-full items-center justify-between px-4 py-3 text-left font-medium text-muted-foreground text-sm hover:bg-muted/50">
                <span>{t("settings.guildAdminsSection", { count: adminOnlyMembers.length })}</span>
                <ChevronDown className="h-4 w-4 transition-transform group-data-[state=open]:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <p className="px-4 pb-2 text-muted-foreground text-xs">
                  {t("settings.guildAdminsSectionHint")}
                </p>
                <div className="px-1 pb-1">
                  <DataTable columns={memberColumns} data={adminOnlyMembers} enablePagination />
                </div>
              </CollapsibleContent>
            </Collapsible>
          ) : null}
          {canManageMembers ? (
            <>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <SearchableCombobox
                  items={availableUsers.map((candidate) => ({
                    value: String(candidate.id),
                    label: candidate.full_name?.trim() || candidate.email,
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
                  <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
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
                    !selectedRoleId ||
                    addMember.isPending ||
                    usersQuery.isLoading ||
                    availableUsers.length === 0
                  }
                >
                  {addMember.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
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
    </TabsContent>
  );
};
