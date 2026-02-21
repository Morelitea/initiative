import { useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { TabsContent } from "@/components/ui/tabs";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import {
  useAddProjectMember,
  useUpdateProjectMember,
  useRemoveProjectMember,
  useAddProjectMembersBulk,
  useRemoveProjectMembersBulk,
  useAddProjectRolePermission,
  useUpdateProjectRolePermission,
  useRemoveProjectRolePermission,
} from "@/hooks/useProjects";
import type {
  ProjectPermissionLevel,
  ProjectRead,
  ProjectRolePermissionRead,
} from "@/api/generated/initiativeAPI.schemas";

interface PermissionRow {
  userId: number;
  displayName: string;
  email: string;
  level: ProjectPermissionLevel;
  isOwner: boolean;
}

interface ProjectSettingsAccessTabProps {
  project: ProjectRead;
  projectId: number;
}

export const ProjectSettingsAccessTab = ({ project, projectId }: ProjectSettingsAccessTabProps) => {
  const { t } = useTranslation("projects");

  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [selectedNewUserId, setSelectedNewUserId] = useState<string>("");
  const [selectedNewLevel, setSelectedNewLevel] = useState<ProjectPermissionLevel>("read");
  const [selectedMembers, setSelectedMembers] = useState<PermissionRow[]>([]);
  const [roleAccessMessage, setRoleAccessMessage] = useState<string | null>(null);
  const [roleAccessError, setRoleAccessError] = useState<string | null>(null);
  const [selectedNewRoleId, setSelectedNewRoleId] = useState<string>("");
  const [selectedNewRoleLevel, setSelectedNewRoleLevel] = useState<"read" | "write">("read");

  const initiativeRolesQuery = useInitiativeRoles(project.initiative_id ?? null);

  const addMember = useAddProjectMember(projectId, {
    onSuccess: () => {
      setAccessMessage(t("settings.access.granted"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.grantError"));
    },
  });

  const updateMemberLevel = useUpdateProjectMember(projectId, {
    onSuccess: () => {
      setAccessMessage(t("settings.access.updated"));
      setAccessError(null);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.updateError"));
    },
  });

  const removeMember = useRemoveProjectMember(projectId, {
    onSuccess: () => {
      setAccessMessage(t("settings.access.removed"));
      setAccessError(null);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.removeError"));
    },
  });

  const addAllMembers = useAddProjectMembersBulk(projectId, {
    onSuccess: () => {
      setAccessMessage(t("settings.access.grantedAll"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.grantAllError"));
    },
  });

  const bulkUpdateLevel = useAddProjectMembersBulk(projectId, {
    onSuccess: () => {
      setAccessMessage(t("settings.access.bulkUpdated"));
      setAccessError(null);
      setSelectedMembers([]);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.bulkUpdateError"));
    },
  });

  const bulkRemoveMembers = useRemoveProjectMembersBulk(projectId, {
    onSuccess: () => {
      setAccessMessage(t("settings.access.bulkRemoved"));
      setAccessError(null);
      setSelectedMembers([]);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.bulkRemoveError"));
    },
  });

  const addRolePermission = useAddProjectRolePermission(projectId, {
    onSuccess: () => {
      setRoleAccessMessage(t("settings.roleAccess.granted"));
      setRoleAccessError(null);
      setSelectedNewRoleId("");
      setSelectedNewRoleLevel("read");
    },
    onError: () => {
      setRoleAccessMessage(null);
      setRoleAccessError(t("settings.roleAccess.grantError"));
    },
  });

  const updateRolePermission = useUpdateProjectRolePermission(projectId, {
    onSuccess: () => {
      setRoleAccessMessage(t("settings.roleAccess.updated"));
      setRoleAccessError(null);
    },
    onError: () => {
      setRoleAccessMessage(null);
      setRoleAccessError(t("settings.roleAccess.updateError"));
    },
  });

  const removeRolePermission = useRemoveProjectRolePermission(projectId, {
    onSuccess: () => {
      setRoleAccessMessage(t("settings.roleAccess.removed"));
      setRoleAccessError(null);
    },
    onError: () => {
      setRoleAccessMessage(null);
      setRoleAccessError(t("settings.roleAccess.removeError"));
    },
  });

  // Initiative roles not yet assigned to this project
  const availableRoles = useMemo(
    () =>
      (initiativeRolesQuery.data ?? []).filter(
        (role) => !(project.role_permissions ?? []).some((rp) => rp.initiative_role_id === role.id)
      ),
    [initiativeRolesQuery.data, project.role_permissions]
  );

  // Column definitions for role permissions table
  const rolePermissionColumns: ColumnDef<ProjectRolePermissionRead>[] = useMemo(
    () => [
      {
        accessorKey: "role_display_name",
        header: t("settings.roleAccess.roleNameColumn"),
        cell: ({ row }) => <span className="font-medium">{row.original.role_display_name}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.roleAccess.accessLevelColumn"),
        cell: ({ row }) => (
          <Select
            value={row.original.level}
            onValueChange={(value) => {
              setRoleAccessMessage(null);
              setRoleAccessError(null);
              updateRolePermission.mutate({
                roleId: row.original.initiative_role_id,
                data: { level: value as ProjectPermissionLevel },
              });
            }}
            disabled={updateRolePermission.isPending}
          >
            <SelectTrigger className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="read">{t("settings.roleAccess.canView")}</SelectItem>
              <SelectItem value="write">{t("settings.roleAccess.canEdit")}</SelectItem>
            </SelectContent>
          </Select>
        ),
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.roleAccess.actionsColumn")}</div>,
        cell: ({ row }) => (
          <div className="text-right">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => {
                setRoleAccessMessage(null);
                setRoleAccessError(null);
                removeRolePermission.mutate(row.original.initiative_role_id);
              }}
              disabled={removeRolePermission.isPending}
            >
              {t("settings.roleAccess.remove")}
            </Button>
          </div>
        ),
      },
    ],
    [updateRolePermission, removeRolePermission, t]
  );

  const initiativeMembers = useMemo(
    () => project.initiative?.members ?? [],
    [project.initiative?.members]
  );

  // Build permission rows with user info
  const permissionRows: PermissionRow[] = useMemo(
    () =>
      (project.permissions ?? []).map((permission) => {
        const member = initiativeMembers.find((entry) => entry.user?.id === permission.user_id);
        const ownerInfo = project.owner;
        const displayName =
          member?.user?.full_name?.trim() ||
          member?.user?.email ||
          (permission.user_id === project.owner_id
            ? ownerInfo?.full_name?.trim() || ownerInfo?.email || "Project owner"
            : `User ${permission.user_id}`);
        const email =
          member?.user?.email ||
          (permission.user_id === project.owner_id ? ownerInfo?.email || "" : "");
        return {
          userId: permission.user_id,
          displayName,
          email,
          level: permission.level,
          isOwner: permission.user_id === project.owner_id,
        };
      }),
    [project.permissions, project.owner, project.owner_id, initiativeMembers]
  );

  // Column definitions for the permissions table
  const permissionColumns: ColumnDef<PermissionRow>[] = useMemo(
    () => [
      {
        accessorKey: "displayName",
        header: t("settings.access.nameColumn"),
        cell: ({ row }) => <span className="font-medium">{row.original.displayName}</span>,
      },
      {
        accessorKey: "email",
        header: t("settings.access.emailColumn"),
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.email}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.access.accessColumn"),
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return (
              <span className="text-muted-foreground">{t("settings.access.permissionOwner")}</span>
            );
          }
          return (
            <Select
              value={row.original.level}
              onValueChange={(value) => {
                setAccessMessage(null);
                setAccessError(null);
                updateMemberLevel.mutate({
                  userId: row.original.userId,
                  data: { level: value as ProjectPermissionLevel },
                });
              }}
              disabled={updateMemberLevel.isPending}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("settings.access.permissionRead")}</SelectItem>
                <SelectItem value="write">{t("settings.access.permissionWrite")}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.access.actionsColumn")}</div>,
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <div className="text-muted-foreground text-right text-xs">-</div>;
          }
          return (
            <div className="text-right">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive"
                onClick={() => {
                  setAccessMessage(null);
                  setAccessError(null);
                  removeMember.mutate(row.original.userId);
                }}
                disabled={removeMember.isPending}
              >
                {t("settings.access.remove")}
              </Button>
            </div>
          );
        },
      },
    ],
    [updateMemberLevel, removeMember, t]
  );

  // Initiative members who don't have permissions yet
  const availableMembers = useMemo(
    () =>
      initiativeMembers.filter(
        (member) =>
          member.user &&
          !(project.permissions ?? []).some((permission) => permission.user_id === member.user.id)
      ),
    [initiativeMembers, project.permissions]
  );

  return (
    <TabsContent value="access" className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("settings.roleAccess.title")}</CardTitle>
          <CardDescription>{t("settings.roleAccess.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {(project.role_permissions ?? []).length > 0 ? (
            <DataTable
              columns={rolePermissionColumns}
              data={project.role_permissions ?? []}
              getRowId={(row) => String(row.initiative_role_id)}
            />
          ) : (
            <p className="text-muted-foreground text-sm">{t("settings.roleAccess.noRoles")}</p>
          )}

          <div className="space-y-2 pt-2">
            <Label>{t("settings.roleAccess.addRole")}</Label>
            {initiativeRolesQuery.isLoading ? (
              <p className="text-muted-foreground text-sm">
                {t("settings.roleAccess.loadingRoles")}
              </p>
            ) : availableRoles.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {t("settings.roleAccess.allRolesAssigned")}
              </p>
            ) : (
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedNewRoleId) {
                    setRoleAccessError(t("settings.roleAccess.selectRoleError"));
                    return;
                  }
                  setRoleAccessError(null);
                  addRolePermission.mutate({
                    initiative_role_id: Number(selectedNewRoleId),
                    level: selectedNewRoleLevel,
                  });
                }}
              >
                <Select value={selectedNewRoleId} onValueChange={setSelectedNewRoleId}>
                  <SelectTrigger className="min-w-[200px]">
                    <SelectValue placeholder={t("settings.roleAccess.selectRole")} />
                  </SelectTrigger>
                  <SelectContent>
                    {availableRoles.map((role) => (
                      <SelectItem key={role.id} value={String(role.id)}>
                        {role.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={selectedNewRoleLevel}
                  onValueChange={(value) => setSelectedNewRoleLevel(value as "read" | "write")}
                >
                  <SelectTrigger className="w-[130px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{t("settings.roleAccess.canView")}</SelectItem>
                    <SelectItem value="write">{t("settings.roleAccess.canEdit")}</SelectItem>
                  </SelectContent>
                </Select>
                <Button type="submit" disabled={addRolePermission.isPending}>
                  {addRolePermission.isPending
                    ? t("settings.roleAccess.adding")
                    : t("settings.roleAccess.add")}
                </Button>
              </form>
            )}
            {roleAccessMessage ? <p className="text-primary text-sm">{roleAccessMessage}</p> : null}
            {roleAccessError ? <p className="text-destructive text-sm">{roleAccessError}</p> : null}
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("settings.access.title")}</CardTitle>
          <CardDescription>{t("settings.access.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Bulk action bar */}
          {selectedMembers.length > 0 && (
            <div className="bg-muted flex items-center gap-3 rounded-md p-3">
              <span className="text-sm font-medium">
                {t("settings.access.selected", { count: selectedMembers.length })}
              </span>
              <Select
                onValueChange={(level) => {
                  const userIds = selectedMembers.filter((m) => !m.isOwner).map((m) => m.userId);
                  if (userIds.length > 0) {
                    bulkUpdateLevel.mutate({
                      user_ids: userIds,
                      level: level as ProjectPermissionLevel,
                    });
                  }
                }}
                disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
              >
                <SelectTrigger className="w-[150px]">
                  <SelectValue placeholder={t("settings.access.changeAccess")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">{t("settings.access.permissionRead")}</SelectItem>
                  <SelectItem value="write">{t("settings.access.permissionWrite")}</SelectItem>
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => {
                  const userIds = selectedMembers.filter((m) => !m.isOwner).map((m) => m.userId);
                  if (userIds.length > 0) {
                    bulkRemoveMembers.mutate({ user_ids: userIds });
                  }
                }}
                disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
              >
                {bulkRemoveMembers.isPending
                  ? t("settings.access.removing")
                  : t("settings.access.remove")}
              </Button>
            </div>
          )}

          {/* Access table */}
          <DataTable
            columns={permissionColumns}
            data={permissionRows}
            enablePagination
            enableFilterInput
            filterInputColumnKey="displayName"
            filterInputPlaceholder={t("settings.access.filterByName")}
            enableRowSelection
            onRowSelectionChange={setSelectedMembers}
            onExitSelection={() => setSelectedMembers([])}
            getRowId={(row) => String(row.userId)}
          />

          {/* Add member form */}
          <div className="space-y-2 pt-2">
            <Label>{t("settings.access.grantAccess")}</Label>
            {availableMembers.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {t("settings.access.allMembersHaveAccess")}
              </p>
            ) : (
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedNewUserId) {
                    setAccessError(t("settings.access.selectMemberError"));
                    return;
                  }
                  setAccessError(null);
                  addMember.mutate({
                    user_id: Number(selectedNewUserId),
                    level: selectedNewLevel,
                  });
                }}
              >
                <SearchableCombobox
                  items={availableMembers.map((member) => ({
                    value: String(member.user.id),
                    label: member.user.full_name?.trim() || member.user.email,
                  }))}
                  value={selectedNewUserId}
                  onValueChange={setSelectedNewUserId}
                  placeholder={t("settings.access.selectMember")}
                  emptyMessage={t("settings.access.noMembersFound")}
                  className="min-w-[200px]"
                />
                <Select
                  value={selectedNewLevel}
                  onValueChange={(value) => setSelectedNewLevel(value as ProjectPermissionLevel)}
                >
                  <SelectTrigger className="w-[130px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{t("settings.access.permissionRead")}</SelectItem>
                    <SelectItem value="write">{t("settings.access.permissionWrite")}</SelectItem>
                  </SelectContent>
                </Select>
                <Button type="submit" disabled={addMember.isPending || addAllMembers.isPending}>
                  {addMember.isPending ? t("settings.access.adding") : t("settings.access.add")}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() =>
                    addAllMembers.mutate({
                      user_ids: availableMembers.map((m) => m.user.id),
                      level: selectedNewLevel,
                    })
                  }
                  disabled={addMember.isPending || addAllMembers.isPending}
                >
                  {addAllMembers.isPending
                    ? t("settings.access.addingAll")
                    : t("settings.access.addAll", { count: availableMembers.length })}
                </Button>
              </form>
            )}
            {accessMessage ? <p className="text-primary text-sm">{accessMessage}</p> : null}
            {accessError ? <p className="text-destructive text-sm">{accessError}</p> : null}
          </div>
        </CardContent>
      </Card>
    </TabsContent>
  );
};
