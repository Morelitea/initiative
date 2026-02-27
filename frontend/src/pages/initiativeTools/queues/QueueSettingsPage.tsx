import { useEffect, useMemo, useState } from "react";
import { Link, useRouter, useParams } from "@tanstack/react-router";
import { ColumnDef } from "@tanstack/react-table";
import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

import {
  useQueue,
  useUpdateQueue,
  useDeleteQueue,
  useSetQueuePermissions,
  useSetQueueRolePermissions,
} from "@/hooks/useQueues";
import { useInitiativeMembers } from "@/hooks/useInitiatives";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useGuildPath } from "@/lib/guildUrl";

import type {
  QueuePermissionLevel,
  QueueRolePermissionRead,
  QueuePermissionCreate,
  QueueRolePermissionCreate,
} from "@/api/generated/initiativeAPI.schemas";

// ── Types ──────────────────────────────────────────────────────────────────

interface UserPermissionRow {
  user_id: number;
  displayName: string;
  email: string;
  level: QueuePermissionLevel;
  isOwner: boolean;
}

// ── Component ──────────────────────────────────────────────────────────────

export const QueueSettingsPage = () => {
  const { t } = useTranslation(["queues", "common"]);
  const { queueId } = useParams({ strict: false }) as { queueId: string };
  const parsedId = Number(queueId);
  const router = useRouter();
  const gp = useGuildPath();

  // ── Fetch queue data ───────────────────────────────────────────────────

  const queueQuery = useQueue(Number.isFinite(parsedId) ? parsedId : null);
  const queue = queueQuery.data;

  const canManage =
    queue?.my_permission_level === "owner" || queue?.my_permission_level === "write";
  const isOwner = queue?.my_permission_level === "owner";

  // ── Details tab state ──────────────────────────────────────────────────

  const [nameValue, setNameValue] = useState("");
  const [descriptionValue, setDescriptionValue] = useState("");

  useEffect(() => {
    if (!queue) return;
    setNameValue(queue.name);
    setDescriptionValue(queue.description ?? "");
  }, [queue]);

  const updateQueue = useUpdateQueue(parsedId, {
    onSuccess: () => {
      toast.success(t("detailsUpdated"));
    },
  });

  const handleDetailsSave = () => {
    const trimmedName = nameValue.trim();
    if (!trimmedName) return;
    updateQueue.mutate({
      name: trimmedName,
      description: descriptionValue.trim() || null,
    });
  };

  // ── Access tab: role permissions (local state + bulk PUT) ──────────────

  const rolesQuery = useInitiativeRoles(queue?.initiative_id ?? null);
  const membersQuery = useInitiativeMembers(queue?.initiative_id ?? null);

  const [localRolePerms, setLocalRolePerms] = useState<QueueRolePermissionCreate[]>([]);
  const [localUserPerms, setLocalUserPerms] = useState<QueuePermissionCreate[]>([]);

  // Sync local state from server data
  useEffect(() => {
    if (!queue) return;
    setLocalRolePerms(
      queue.role_permissions.map((rp) => ({
        initiative_role_id: rp.initiative_role_id,
        level: rp.level ?? "read",
      }))
    );
    setLocalUserPerms(
      queue.permissions.map((p) => ({
        user_id: p.user_id,
        level: p.level ?? "read",
      }))
    );
  }, [queue]);

  const setRolePermissions = useSetQueueRolePermissions(parsedId, {
    onSuccess: () => {
      toast.success(t("permissionsUpdated"));
    },
  });

  const setUserPermissions = useSetQueuePermissions(parsedId, {
    onSuccess: () => {
      toast.success(t("permissionsUpdated"));
    },
  });

  // Role permission helpers
  const [selectedNewRoleId, setSelectedNewRoleId] = useState<string>("");
  const [selectedNewRoleLevel, setSelectedNewRoleLevel] = useState<"read" | "write">("read");

  const availableRoles = useMemo(() => {
    const roles = rolesQuery.data ?? [];
    const assignedRoleIds = new Set(localRolePerms.map((rp) => rp.initiative_role_id));
    return roles.filter((role) => !assignedRoleIds.has(role.id));
  }, [rolesQuery.data, localRolePerms]);

  const handleAddRolePermission = () => {
    if (!selectedNewRoleId) return;
    const newList: QueueRolePermissionCreate[] = [
      ...localRolePerms,
      { initiative_role_id: Number(selectedNewRoleId), level: selectedNewRoleLevel },
    ];
    setLocalRolePerms(newList);
    setRolePermissions.mutate(newList);
    setSelectedNewRoleId("");
    setSelectedNewRoleLevel("read");
  };

  const handleUpdateRoleLevel = (roleId: number, level: QueuePermissionLevel) => {
    const newList = localRolePerms.map((rp) =>
      rp.initiative_role_id === roleId ? { ...rp, level } : rp
    );
    setLocalRolePerms(newList);
    setRolePermissions.mutate(newList);
  };

  const handleRemoveRolePermission = (roleId: number) => {
    const newList = localRolePerms.filter((rp) => rp.initiative_role_id !== roleId);
    setLocalRolePerms(newList);
    setRolePermissions.mutate(newList);
  };

  // User permission helpers
  const [selectedNewUserId, setSelectedNewUserId] = useState<string>("");
  const [selectedNewUserLevel, setSelectedNewUserLevel] = useState<QueuePermissionLevel>("read");
  const [selectedMembers, setSelectedMembers] = useState<UserPermissionRow[]>([]);

  const availableMembers = useMemo(() => {
    const members = membersQuery.data ?? [];
    const assignedUserIds = new Set(localUserPerms.map((p) => p.user_id));
    return members.filter((m) => !assignedUserIds.has(m.id));
  }, [membersQuery.data, localUserPerms]);

  const handleAddUserPermission = () => {
    if (!selectedNewUserId) return;
    const newList: QueuePermissionCreate[] = [
      ...localUserPerms,
      { user_id: Number(selectedNewUserId), level: selectedNewUserLevel },
    ];
    setLocalUserPerms(newList);
    setUserPermissions.mutate(newList);
    setSelectedNewUserId("");
    setSelectedNewUserLevel("read");
  };

  const handleUpdateUserLevel = (userId: number, level: QueuePermissionLevel) => {
    const newList = localUserPerms.map((p) => (p.user_id === userId ? { ...p, level } : p));
    setLocalUserPerms(newList);
    setUserPermissions.mutate(newList);
  };

  const handleRemoveUserPermission = (userId: number) => {
    const newList = localUserPerms.filter((p) => p.user_id !== userId);
    setLocalUserPerms(newList);
    setUserPermissions.mutate(newList);
  };

  const handleBulkUpdateLevel = (level: QueuePermissionLevel) => {
    const selectedUserIds = new Set(
      selectedMembers.filter((m) => !m.isOwner).map((m) => m.user_id)
    );
    if (selectedUserIds.size === 0) return;
    const newList = localUserPerms.map((p) =>
      selectedUserIds.has(p.user_id) ? { ...p, level } : p
    );
    setLocalUserPerms(newList);
    setUserPermissions.mutate(newList);
    setSelectedMembers([]);
  };

  const handleBulkRemoveUsers = () => {
    const selectedUserIds = new Set(
      selectedMembers.filter((m) => !m.isOwner).map((m) => m.user_id)
    );
    if (selectedUserIds.size === 0) return;
    const newList = localUserPerms.filter((p) => !selectedUserIds.has(p.user_id));
    setLocalUserPerms(newList);
    setUserPermissions.mutate(newList);
    setSelectedMembers([]);
  };

  const handleAddAllMembers = () => {
    if (availableMembers.length === 0) return;
    const newEntries: QueuePermissionCreate[] = availableMembers.map((m) => ({
      user_id: m.id,
      level: selectedNewUserLevel,
    }));
    const newList = [...localUserPerms, ...newEntries];
    setLocalUserPerms(newList);
    setUserPermissions.mutate(newList);
  };

  // ── Resolve user display names ─────────────────────────────────────────

  const userPermissionRows: UserPermissionRow[] = useMemo(() => {
    const members = membersQuery.data ?? [];
    return localUserPerms.map((p) => {
      const member = members.find((m) => m.id === p.user_id);
      const displayName = member?.full_name?.trim() || member?.email || `User #${p.user_id}`;
      const email = member?.email || "";
      return {
        user_id: p.user_id,
        displayName,
        email,
        level: p.level ?? "read",
        isOwner: p.level === "owner",
      };
    });
  }, [localUserPerms, membersQuery.data]);

  // Build role permission display rows with display names
  const rolePermissionRows: (
    | QueueRolePermissionRead
    | { initiative_role_id: number; role_display_name: string; level: QueuePermissionLevel }
  )[] = useMemo(() => {
    const serverRows = queue?.role_permissions ?? [];
    return localRolePerms.map((lrp) => {
      const serverRow = serverRows.find((sr) => sr.initiative_role_id === lrp.initiative_role_id);
      if (serverRow) {
        return { ...serverRow, level: lrp.level ?? serverRow.level ?? "read" };
      }
      // For newly added roles that aren't yet in server data, resolve from roles query
      const role = (rolesQuery.data ?? []).find((r) => r.id === lrp.initiative_role_id);
      return {
        initiative_role_id: lrp.initiative_role_id,
        role_display_name: role?.display_name ?? `Role #${lrp.initiative_role_id}`,
        level: lrp.level ?? "read",
      };
    });
  }, [localRolePerms, queue?.role_permissions, rolesQuery.data]);

  // ── Advanced tab: delete ───────────────────────────────────────────────

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const deleteQueue = useDeleteQueue({
    onSuccess: () => {
      toast.success(t("queueDeleted"));
      setDeleteDialogOpen(false);
      router.navigate({ to: gp("/queues") });
    },
  });

  // ── Column definitions ─────────────────────────────────────────────────

  const roleColumns: ColumnDef<(typeof rolePermissionRows)[number]>[] = useMemo(
    () => [
      {
        accessorKey: "role_display_name",
        header: t("rolePermissions"),
        cell: ({ row }) => <span className="font-medium">{row.original.role_display_name}</span>,
      },
      {
        accessorKey: "level",
        header: t("permissionLevel"),
        cell: ({ row }) => (
          <Select
            value={row.original.level}
            onValueChange={(value) =>
              handleUpdateRoleLevel(row.original.initiative_role_id, value as QueuePermissionLevel)
            }
            disabled={setRolePermissions.isPending}
          >
            <SelectTrigger className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="read">{t("permissionRead")}</SelectItem>
              <SelectItem value="write">{t("permissionWrite")}</SelectItem>
            </SelectContent>
          </Select>
        ),
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("common:actions")}</div>,
        cell: ({ row }) => (
          <div className="text-right">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => handleRemoveRolePermission(row.original.initiative_role_id)}
              disabled={setRolePermissions.isPending}
            >
              {t("removeRole")}
            </Button>
          </div>
        ),
      },
    ],
    [t, setRolePermissions.isPending] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const userColumns: ColumnDef<UserPermissionRow>[] = useMemo(
    () => [
      {
        accessorKey: "displayName",
        header: t("addMember"),
        cell: ({ row }) => (
          <div>
            <span className="font-medium">{row.original.displayName}</span>
            {row.original.email && (
              <span className="text-muted-foreground ml-2 text-sm">{row.original.email}</span>
            )}
          </div>
        ),
      },
      {
        accessorKey: "level",
        header: t("permissionLevel"),
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <span className="text-muted-foreground">{t("permissionOwner")}</span>;
          }
          return (
            <Select
              value={row.original.level}
              onValueChange={(value) =>
                handleUpdateUserLevel(row.original.user_id, value as QueuePermissionLevel)
              }
              disabled={setUserPermissions.isPending}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("permissionRead")}</SelectItem>
                <SelectItem value="write">{t("permissionWrite")}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("common:actions")}</div>,
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
                onClick={() => handleRemoveUserPermission(row.original.user_id)}
                disabled={setUserPermissions.isPending}
              >
                {t("removeMember")}
              </Button>
            </div>
          );
        },
      },
    ],
    [t, setUserPermissions.isPending] // eslint-disable-line react-hooks/exhaustive-deps
  );

  // ── Early returns ──────────────────────────────────────────────────────

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (queueQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("loadingQueue")}
      </div>
    );
  }

  if (queueQuery.isError || !queue) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumbs */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/queues")}>{t("title")}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/queues/${queue.id}`)}>{queue.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Header */}
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">{t("settings")}</h1>
        <p className="text-muted-foreground text-sm">{t("settingsDescription")}</p>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("details")}</TabsTrigger>
          {canManage && <TabsTrigger value="access">{t("access")}</TabsTrigger>}
          <TabsTrigger value="advanced">{t("advanced")}</TabsTrigger>
        </TabsList>

        {/* ── Details tab ─────────────────────────────────────────── */}
        <TabsContent value="details" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("details")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="queue-name">{t("name")}</Label>
                <Input
                  id="queue-name"
                  value={nameValue}
                  onChange={(e) => setNameValue(e.target.value)}
                  placeholder={t("namePlaceholder")}
                  disabled={!canManage}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="queue-description">{t("description")}</Label>
                <Textarea
                  id="queue-description"
                  value={descriptionValue}
                  onChange={(e) => setDescriptionValue(e.target.value)}
                  placeholder={t("descriptionPlaceholder")}
                  disabled={!canManage}
                  rows={3}
                />
              </div>
              {canManage && (
                <Button
                  onClick={handleDetailsSave}
                  disabled={updateQueue.isPending || !nameValue.trim()}
                >
                  {updateQueue.isPending ? t("saving") : t("common:save")}
                </Button>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Access tab ──────────────────────────────────────────── */}
        {canManage && (
          <TabsContent value="access" className="space-y-6">
            {/* Role permissions */}
            <Card>
              <CardHeader>
                <CardTitle>{t("rolePermissions")}</CardTitle>
                <CardDescription>{t("rolePermissionsDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {rolePermissionRows.length > 0 ? (
                  <DataTable
                    columns={roleColumns}
                    data={rolePermissionRows}
                    getRowId={(row) => String(row.initiative_role_id)}
                  />
                ) : (
                  <p className="text-muted-foreground text-sm">{t("noRolePermissions")}</p>
                )}

                {/* Add role form */}
                <div className="space-y-2 pt-2">
                  <Label>{t("addRole")}</Label>
                  {availableRoles.length === 0 ? (
                    <p className="text-muted-foreground text-sm">{t("noRolePermissions")}</p>
                  ) : (
                    <div className="flex flex-wrap items-end gap-3">
                      <Select value={selectedNewRoleId} onValueChange={setSelectedNewRoleId}>
                        <SelectTrigger className="min-w-[200px]">
                          <SelectValue placeholder={t("selectRole")} />
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
                        onValueChange={(v) => setSelectedNewRoleLevel(v as "read" | "write")}
                      >
                        <SelectTrigger className="w-[130px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="read">{t("permissionRead")}</SelectItem>
                          <SelectItem value="write">{t("permissionWrite")}</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        onClick={handleAddRolePermission}
                        disabled={!selectedNewRoleId || setRolePermissions.isPending}
                      >
                        {setRolePermissions.isPending ? t("adding") : t("addRole")}
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* User permissions */}
            <Card>
              <CardHeader>
                <CardTitle>{t("userPermissions")}</CardTitle>
                <CardDescription>{t("userPermissionsDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Bulk action bar */}
                {selectedMembers.length > 0 && (
                  <div className="bg-muted flex items-center gap-3 rounded-md p-3">
                    <span className="text-sm font-medium">
                      {t("selectedCount", { count: selectedMembers.length })}
                    </span>
                    <Select
                      onValueChange={(level) =>
                        handleBulkUpdateLevel(level as QueuePermissionLevel)
                      }
                      disabled={setUserPermissions.isPending}
                    >
                      <SelectTrigger className="w-[150px]">
                        <SelectValue placeholder={t("changeAccess")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("permissionRead")}</SelectItem>
                        <SelectItem value="write">{t("permissionWrite")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      onClick={handleBulkRemoveUsers}
                      disabled={setUserPermissions.isPending}
                    >
                      {setUserPermissions.isPending ? t("removing") : t("removeMember")}
                    </Button>
                  </div>
                )}

                <DataTable
                  columns={userColumns}
                  data={userPermissionRows}
                  getRowId={(row) => String(row.user_id)}
                  enableFilterInput
                  filterInputColumnKey="displayName"
                  filterInputPlaceholder={t("filterByName")}
                  enableRowSelection
                  onRowSelectionChange={setSelectedMembers}
                  onExitSelection={() => setSelectedMembers([])}
                  enablePagination
                />

                {/* Add member form */}
                <div className="space-y-2 pt-2">
                  <Label>{t("addMember")}</Label>
                  {availableMembers.length === 0 ? (
                    <p className="text-muted-foreground text-sm">{t("noUserPermissions")}</p>
                  ) : (
                    <div className="flex flex-wrap items-end gap-3">
                      <SearchableCombobox
                        items={availableMembers.map((m) => ({
                          value: String(m.id),
                          label: m.full_name?.trim() || m.email,
                        }))}
                        value={selectedNewUserId}
                        onValueChange={setSelectedNewUserId}
                        placeholder={t("selectMember")}
                        emptyMessage={t("selectMember")}
                        className="min-w-[200px]"
                      />
                      <Select
                        value={selectedNewUserLevel}
                        onValueChange={(v) => setSelectedNewUserLevel(v as QueuePermissionLevel)}
                      >
                        <SelectTrigger className="w-[130px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="read">{t("permissionRead")}</SelectItem>
                          <SelectItem value="write">{t("permissionWrite")}</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        onClick={handleAddUserPermission}
                        disabled={!selectedNewUserId || setUserPermissions.isPending}
                      >
                        {setUserPermissions.isPending ? t("adding") : t("addMember")}
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={handleAddAllMembers}
                        disabled={setUserPermissions.isPending}
                      >
                        {setUserPermissions.isPending
                          ? t("adding")
                          : t("addAllCount", { count: availableMembers.length })}
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* ── Advanced tab ────────────────────────────────────────── */}
        <TabsContent value="advanced" className="space-y-6">
          {isOwner && (
            <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
              <CardHeader>
                <CardTitle>{t("dangerZone")}</CardTitle>
                <CardDescription>{t("dangerZoneDescription")}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setDeleteDialogOpen(true)}
                  disabled={!isOwner}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t("deleteQueue")}
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t("deleteQueue")}
        description={t("deleteQueueConfirm")}
        confirmLabel={t("deleteQueue")}
        cancelLabel={t("common:cancel")}
        onConfirm={() => deleteQueue.mutate(parsedId)}
        isLoading={deleteQueue.isPending}
        destructive
      />
    </div>
  );
};
