import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams, useRouter } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useGuildPath } from "@/lib/guildUrl";
import type { ColumnDef, Row } from "@tanstack/react-table";
import { Loader2, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
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
  Initiative,
  InitiativeMember,
  InitiativeMemberUpdate,
  InitiativeRoleRead,
  PermissionKey,
  User,
} from "@/types/api";

const INITIATIVES_QUERY_KEY = ["initiatives"];
const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const InitiativeSettingsPage = () => {
  const { initiativeId: initiativeIdParam } = useParams({ strict: false }) as {
    initiativeId: string;
  };
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const router = useRouter();
  const queryClient = useQueryClient();

  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const gp = useGuildPath();

  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);
  const adminLabel = getRoleLabel("admin", roleLabels);

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: INITIATIVES_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
    enabled: hasValidInitiativeId,
  });

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

  // Delete role confirmation
  const [roleToDelete, setRoleToDelete] = useState<InitiativeRoleRead | null>(null);

  // Rename role dialog
  const [roleToRename, setRoleToRename] = useState<InitiativeRoleRead | null>(null);
  const [renameDisplayName, setRenameDisplayName] = useState("");

  // Remove member confirmation
  const [memberToRemove, setMemberToRemove] = useState<InitiativeMember | null>(null);

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

  const usersQuery = useQuery<User[]>({
    queryKey: ["users", { guildId: activeGuild?.id }],
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
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

  const updateInitiative = useMutation({
    mutationFn: async (payload: Partial<Pick<Initiative, "name" | "description" | "color">>) => {
      const response = await apiClient.patch<Initiative>(`/initiatives/${initiativeId}`, payload);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Initiative updated.");
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to update initiative right now.";
      toast.error(message);
    },
  });

  const deleteInitiative = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/initiatives/${initiativeId}`);
    },
    onSuccess: () => {
      toast.success("Initiative deleted.");
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
      router.navigate({ to: gp("/initiatives") });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to delete initiative right now.";
      toast.error(message);
    },
  });

  const addMember = useMutation({
    mutationFn: async ({ userId, roleId }: { userId: number; roleId: number }) => {
      const response = await apiClient.post<Initiative>(`/initiatives/${initiativeId}/members`, {
        user_id: userId,
        role_id: roleId,
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success("Member added.");
      setSelectedUserId("");
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to add member right now.";
      toast.error(message);
    },
  });

  const removeMember = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/initiatives/${initiativeId}/members/${userId}`);
    },
    onSuccess: () => {
      toast.success("Member removed.");
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to remove member right now.";
      toast.error(message);
    },
  });

  const updateMemberRole = useMutation({
    mutationFn: async ({ userId, roleId }: { userId: number; roleId: number }) => {
      const payload: InitiativeMemberUpdate = { role_id: roleId };
      const response = await apiClient.patch<Initiative>(
        `/initiatives/${initiativeId}/members/${userId}`,
        payload
      );
      return response.data;
    },
    onSuccess: () => {
      toast.success("Role updated.");
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
    onError: () => {
      toast.error("Unable to update role right now.");
    },
  });

  const handleSaveDetails = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error("Name is required.");
      return;
    }
    updateInitiative.mutate({
      name: trimmedName,
      description: description.trim() || undefined,
      color,
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
    addMember.mutate({ userId, roleId });
  };

  const handleDeleteInitiative = () => {
    if (initiative?.is_default) {
      return;
    }
    setDeleteConfirmText("");
    setShowDeleteConfirm(true);
  };

  const confirmDeleteInitiative = () => {
    deleteInitiative.mutate();
    setShowDeleteConfirm(false);
    setDeleteConfirmText("");
  };

  const handleCreateRole = () => {
    const name = newRoleName.trim().toLowerCase().replace(/\s+/g, "_");
    const displayName = newRoleDisplayName.trim();
    if (!name || !displayName) {
      toast.error("Name and display name are required.");
      return;
    }
    createRoleMutation.mutate(
      { name, display_name: displayName },
      {
        onSuccess: () => {
          setShowNewRoleDialog(false);
          setNewRoleName("");
          setNewRoleDisplayName("");
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
                  Built-in
                </Badge>
              )}
              {role.is_manager && (
                <Badge variant="outline" className="text-xs">
                  Manager
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
        header: () => <div className="text-center">Members</div>,
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
      canManageMembers,
      updateRoleMutation.isPending,
      deleteRoleMutation.isPending,
      handleTogglePermission,
      handleDeleteRole,
      handleRenameRole,
    ]
  );

  const memberColumns: ColumnDef<InitiativeMember>[] = useMemo(() => {
    // Get role display name for a member
    const getRoleDisplayName = (member: InitiativeMember): string => {
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
        header: "Name",
        cell: ({ row }) => {
          const member = row.original;
          return <span className="font-medium">{member.user.full_name?.trim() || "—"}</span>;
        },
      },
      {
        id: "email",
        accessorKey: "user.email",
        header: "Email",
        cell: ({ row }) => {
          const member = row.original;
          return <span className="text-muted-foreground">{member.user.email}</span>;
        },
      },
      {
        accessorKey: "role",
        header: "Role",
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
                  userId: member.user.id,
                  roleId: Number(value),
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
              Remove
            </Button>
          );
        },
      },
    ];
  }, [
    canManageMembers,
    rolesQuery.data,
    removeMember,
    updateMemberRole,
    projectManagerLabel,
    memberLabel,
  ]);

  if (!hasValidInitiativeId) {
    return <Navigate to={gp("/initiatives")} replace />;
  }

  if (initiativesQuery.isLoading || !initiativesQuery.data) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading initiative...
      </div>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp("/initiatives")}>&larr; Back to My Initiatives</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <h1 className="text-2xl font-semibold">Initiative not found</h1>
          <p className="text-muted-foreground">
            The initiative you&apos;re looking for doesn&apos;t exist or you no longer have access.
          </p>
        </div>
      </div>
    );
  }

  if (!canManageMembers && !canDeleteInitiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp(`/initiatives/${initiative.id}`)}>&larr; Back to initiative</Link>
        </Button>
        <Card>
          <CardHeader>
            <CardTitle>Permission required</CardTitle>
            <CardDescription>
              Only guild admins and initiative project managers can manage initiative settings.
            </CardDescription>
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
            <BreadcrumbPage>Settings</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Initiative settings</h1>
        <p className="text-muted-foreground text-sm">
          Update details, manage members and roles, and control dangerous actions.
        </p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
          <TabsTrigger value="roles">Roles</TabsTrigger>
          <TabsTrigger value="danger">Danger zone</TabsTrigger>
        </TabsList>
        <TabsContent value="details">
          <Card>
            <CardHeader>
              <CardTitle>Initiative details</CardTitle>
              <CardDescription>Rename, describe, or recolor this initiative.</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={handleSaveDetails}>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="initiative-name">Name</Label>
                    <Input
                      id="initiative-name"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      disabled={!canManageMembers || updateInitiative.isPending}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="initiative-color">Color</Label>
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
                  <Label htmlFor="initiative-description">Description</Label>
                  <Textarea
                    id="initiative-description"
                    rows={4}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Add context for your guild."
                    disabled={!canManageMembers || updateInitiative.isPending}
                  />
                </div>
                {canManageMembers ? (
                  <Button type="submit" disabled={updateInitiative.isPending}>
                    {updateInitiative.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      "Save changes"
                    )}
                  </Button>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    Only guild admins or initiative project managers can edit details.
                  </p>
                )}
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="members">
          <Card>
            <CardHeader>
              <CardTitle>Members</CardTitle>
              <CardDescription>
                Initiative project managers and guild admins can manage membership.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <DataTable
                columns={memberColumns}
                data={initiative.members}
                enableFilterInput
                filterInputColumnKey="name"
                filterInputPlaceholder="Filter by name"
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
                          ? "Loading members..."
                          : availableUsers.length > 0
                            ? "Select user"
                            : "Everyone has been added"
                      }
                      disabled={usersQuery.isLoading || availableUsers.length === 0}
                    />
                    {rolesQuery.data && (
                      <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
                        <SelectTrigger className="w-44">
                          <SelectValue placeholder="Select role" />
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
                          Adding...
                        </>
                      ) : (
                        "Add member"
                      )}
                    </Button>
                  </div>
                  {usersQuery.isError ? (
                    <p className="text-destructive text-xs">
                      Unable to load potential members right now.
                    </p>
                  ) : null}
                </>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="roles">
          <Card>
            <CardHeader>
              <CardTitle>Role permissions</CardTitle>
              <CardDescription>
                Configure what each role can do within this initiative. Project Manager permissions
                are locked to prevent accidental lockouts.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {rolesQuery.isLoading ? (
                <div className="text-muted-foreground flex items-center gap-2 text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading roles...
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
                  Add custom role
                </Button>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="danger">
          <Card className="border-destructive/40">
            <CardHeader>
              <CardTitle className="text-destructive">Danger zone</CardTitle>
              <CardDescription>
                Deleting an initiative removes all of its projects, tasks, and documents.
              </CardDescription>
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
                      Deleting...
                    </>
                  ) : (
                    <>
                      <Trash2 className="mr-2 h-4 w-4" />
                      Delete initiative
                    </>
                  )}
                </Button>
              ) : (
                <p className="text-muted-foreground text-sm">
                  Contact a guild admin ({adminLabel}) to delete this initiative.
                </p>
              )}
              {initiative.is_default ? (
                <p className="text-muted-foreground text-xs">
                  The default initiative cannot be deleted.
                </p>
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
            <AlertDialogTitle>Delete initiative?</AlertDialogTitle>
            <AlertDialogDescription>
              Deleting <strong>{initiative?.name}</strong> will permanently remove all projects,
              tasks, and documents within it. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="delete-confirm-input">
              Type <strong>{initiative?.name}</strong> to confirm:
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
            <AlertDialogCancel disabled={deleteInitiative.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteInitiative}
              disabled={!canConfirmDelete || deleteInitiative.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {deleteInitiative.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* New Role Dialog */}
      <Dialog open={showNewRoleDialog} onOpenChange={setShowNewRoleDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create custom role</DialogTitle>
            <DialogDescription>
              Add a new role with custom permissions for this initiative.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="new-role-display-name">Display name</Label>
              <Input
                id="new-role-display-name"
                value={newRoleDisplayName}
                onChange={(e) => setNewRoleDisplayName(e.target.value)}
                placeholder="e.g., Viewer"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-role-name">Internal name</Label>
              <Input
                id="new-role-name"
                value={newRoleName}
                onChange={(e) => {
                  // Auto-convert to snake_case
                  const snakeCase = e.target.value
                    .toLowerCase()
                    .replace(/\s+/g, "_")
                    .replace(/[^a-z0-9_]/g, "");
                  setNewRoleName(snakeCase);
                }}
                placeholder="e.g., viewer"
              />
              <p className="text-muted-foreground text-xs">
                Lowercase, no spaces. Used internally for identification.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewRoleDialog(false)}>
              Cancel
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
                  Creating...
                </>
              ) : (
                "Create role"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Role Confirmation Dialog */}
      <AlertDialog open={!!roleToDelete} onOpenChange={(open) => !open && setRoleToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete role?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete the role &quot;{roleToDelete?.display_name}&quot;?
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRoleMutation.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteRole}
              disabled={deleteRoleMutation.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {deleteRoleMutation.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Rename Role Dialog */}
      <Dialog open={!!roleToRename} onOpenChange={(open) => !open && setRoleToRename(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename role</DialogTitle>
            <DialogDescription>
              Change the display name for the &quot;{roleToRename?.display_name}&quot; role.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="rename-role-display-name">Display name</Label>
              <Input
                id="rename-role-display-name"
                value={renameDisplayName}
                onChange={(e) => setRenameDisplayName(e.target.value)}
                placeholder="e.g., Viewer"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleToRename(null)}>
              Cancel
            </Button>
            <Button
              onClick={confirmRenameRole}
              disabled={updateRoleMutation.isPending || !renameDisplayName.trim()}
            >
              {updateRoleMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save"
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
            <AlertDialogTitle>Remove member?</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <span className="block">
                Are you sure you want to remove{" "}
                <strong>{memberToRemove?.user.full_name || memberToRemove?.user.email}</strong> from
                this initiative?
              </span>
              <span className="text-destructive block">
                This will also remove their explicit access to all projects and documents in this
                initiative.
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removeMember.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (memberToRemove) {
                  removeMember.mutate(memberToRemove.user.id, {
                    onSuccess: () => setMemberToRemove(null),
                  });
                }
              }}
              disabled={removeMember.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {removeMember.isPending ? "Removing..." : "Remove"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
