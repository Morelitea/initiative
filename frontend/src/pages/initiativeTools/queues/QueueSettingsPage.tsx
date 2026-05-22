import { Link, useParams, useRouter } from "@tanstack/react-router";
import { Loader2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  QueuePermissionCreate,
  QueueRolePermissionCreate,
} from "@/api/generated/initiativeAPI.schemas";
import type { AccessLevel, RolePermissionRow } from "@/components/access/RolePermissionsCard";
import { RolePermissionsCard } from "@/components/access/RolePermissionsCard";
import type { UserPermissionRow } from "@/components/access/UserPermissionsCard";
import { UserPermissionsCard } from "@/components/access/UserPermissionsCard";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiativeMembers } from "@/hooks/useInitiatives";
import {
  useDeleteQueue,
  useQueue,
  useSetQueuePermissions,
  useSetQueueRolePermissions,
  useUpdateQueue,
} from "@/hooks/useQueues";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";

export const QueueSettingsPage = () => {
  const { t } = useTranslation(["queues", "common"]);
  const { queueId } = useParams({ strict: false }) as { queueId: string };
  const parsedId = Number(queueId);
  const router = useRouter();
  const gp = useGuildPath();

  const queueQuery = useQueue(Number.isFinite(parsedId) ? parsedId : null);
  const queue = queueQuery.data;

  const canManage =
    queue?.my_permission_level === "owner" || queue?.my_permission_level === "write";
  const isOwner = queue?.my_permission_level === "owner";

  // ── Details ────────────────────────────────────────────────────────────

  const [nameValue, setNameValue] = useState("");
  const [descriptionValue, setDescriptionValue] = useState("");

  useEffect(() => {
    if (!queue) return;
    setNameValue(queue.name);
    setDescriptionValue(queue.description ?? "");
  }, [queue]);

  const updateQueue = useUpdateQueue(parsedId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  const handleDetailsSave = () => {
    const trimmedName = nameValue.trim();
    if (!trimmedName) return;
    updateQueue.mutate({ name: trimmedName, description: descriptionValue.trim() || null });
  };

  // ── Access (local state + bulk PUT) ────────────────────────────────────

  const rolesQuery = useInitiativeRoles(queue?.initiative_id ?? null);
  const membersQuery = useInitiativeMembers(queue?.initiative_id ?? null);

  const [localRolePerms, setLocalRolePerms] = useState<QueueRolePermissionCreate[]>([]);
  const [localUserPerms, setLocalUserPerms] = useState<QueuePermissionCreate[]>([]);

  useEffect(() => {
    if (!queue) return;
    setLocalRolePerms(
      queue.role_permissions.map((rp) => ({
        initiative_role_id: rp.initiative_role_id,
        level: rp.level ?? "read",
      }))
    );
    setLocalUserPerms(
      queue.permissions.map((p) => ({ user_id: p.user_id, level: p.level ?? "read" }))
    );
  }, [queue]);

  const setRolePermissions = useSetQueueRolePermissions(parsedId, {
    onSuccess: () => toast.success(t("permissionsUpdated")),
  });
  const setUserPermissions = useSetQueuePermissions(parsedId, {
    onSuccess: () => toast.success(t("permissionsUpdated")),
  });

  const availableRoles = useMemo(() => {
    const roles = rolesQuery.data ?? [];
    const assigned = new Set(localRolePerms.map((rp) => rp.initiative_role_id));
    return roles.filter((role) => !assigned.has(role.id));
  }, [rolesQuery.data, localRolePerms]);

  const availableMembers = useMemo(() => {
    const members = membersQuery.data ?? [];
    const assigned = new Set(localUserPerms.map((p) => p.user_id));
    return members.filter((m) => !assigned.has(m.id));
  }, [membersQuery.data, localUserPerms]);

  const rolePermissionRows: RolePermissionRow[] = useMemo(() => {
    const serverRows = queue?.role_permissions ?? [];
    return localRolePerms.map((lrp) => {
      const serverRow = serverRows.find((sr) => sr.initiative_role_id === lrp.initiative_role_id);
      const role = (rolesQuery.data ?? []).find((r) => r.id === lrp.initiative_role_id);
      return {
        initiative_role_id: lrp.initiative_role_id,
        role_display_name:
          serverRow?.role_display_name ?? role?.display_name ?? `Role #${lrp.initiative_role_id}`,
        level: (lrp.level ?? "read") as AccessLevel,
      };
    });
  }, [localRolePerms, queue?.role_permissions, rolesQuery.data]);

  const userPermissionRows: UserPermissionRow[] = useMemo(() => {
    const members = membersQuery.data ?? [];
    return localUserPerms.map((p) => {
      const member = members.find((m) => m.id === p.user_id);
      return {
        user_id: p.user_id,
        displayName: member?.full_name?.trim() || member?.email || `User #${p.user_id}`,
        email: member?.email || "",
        level: (p.level ?? "read") as AccessLevel,
        isOwner: p.level === "owner",
      };
    });
  }, [localUserPerms, membersQuery.data]);

  const commitRoles = (next: QueueRolePermissionCreate[]) => {
    setLocalRolePerms(next);
    setRolePermissions.mutate(next);
  };
  const handleAddRole = (roleId: number, level: "read" | "write") =>
    commitRoles([...localRolePerms, { initiative_role_id: roleId, level }]);
  const handleUpdateRoleLevel = (roleId: number, level: "read" | "write") =>
    commitRoles(
      localRolePerms.map((rp) => (rp.initiative_role_id === roleId ? { ...rp, level } : rp))
    );
  const handleRemoveRole = (roleId: number) =>
    commitRoles(localRolePerms.filter((rp) => rp.initiative_role_id !== roleId));

  const commitUsers = (next: QueuePermissionCreate[]) => {
    setLocalUserPerms(next);
    setUserPermissions.mutate(next);
  };
  const handleAddUser = (userId: number, level: "read" | "write") =>
    commitUsers([...localUserPerms, { user_id: userId, level }]);
  const handleUpdateUserLevel = (userId: number, level: "read" | "write") =>
    commitUsers(localUserPerms.map((p) => (p.user_id === userId ? { ...p, level } : p)));
  const handleRemoveUser = (userId: number) =>
    commitUsers(localUserPerms.filter((p) => p.user_id !== userId));
  const handleBulkUpdate = (userIds: number[], level: "read" | "write") => {
    const ids = new Set(userIds);
    commitUsers(localUserPerms.map((p) => (ids.has(p.user_id) ? { ...p, level } : p)));
  };
  const handleBulkRemove = (userIds: number[]) => {
    const ids = new Set(userIds);
    commitUsers(localUserPerms.filter((p) => !ids.has(p.user_id)));
  };
  const handleAddAll = (level: "read" | "write") =>
    commitUsers([...localUserPerms, ...availableMembers.map((m) => ({ user_id: m.id, level }))]);

  // ── Delete ─────────────────────────────────────────────────────────────

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const deleteQueue = useDeleteQueue({
    onSuccess: () => {
      toast.success(t("queueDeleted"));
      setDeleteDialogOpen(false);
      router.navigate({ to: gp("/queues") });
    },
  });

  const accessBusy = setRolePermissions.isPending || setUserPermissions.isPending;

  // ── Early returns ──────────────────────────────────────────────────────

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (queueQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
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

      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("settings")}</h1>
        <p className="text-muted-foreground text-sm">{t("settingsDescription")}</p>
      </div>

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
            <RolePermissionsCard
              rolePermissions={rolePermissionRows}
              availableRoles={availableRoles}
              busy={accessBusy}
              loadingRoles={rolesQuery.isLoading}
              onAdd={handleAddRole}
              onUpdateLevel={handleUpdateRoleLevel}
              onRemove={handleRemoveRole}
            />
            <UserPermissionsCard
              userPermissions={userPermissionRows}
              availableMembers={availableMembers}
              busy={accessBusy}
              onAdd={handleAddUser}
              onUpdateLevel={handleUpdateUserLevel}
              onRemove={handleRemoveUser}
              onAddAll={handleAddAll}
              onBulkUpdate={handleBulkUpdate}
              onBulkRemove={handleBulkRemove}
            />
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
