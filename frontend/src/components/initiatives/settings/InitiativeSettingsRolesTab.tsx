import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable } from "@/components/ui/data-table";
import { TabsContent } from "@/components/ui/tabs";
import type { InitiativeRoleRead, PermissionKey } from "@/api/generated/initiativeAPI.schemas";
import {
  useInitiativeRoles,
  useUpdateRole,
  useDeleteRole,
  PERMISSION_LABELS,
  ALL_PERMISSION_KEYS,
} from "@/hooks/useInitiativeRoles";

interface InitiativeSettingsRolesTabProps {
  initiativeId: number;
  canManageMembers: boolean;
  onOpenCreateRoleDialog: () => void;
  onDeleteRole: (role: InitiativeRoleRead) => void;
  onRenameRole: (role: InitiativeRoleRead) => void;
}

export const InitiativeSettingsRolesTab = ({
  initiativeId,
  canManageMembers,
  onOpenCreateRoleDialog,
  onDeleteRole,
  onRenameRole,
}: InitiativeSettingsRolesTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  const rolesQuery = useInitiativeRoles(initiativeId || null);
  const updateRoleMutation = useUpdateRole(initiativeId);
  const deleteRoleMutation = useDeleteRole(initiativeId);

  const handleTogglePermission = useCallback(
    (role: InitiativeRoleRead, key: PermissionKey, enabled: boolean) => {
      // Don't allow editing PM role permissions
      if (role.name === "project_manager") {
        return;
      }
      const newPermissions = { ...role.permissions, [key]: enabled };
      updateRoleMutation.mutate({ roleId: role.id, data: { permissions: newPermissions } });
    },
    [updateRoleMutation]
  );

  const handleDeleteRole = useCallback(
    (role: InitiativeRoleRead) => {
      onDeleteRole(role);
    },
    [onDeleteRole]
  );

  const handleRenameRole = useCallback(
    (role: InitiativeRoleRead) => {
      onRenameRole(role);
    },
    [onRenameRole]
  );

  const roleColumns: ColumnDef<InitiativeRoleRead>[] = useMemo(
    () => [
      {
        accessorKey: "display_name",
        header: "Role",
        cell: ({ row }) => {
          const role = row.original;
          return (
            <div className="flex items-center gap-2">
              <span className="font-medium text-nowrap">{role.display_name}</span>
              {role.is_builtin && (
                <Badge variant="secondary" className="text-xs text-nowrap">
                  {t("settings.builtIn")}
                </Badge>
              )}
              {role.is_manager && (
                <Badge variant="outline" className="text-xs">
                  {t("settings.manager")}
                </Badge>
              )}
            </div>
          );
        },
      },
      ...ALL_PERMISSION_KEYS.map(
        (key): ColumnDef<InitiativeRoleRead> => ({
          id: key,
          header: () => <div className="text-center">{PERMISSION_LABELS[key]}</div>,
          cell: ({ row }) => {
            const role = row.original;
            const isPM = role.name === "project_manager";
            return (
              <div className="flex justify-center">
                {isPM ? (
                  <Lock className="text-muted-foreground h-4 w-4" />
                ) : (
                  <Checkbox
                    checked={role.permissions[key] ?? false}
                    onCheckedChange={(checked) =>
                      handleTogglePermission(role, key, Boolean(checked))
                    }
                    disabled={!canManageMembers || updateRoleMutation.isPending}
                  />
                )}
              </div>
            );
          },
        })
      ),
      {
        id: "member_count",
        header: () => <div className="text-center">{t("settings.membersCount")}</div>,
        cell: ({ row }) => (
          <div className="flex justify-center">
            <Badge variant="outline">{row.original.member_count}</Badge>
          </div>
        ),
      },
      ...(canManageMembers
        ? [
            {
              id: "actions",
              header: "",
              cell: ({ row }: { row: Row<InitiativeRoleRead> }) => {
                const role = row.original;
                if (role.is_builtin) {
                  return null;
                }
                return (
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRenameRole(role)}
                      disabled={updateRoleMutation.isPending}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteRole(role)}
                      disabled={deleteRoleMutation.isPending || role.member_count > 0}
                    >
                      <Trash2 className="text-destructive h-4 w-4" />
                    </Button>
                  </div>
                );
              },
            } as ColumnDef<InitiativeRoleRead>,
          ]
        : []),
    ],
    [
      t,
      canManageMembers,
      updateRoleMutation.isPending,
      deleteRoleMutation.isPending,
      handleTogglePermission,
      handleDeleteRole,
      handleRenameRole,
    ]
  );

  return (
    <TabsContent value="roles">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.rolesTitle")}</CardTitle>
          <CardDescription>{t("settings.rolesDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {rolesQuery.isLoading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("settings.loadingRoles")}
            </div>
          ) : rolesQuery.data ? (
            <DataTable columns={roleColumns} data={rolesQuery.data} />
          ) : null}

          {canManageMembers && (
            <Button variant="outline" onClick={onOpenCreateRoleDialog}>
              <Plus className="mr-2 h-4 w-4" />
              {t("settings.addCustomRole")}
            </Button>
          )}
        </CardContent>
      </Card>
    </TabsContent>
  );
};
