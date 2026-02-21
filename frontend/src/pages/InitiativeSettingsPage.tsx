import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useParams, useRouter } from "@tanstack/react-router";
import { Trans, useTranslation } from "react-i18next";
import { useGuildPath } from "@/lib/guildUrl";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { Loader2, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
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
import { Checkbox } from "@/components/ui/checkbox";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { DataTable } from "@/components/ui/data-table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/useAuth";
import {
  useInitiatives,
  useUpdateInitiative,
  useDeleteInitiative,
  useAddInitiativeMember,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import { useUsers } from "@/hooks/useUsers";
import { useGuilds } from "@/hooks/useGuilds";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import {
  useInitiativeRoles,
  useCreateRole,
  useUpdateRole,
  useDeleteRole,
  PERMISSION_LABELS,
  ALL_PERMISSION_KEYS,
} from "@/hooks/useInitiativeRoles";
import type {
  InitiativeMemberRead,
  InitiativeRoleRead,
  PermissionKey,
} from "@/api/generated/initiativeAPI.schemas";

const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const InitiativeSettingsPage = () => {
  const { initiativeId: initiativeIdParam } = useParams({ strict: false }) as {
    initiativeId: string;
  };
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const router = useRouter();

  const { t } = useTranslation(["initiatives", "common"]);
  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const gp = useGuildPath();

  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);
  const adminLabel = getRoleLabel("admin", roleLabels);

  const initiativesQuery = useInitiatives({ enabled: hasValidInitiativeId });

  const initiative =
    hasValidInitiativeId && initiativesQuery.data
      ? (initiativesQuery.data.find((item) => item.id === initiativeId) ?? null)
      : null;

  // Fetch roles for this initiative
  const rolesQuery = useInitiativeRoles(initiativeId || null);
  const createRoleMutation = useCreateRole(initiativeId);
  const updateRoleMutation = useUpdateRole(initiativeId);
  const deleteRoleMutation = useDeleteRole(initiativeId);

  const isGuildAdmin = activeGuild?.role === "admin";
  const initiativeMembership = initiative?.members.find((member) => member.user.id === user?.id);
  const isInitiativeManager =
    initiativeMembership?.is_manager || initiativeMembership?.role === "project_manager";
  const canManageMembers = Boolean(isGuildAdmin || isInitiativeManager);
  const canDeleteInitiative = Boolean(isGuildAdmin);

  const [name, setName] = useState(initiative?.name ?? "");
  const [description, setDescription] = useState(initiative?.description ?? "");
  const [color, setColor] = useState(initiative?.color ?? DEFAULT_INITIATIVE_COLOR);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  // New role dialog state
  const [showNewRoleDialog, setShowNewRoleDialog] = useState(false);
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDisplayName, setNewRoleDisplayName] = useState("");
  const roleNameTouchedRef = useRef(false);

  // Delete role confirmation
  const [roleToDelete, setRoleToDelete] = useState<InitiativeRoleRead | null>(null);

  // Rename role dialog
  const [roleToRename, setRoleToRename] = useState<InitiativeRoleRead | null>(null);
  const [renameDisplayName, setRenameDisplayName] = useState("");

  // Remove member confirmation
  const [memberToRemove, setMemberToRemove] = useState<InitiativeMemberRead | null>(null);

  useEffect(() => {
    if (initiative) {
      setName(initiative.name);
      setDescription(initiative.description ?? "");
      setColor(initiative.color ?? DEFAULT_INITIATIVE_COLOR);
    }
  }, [initiative]);

  // Set default role_id when roles load
  useEffect(() => {
    if (rolesQuery.data && !selectedRoleId) {
      const memberRole = rolesQuery.data.find((r) => r.name === "member");
      if (memberRole) {
        setSelectedRoleId(String(memberRole.id));
      }
    }
  }, [rolesQuery.data, selectedRoleId]);

  const usersQuery = useUsers({
    enabled: canManageMembers && !!activeGuild?.id,
    staleTime: 5 * 60 * 1000,
  });

  const availableUsers = useMemo(() => {
    if (!usersQuery.data || !initiative) {
      return [];
    }
    const existingIds = new Set(initiative.members.map((member) => member.user.id));
    return usersQuery.data.filter((candidate) => !existingIds.has(candidate.id));
  }, [usersQuery.data, initiative]);

  const updateInitiative = useUpdateInitiative({
    onSuccess: () => {
      toast.success(t("settings.updated"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.updateError");
      toast.error(message);
    },
  });

  const deleteInitiative = useDeleteInitiative({
    onSuccess: () => {
      toast.success(t("settings.deleted"));
      router.navigate({ to: gp("/initiatives") });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.deleteError");
      toast.error(message);
    },
  });

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

  const handleSaveDetails = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("settings.nameRequired"));
      return;
    }
    updateInitiative.mutate({
      initiativeId,
      data: {
        name: trimmedName,
        description: description.trim() || undefined,
        color,
      },
    });
  };

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

  const handleDeleteInitiative = () => {
    if (initiative?.is_default) {
      return;
    }
    setDeleteConfirmText("");
    setShowDeleteConfirm(true);
  };

  const confirmDeleteInitiative = () => {
    deleteInitiative.mutate(initiativeId);
    setShowDeleteConfirm(false);
    setDeleteConfirmText("");
  };

  const handleCreateRole = () => {
    const name = newRoleName.trim().toLowerCase().replace(/\s+/g, "_");
    const displayName = newRoleDisplayName.trim();
    if (!name || !displayName) {
      toast.error(t("settings.roleNameRequired"));
      return;
    }
    createRoleMutation.mutate(
      { name, display_name: displayName },
      {
        onSuccess: () => {
          setShowNewRoleDialog(false);
          setNewRoleName("");
          setNewRoleDisplayName("");
          roleNameTouchedRef.current = false;
        },
      }
    );
  };

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

  const handleDeleteRole = useCallback((role: InitiativeRoleRead) => {
    setRoleToDelete(role);
  }, []);

  const confirmDeleteRole = () => {
    if (roleToDelete) {
      deleteRoleMutation.mutate(roleToDelete.id, {
        onSuccess: () => setRoleToDelete(null),
      });
    }
  };

  const handleRenameRole = useCallback((role: InitiativeRoleRead) => {
    setRoleToRename(role);
    setRenameDisplayName(role.display_name);
  }, []);

  const confirmRenameRole = () => {
    if (roleToRename && renameDisplayName.trim()) {
      updateRoleMutation.mutate(
        { roleId: roleToRename.id, data: { display_name: renameDisplayName.trim() } },
        { onSuccess: () => setRoleToRename(null) }
      );
    }
  };

  const canConfirmDelete = deleteConfirmText === initiative?.name;

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
          return <span className="font-medium">{member.user.full_name?.trim() || "—"}</span>;
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
          if (!canManageMembers || !rolesQuery.data) {
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
                {rolesQuery.data.map((role) => (
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
              onClick={() => setMemberToRemove(member)}
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
    rolesQuery.data,
    removeMember,
    updateMemberRole,
    projectManagerLabel,
    memberLabel,
    initiativeId,
  ]);

  if (!hasValidInitiativeId) {
    return <Navigate to={gp("/initiatives")} replace />;
  }

  if (initiativesQuery.isLoading || !initiativesQuery.data) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("settings.loadingInitiative")}
      </div>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp("/initiatives")}>{t("settings.backToInitiatives")}</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <h1 className="text-3xl font-semibold tracking-tight">{t("settings.notFound")}</h1>
          <p className="text-muted-foreground">{t("settings.notFoundDescription")}</p>
        </div>
      </div>
    );
  }

  if (!canManageMembers && !canDeleteInitiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp(`/initiatives/${initiative.id}`)}>{t("settings.backToInitiative")}</Link>
        </Button>
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.permissionRequired")}</CardTitle>
            <CardDescription>{t("settings.permissionRequiredDescription")}</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/initiatives/${initiative.id}`)}>{initiative.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings.breadcrumbSettings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">{t("settings.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("settings.subtitle")}</p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("settings.detailsTab")}</TabsTrigger>
          <TabsTrigger value="members">{t("settings.membersTab")}</TabsTrigger>
          <TabsTrigger value="roles">{t("settings.rolesTab")}</TabsTrigger>
          <TabsTrigger value="danger">{t("settings.dangerTab")}</TabsTrigger>
        </TabsList>
        <TabsContent value="details">
          <Card>
            <CardHeader>
              <CardTitle>{t("settings.detailsTitle")}</CardTitle>
              <CardDescription>{t("settings.detailsDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={handleSaveDetails}>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="initiative-name">{t("settings.nameLabel")}</Label>
                    <Input
                      id="initiative-name"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      disabled={!canManageMembers || updateInitiative.isPending}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="initiative-color">{t("settings.colorLabel")}</Label>
                    <ColorPickerPopover
                      id="initiative-color"
                      value={color}
                      onChange={setColor}
                      disabled={!canManageMembers || updateInitiative.isPending}
                      triggerLabel="Adjust"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="initiative-description">{t("settings.descriptionLabel")}</Label>
                  <Textarea
                    id="initiative-description"
                    rows={4}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder={t("settings.descriptionPlaceholder")}
                    disabled={!canManageMembers || updateInitiative.isPending}
                  />
                </div>
                {canManageMembers ? (
                  <Button type="submit" disabled={updateInitiative.isPending}>
                    {updateInitiative.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        {t("settings.saving")}
                      </>
                    ) : (
                      t("settings.saveChanges")
                    )}
                  </Button>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    {t("settings.editPermissionNote")}
                  </p>
                )}
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="members">
          <Card>
            <CardHeader>
              <CardTitle>{t("settings.membersTitle")}</CardTitle>
              <CardDescription>{t("settings.membersDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <DataTable
                columns={memberColumns}
                data={initiative.members}
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
                    {rolesQuery.data && (
                      <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
                        <SelectTrigger className="w-44">
                          <SelectValue placeholder={t("settings.selectRole")} />
                        </SelectTrigger>
                        <SelectContent>
                          {rolesQuery.data.map((role) => (
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
                <Button
                  variant="outline"
                  onClick={() => setShowNewRoleDialog(true)}
                  disabled={createRoleMutation.isPending}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {t("settings.addCustomRole")}
                </Button>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="danger">
          <Card className="border-destructive/40">
            <CardHeader>
              <CardTitle className="text-destructive">{t("settings.dangerTitle")}</CardTitle>
              <CardDescription>{t("settings.dangerDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {canDeleteInitiative ? (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={handleDeleteInitiative}
                  disabled={initiative.is_default || deleteInitiative.isPending}
                >
                  {deleteInitiative.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      {t("settings.deletingInitiative")}
                    </>
                  ) : (
                    <>
                      <Trash2 className="mr-2 h-4 w-4" />
                      {t("settings.deleteInitiative")}
                    </>
                  )}
                </Button>
              ) : (
                <p className="text-muted-foreground text-sm">
                  {t("settings.contactAdmin", { adminLabel })}
                </p>
              )}
              {initiative.is_default ? (
                <p className="text-muted-foreground text-xs">{t("settings.defaultCannotDelete")}</p>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Delete Initiative Dialog */}
      <AlertDialog
        open={showDeleteConfirm}
        onOpenChange={(open) => {
          setShowDeleteConfirm(open);
          if (!open) setDeleteConfirmText("");
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="settings.deleteConfirmDescription"
                ns="initiatives"
                values={{ name: initiative?.name }}
                components={{ bold: <strong /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="delete-confirm-input">
              <Trans
                i18nKey="settings.deleteConfirmLabel"
                ns="initiatives"
                values={{ name: initiative?.name }}
                components={{ bold: <strong /> }}
              />
            </Label>
            <Input
              id="delete-confirm-input"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder={initiative?.name}
              autoComplete="off"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteInitiative.isPending}>
              {t("common:cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteInitiative}
              disabled={!canConfirmDelete || deleteInitiative.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {deleteInitiative.isPending ? t("settings.deletingInitiative") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* New Role Dialog */}
      <Dialog
        open={showNewRoleDialog}
        onOpenChange={(open) => {
          setShowNewRoleDialog(open);
          if (!open) roleNameTouchedRef.current = false;
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.createRoleTitle")}</DialogTitle>
            <DialogDescription>{t("settings.createRoleDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="new-role-display-name">{t("settings.roleDisplayNameLabel")}</Label>
              <Input
                id="new-role-display-name"
                value={newRoleDisplayName}
                onChange={(e) => {
                  const display = e.target.value;
                  setNewRoleDisplayName(display);
                  if (!roleNameTouchedRef.current) {
                    setNewRoleName(
                      display
                        .trim()
                        .toLowerCase()
                        .replace(/\s+/g, "_")
                        .replace(/[^a-z0-9_]/g, "")
                    );
                  }
                }}
                placeholder={t("settings.roleDisplayNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-role-name">{t("settings.roleInternalNameLabel")}</Label>
              <Input
                id="new-role-name"
                value={newRoleName}
                onChange={(e) => {
                  const snakeCase = e.target.value
                    .toLowerCase()
                    .replace(/\s+/g, "_")
                    .replace(/[^a-z0-9_]/g, "");
                  setNewRoleName(snakeCase);
                  if (!snakeCase && !newRoleDisplayName) {
                    roleNameTouchedRef.current = false;
                  } else {
                    roleNameTouchedRef.current = true;
                  }
                }}
                placeholder={t("settings.roleInternalNamePlaceholder")}
              />
              <p className="text-muted-foreground text-xs">{t("settings.roleInternalNameHint")}</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewRoleDialog(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={handleCreateRole}
              disabled={
                createRoleMutation.isPending || !newRoleName.trim() || !newRoleDisplayName.trim()
              }
            >
              {createRoleMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.creatingRole")}
                </>
              ) : (
                t("settings.createRole")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Role Confirmation Dialog */}
      <AlertDialog open={!!roleToDelete} onOpenChange={(open) => !open && setRoleToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteRoleTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.deleteRoleDescription", { roleName: roleToDelete?.display_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRoleMutation.isPending}>
              {t("common:cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteRole}
              disabled={deleteRoleMutation.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {deleteRoleMutation.isPending ? t("settings.deletingRole") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Rename Role Dialog */}
      <Dialog open={!!roleToRename} onOpenChange={(open) => !open && setRoleToRename(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.renameRoleTitle")}</DialogTitle>
            <DialogDescription>
              {t("settings.renameRoleDescription", { roleName: roleToRename?.display_name })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="rename-role-display-name">{t("settings.roleDisplayNameLabel")}</Label>
              <Input
                id="rename-role-display-name"
                value={renameDisplayName}
                onChange={(e) => setRenameDisplayName(e.target.value)}
                placeholder={t("settings.roleDisplayNamePlaceholder")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleToRename(null)}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={confirmRenameRole}
              disabled={updateRoleMutation.isPending || !renameDisplayName.trim()}
            >
              {updateRoleMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.savingRole")}
                </>
              ) : (
                t("common:save")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove Member Confirmation Dialog */}
      <AlertDialog
        open={!!memberToRemove}
        onOpenChange={(open) => !open && setMemberToRemove(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.removeMemberTitle")}</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <span className="block">
                <Trans
                  i18nKey="settings.removeMemberDescription"
                  ns="initiatives"
                  values={{
                    name: memberToRemove?.user.full_name || memberToRemove?.user.email,
                  }}
                  components={{ bold: <strong /> }}
                />
              </span>
              <span className="text-destructive block">{t("settings.removeMemberWarning")}</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removeMember.isPending}>
              {t("common:cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (memberToRemove) {
                  removeMember.mutate(
                    { initiativeId, userId: memberToRemove.user.id },
                    { onSuccess: () => setMemberToRemove(null) }
                  );
                }
              }}
              disabled={removeMember.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {removeMember.isPending ? t("settings.removing") : t("settings.removeMember")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
