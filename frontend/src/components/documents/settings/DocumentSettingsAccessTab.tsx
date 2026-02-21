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
import { toast } from "sonner";
import {
  useAddDocumentMember,
  useUpdateDocumentMember,
  useRemoveDocumentMember,
  useAddDocumentMembersBulk,
  useRemoveDocumentMembersBulk,
  useAddDocumentRolePermission,
  useUpdateDocumentRolePermission,
  useRemoveDocumentRolePermission,
} from "@/hooks/useDocuments";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import type {
  DocumentPermissionLevel,
  DocumentRead,
  DocumentRolePermissionRead,
} from "@/api/generated/initiativeAPI.schemas";

export interface PermissionRow {
  userId: number;
  displayName: string;
  email: string;
  level: DocumentPermissionLevel;
  isOwner: boolean;
}

interface DocumentSettingsAccessTabProps {
  document: DocumentRead;
  documentId: number;
}

export const DocumentSettingsAccessTab = ({
  document,
  documentId,
}: DocumentSettingsAccessTabProps) => {
  const { t } = useTranslation(["documents", "common"]);

  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [selectedNewUserId, setSelectedNewUserId] = useState<string>("");
  const [selectedNewLevel, setSelectedNewLevel] = useState<DocumentPermissionLevel>("read");
  const [selectedMembers, setSelectedMembers] = useState<PermissionRow[]>([]);
  const [selectedNewRoleId, setSelectedNewRoleId] = useState<string>("");
  const [selectedNewRoleLevel, setSelectedNewRoleLevel] = useState<"read" | "write">("read");

  const rolesQuery = useInitiativeRoles(document.initiative_id ?? null);

  // ── Mutation hooks ──────────────────────────────────────────

  const addMember = useAddDocumentMember(documentId, {
    onSuccess: () => {
      setAccessMessage(t("settings.accessGranted"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.grantAccessError"));
    },
  });

  const updateMemberLevel = useUpdateDocumentMember(documentId, {
    onSuccess: () => {
      setAccessMessage(t("settings.accessUpdated"));
      setAccessError(null);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.updateAccessError"));
    },
  });

  const removeMember = useRemoveDocumentMember(documentId, {
    onSuccess: () => {
      setAccessMessage(t("settings.accessRemoved"));
      setAccessError(null);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.removeAccessError"));
    },
  });

  const addAllMembers = useAddDocumentMembersBulk(documentId, {
    onSuccess: () => {
      setAccessMessage(t("settings.accessGranted"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.grantAccessError"));
    },
  });

  const bulkUpdateLevel = useAddDocumentMembersBulk(documentId, {
    onSuccess: () => {
      setAccessMessage(t("settings.accessUpdated"));
      setAccessError(null);
      setSelectedMembers([]);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.updateAccessError"));
    },
  });

  const bulkRemoveMembers = useRemoveDocumentMembersBulk(documentId, {
    onSuccess: () => {
      setAccessMessage(t("settings.accessRemoved"));
      setAccessError(null);
      setSelectedMembers([]);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.removeAccessError"));
    },
  });

  // Role permission mutations
  const addRolePermission = useAddDocumentRolePermission(documentId, {
    onSuccess: () => {
      toast.success(t("settings.roleAccessGranted"));
      setSelectedNewRoleId("");
      setSelectedNewRoleLevel("read");
    },
    onError: () => {
      toast.error(t("settings.grantRoleAccessError"));
    },
  });

  const updateRolePermission = useUpdateDocumentRolePermission(documentId, {
    onSuccess: () => {
      toast.success(t("settings.roleAccessUpdated"));
    },
    onError: () => {
      toast.error(t("settings.updateRoleAccessError"));
    },
  });

  const removeRolePermission = useRemoveDocumentRolePermission(documentId, {
    onSuccess: () => {
      toast.success(t("settings.roleAccessRemoved"));
    },
    onError: () => {
      toast.error(t("settings.removeRoleAccessError"));
    },
  });

  // ── Computed values ──────────────────────────────────────────

  // Initiative members for the permission table
  const initiativeMembers = useMemo(
    () => document.initiative?.members ?? [],
    [document.initiative?.members]
  );

  // Build permission rows with user info
  const permissionRows: PermissionRow[] = useMemo(() => {
    const permissions = document.permissions ?? [];
    return permissions.map((permission) => {
      const member = initiativeMembers.find((entry) => entry.user?.id === permission.user_id);
      const displayName =
        member?.user?.full_name?.trim() ||
        member?.user?.email ||
        t("bulk.userFallback", { id: permission.user_id });
      const email = member?.user?.email || "";
      return {
        userId: permission.user_id,
        displayName,
        email,
        level: permission.level,
        isOwner: permission.level === "owner",
      };
    });
  }, [document.permissions, initiativeMembers, t]);

  // Roles not yet assigned to the document
  const availableRoles = useMemo(() => {
    const roles = rolesQuery.data ?? [];
    const assignedRoleIds = new Set(
      (document.role_permissions ?? []).map((rp) => rp.initiative_role_id)
    );
    return roles.filter((role) => !assignedRoleIds.has(role.id));
  }, [rolesQuery.data, document.role_permissions]);

  // Initiative members who don't have permissions yet
  const availableMembers = useMemo(
    () =>
      initiativeMembers.filter(
        (member) =>
          member.user &&
          !(document.permissions ?? []).some((permission) => permission.user_id === member.user.id)
      ),
    [initiativeMembers, document.permissions]
  );

  // ── Column definitions ──────────────────────────────────────────

  // Column definitions for the permissions table
  const permissionColumns: ColumnDef<PermissionRow>[] = useMemo(
    () => [
      {
        accessorKey: "displayName",
        header: t("settings.columnName"),
        cell: ({ row }) => <span className="font-medium">{row.original.displayName}</span>,
      },
      {
        accessorKey: "email",
        header: t("settings.columnEmail"),
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.email}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.columnAccess"),
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <span className="text-muted-foreground">{t("settings.permissionOwner")}</span>;
          }
          return (
            <Select
              value={row.original.level}
              onValueChange={(value) => {
                setAccessMessage(null);
                setAccessError(null);
                updateMemberLevel.mutate({
                  userId: row.original.userId,
                  level: value as DocumentPermissionLevel,
                });
              }}
              disabled={updateMemberLevel.isPending}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("settings.permissionRead")}</SelectItem>
                <SelectItem value="write">{t("settings.permissionWrite")}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.columnActions")}</div>,
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
                {t("settings.remove")}
              </Button>
            </div>
          );
        },
      },
    ],
    [t, updateMemberLevel, removeMember]
  );

  // Column definitions for the role permissions table
  const rolePermissionColumns: ColumnDef<DocumentRolePermissionRead>[] = useMemo(
    () => [
      {
        accessorKey: "role_display_name",
        header: t("settings.columnRoleName"),
        cell: ({ row }) => <span className="font-medium">{row.original.role_display_name}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.columnAccessLevel"),
        cell: ({ row }) => (
          <Select
            value={row.original.level}
            onValueChange={(value) => {
              updateRolePermission.mutate({
                roleId: row.original.initiative_role_id,
                level: value as "read" | "write",
              });
            }}
            disabled={updateRolePermission.isPending}
          >
            <SelectTrigger className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="read">{t("settings.canView")}</SelectItem>
              <SelectItem value="write">{t("settings.canEdit")}</SelectItem>
            </SelectContent>
          </Select>
        ),
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.columnActions")}</div>,
        cell: ({ row }) => (
          <div className="text-right">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => removeRolePermission.mutate(row.original.initiative_role_id)}
              disabled={removeRolePermission.isPending}
            >
              {t("settings.remove")}
            </Button>
          </div>
        ),
      },
    ],
    [t, updateRolePermission, removeRolePermission]
  );

  return (
    <TabsContent value="access" className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.roleAccessTitle")}</CardTitle>
          <CardDescription>{t("settings.roleAccessDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {(document.role_permissions ?? []).length > 0 ? (
            <DataTable
              columns={rolePermissionColumns}
              data={document.role_permissions ?? []}
              getRowId={(row) => String(row.initiative_role_id)}
            />
          ) : (
            <p className="text-muted-foreground text-sm">{t("settings.noRoleAccess")}</p>
          )}

          {/* Add role form */}
          <div className="space-y-2 pt-2">
            <Label>{t("settings.addRole")}</Label>
            {availableRoles.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("settings.allRolesAssigned")}</p>
            ) : (
              <div className="flex flex-wrap items-end gap-3">
                <Select value={selectedNewRoleId} onValueChange={setSelectedNewRoleId}>
                  <SelectTrigger className="min-w-[200px]">
                    <SelectValue placeholder={t("settings.selectRole")} />
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
                    <SelectItem value="read">{t("settings.canView")}</SelectItem>
                    <SelectItem value="write">{t("settings.canEdit")}</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  onClick={() => {
                    if (!selectedNewRoleId) {
                      return;
                    }
                    addRolePermission.mutate({
                      roleId: Number(selectedNewRoleId),
                      level: selectedNewRoleLevel,
                    });
                  }}
                  disabled={!selectedNewRoleId || addRolePermission.isPending}
                >
                  {addRolePermission.isPending ? t("settings.adding") : t("settings.add")}
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.individualAccessTitle")}</CardTitle>
          <CardDescription>{t("settings.individualAccessDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Bulk action bar */}
          {selectedMembers.length > 0 && (
            <div className="bg-muted flex items-center gap-3 rounded-md p-3">
              <span className="text-sm font-medium">
                {t("settings.selectedCount", { count: selectedMembers.length })}
              </span>
              <Select
                onValueChange={(level) => {
                  const userIds = selectedMembers.filter((m) => !m.isOwner).map((m) => m.userId);
                  if (userIds.length > 0) {
                    bulkUpdateLevel.mutate({
                      user_ids: userIds,
                      level: level as DocumentPermissionLevel,
                    });
                  }
                }}
                disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
              >
                <SelectTrigger className="w-[150px]">
                  <SelectValue placeholder={t("settings.changeAccess")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">{t("settings.permissionRead")}</SelectItem>
                  <SelectItem value="write">{t("settings.permissionWrite")}</SelectItem>
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
                {bulkRemoveMembers.isPending ? t("settings.removing") : t("settings.remove")}
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
            filterInputPlaceholder={t("settings.filterByName")}
            enableRowSelection
            onRowSelectionChange={setSelectedMembers}
            onExitSelection={() => setSelectedMembers([])}
            getRowId={(row) => String(row.userId)}
          />

          {/* Add member form */}
          <div className="space-y-2 pt-2">
            <Label>{t("settings.grantAccess")}</Label>
            {availableMembers.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("settings.allMembersHaveAccess")}</p>
            ) : (
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedNewUserId) {
                    setAccessError(t("settings.selectMember"));
                    return;
                  }
                  setAccessError(null);
                  addMember.mutate({
                    userId: Number(selectedNewUserId),
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
                  placeholder={t("settings.selectMember")}
                  emptyMessage={t("settings.noMembersFound")}
                  className="min-w-[200px]"
                />
                <Select
                  value={selectedNewLevel}
                  onValueChange={(value) => setSelectedNewLevel(value as DocumentPermissionLevel)}
                >
                  <SelectTrigger className="w-[130px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{t("settings.permissionRead")}</SelectItem>
                    <SelectItem value="write">{t("settings.permissionWrite")}</SelectItem>
                  </SelectContent>
                </Select>
                <Button type="submit" disabled={addMember.isPending || addAllMembers.isPending}>
                  {addMember.isPending ? t("settings.adding") : t("settings.add")}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() =>
                    addAllMembers.mutate({
                      user_ids: availableMembers.map((member) => member.user.id),
                      level: selectedNewLevel,
                    })
                  }
                  disabled={addMember.isPending || addAllMembers.isPending}
                >
                  {addAllMembers.isPending
                    ? t("settings.adding")
                    : t("settings.addAllCount", { count: availableMembers.length })}
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
