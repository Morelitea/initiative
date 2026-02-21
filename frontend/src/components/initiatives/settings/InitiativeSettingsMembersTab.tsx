import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import type { ColumnDef } from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import { TabsContent } from "@/components/ui/tabs";
import type {
  InitiativeMemberRead,
  InitiativeRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useAddInitiativeMember,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import { useUsers } from "@/hooks/useUsers";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";

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
  const { data: roleLabels } = useRoleLabels();

  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);

  const usersQuery = useUsers({
    enabled: canManageMembers && !!activeGuildId,
    staleTime: 5 * 60 * 1000,
  });

  const availableUsers = useMemo(() => {
    if (!usersQuery.data || !members) {
      return [];
    }
    const existingIds = new Set(members.map((member) => member.user.id));
    return usersQuery.data.filter((candidate) => !existingIds.has(candidate.id));
  }, [usersQuery.data, members]);

  const addMember = useAddInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.memberAdded"));
      setSelectedUserId("");
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.addMemberError");
      toast.error(message);
    },
  });

  const removeMember = useRemoveInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.memberRemoved"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.removeMemberError");
      toast.error(message);
    },
  });

  const updateMemberRole = useUpdateInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.roleUpdated"));
    },
    onError: () => {
      toast.error(t("settings.roleUpdateError"));
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

  const memberColumns: ColumnDef<InitiativeMemberRead>[] = useMemo(() => {
    // Get role display name for a member
    const getRoleDisplayName = (member: InitiativeMemberRead): string => {
      if (member.role_display_name) {
        return member.role_display_name;
      }
      // Fallback to legacy role
      return member.role === "project_manager" ? projectManagerLabel : memberLabel;
    };

    return [
      {
        id: "name",
        accessorKey: "user.full_name",
        header: t("settings.nameColumn"),
        cell: ({ row }) => {
          const member = row.original;
          return <span className="font-medium">{member.user.full_name?.trim() || "\u2014"}</span>;
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
            <span className="bg-muted text-muted-foreground inline-flex items-center rounded-md px-2 py-1 text-sm font-medium">
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
    canManageMembers,
    roles,
    removeMember,
    updateMemberRole,
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
