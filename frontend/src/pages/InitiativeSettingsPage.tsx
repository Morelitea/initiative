import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DataTable } from "@/components/ui/data-table";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import type { Initiative, InitiativeMember, InitiativeRole, User } from "@/types/api";

const INITIATIVES_QUERY_KEY = ["initiatives"];
const USERS_QUERY_KEY = ["users"];
const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const InitiativeSettingsPage = () => {
  const { initiativeId: initiativeIdParam } = useParams();
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const { data: roleLabels } = useRoleLabels();

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

  const isGuildAdmin = user?.role === "admin" || activeGuild?.role === "admin";
  const initiativeMembership = initiative?.members.find((member) => member.user.id === user?.id);
  const isInitiativeManager = initiativeMembership?.role === "project_manager";
  const canManageMembers = Boolean(isGuildAdmin || isInitiativeManager);
  const canDeleteInitiative = Boolean(isGuildAdmin);

  const [name, setName] = useState(initiative?.name ?? "");
  const [description, setDescription] = useState(initiative?.description ?? "");
  const [color, setColor] = useState(initiative?.color ?? DEFAULT_INITIATIVE_COLOR);
  const [selectedUserId, setSelectedUserId] = useState("");

  useEffect(() => {
    if (initiative) {
      setName(initiative.name);
      setDescription(initiative.description ?? "");
      setColor(initiative.color ?? DEFAULT_INITIATIVE_COLOR);
    }
  }, [initiative]);

  const usersQuery = useQuery<User[]>({
    queryKey: USERS_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
    enabled: canManageMembers,
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
      navigate("/initiatives");
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to delete initiative right now.";
      toast.error(message);
    },
  });

  const addMember = useMutation({
    mutationFn: async (userId: number) => {
      const response = await apiClient.post<Initiative>(`/initiatives/${initiativeId}/members`, {
        user_id: userId,
        role: "member",
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
    mutationFn: async ({ userId, role }: { userId: number; role: InitiativeRole }) => {
      const response = await apiClient.patch<Initiative>(
        `/initiatives/${initiativeId}/members/${userId}`,
        { role }
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
    if (!selectedUserId) {
      return;
    }
    const userId = Number(selectedUserId);
    if (!Number.isFinite(userId)) {
      return;
    }
    addMember.mutate(userId);
  };

  const handleDeleteInitiative = () => {
    if (initiative?.is_default) {
      return;
    }
    const confirmed = window.confirm(
      `Deleting "${initiative?.name}" removes all projects, tasks, and documents. Continue?`
    );
    if (confirmed) {
      deleteInitiative.mutate();
    }
  };

  const memberColumns: ColumnDef<InitiativeMember>[] = useMemo(
    () => [
      {
        accessorKey: "user.full_name",
        header: "Name",
        cell: ({ row }) => {
          const member = row.original;
          return (
            <div>
              <p className="font-medium">
                {member.user.full_name?.trim() || member.user.email || "Unknown user"}
              </p>
              <p className="text-muted-foreground text-xs">{member.user.email}</p>
            </div>
          );
        },
      },
      {
        accessorKey: "role",
        header: "Role",
        cell: ({ row }) => {
          const member = row.original;
          if (!canManageMembers) {
            return (
              <Badge variant="outline">
                {member.role === "project_manager" ? projectManagerLabel : memberLabel}
              </Badge>
            );
          }
          return (
            <Select
              value={member.role}
              onValueChange={(value) =>
                updateMemberRole.mutate({
                  userId: member.user.id,
                  role: value as InitiativeRole,
                })
              }
              disabled={updateMemberRole.isPending}
            >
              <SelectTrigger className="w-44">
                <SelectValue placeholder="Role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="project_manager">{projectManagerLabel}</SelectItem>
                <SelectItem value="member">{memberLabel}</SelectItem>
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
              onClick={() => removeMember.mutate(member.user.id)}
              disabled={removeMember.isPending}
            >
              Remove
            </Button>
          );
        },
      },
    ],
    [canManageMembers, memberLabel, projectManagerLabel, removeMember, updateMemberRole]
  );

  if (!hasValidInitiativeId) {
    return <Navigate to="/initiatives" replace />;
  }

  if (initiativesQuery.isLoading || !initiativesQuery.data) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading initiative…
      </div>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to="/initiatives">← Back to My Initiatives</Link>
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
          <Link to={`/initiatives/${initiative.id}`}>← Back to initiative</Link>
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
      <Button variant="link" size="sm" asChild className="px-0">
        <Link to={`/initiatives/${initiative.id}`}>← Back to {initiative.name}</Link>
      </Button>
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Initiative settings</h1>
        <p className="text-muted-foreground text-sm">
          Update details, manage members, and control dangerous actions.
        </p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
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
                        Saving…
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
              <DataTable columns={memberColumns} data={initiative.members} />
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
                          ? "Loading members…"
                          : availableUsers.length > 0
                            ? `Select ${memberLabel}`
                            : "Everyone has been added"
                      }
                      disabled={usersQuery.isLoading || availableUsers.length === 0}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleAddMember}
                      disabled={
                        !selectedUserId ||
                        addMember.isPending ||
                        usersQuery.isLoading ||
                        availableUsers.length === 0
                      }
                    >
                      {addMember.isPending ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Adding…
                        </>
                      ) : (
                        `Add ${memberLabel}`
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
                      Deleting…
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
    </div>
  );
};
