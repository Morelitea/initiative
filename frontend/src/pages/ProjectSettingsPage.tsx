import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useRouter } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";

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
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { EmojiPicker } from "@/components/EmojiPicker";
import { useAuth } from "@/hooks/useAuth";
import { queryClient } from "@/lib/queryClient";
import { Project, Initiative, ProjectPermissionLevel } from "@/types/api";
import { ProjectTaskStatusesManager } from "@/components/projects/ProjectTaskStatusesManager";

const INITIATIVES_QUERY_KEY = ["initiatives"];

const PERMISSION_LABELS: Record<ProjectPermissionLevel, string> = {
  owner: "Owner",
  write: "Can edit",
  read: "Can view",
};

interface PermissionRow {
  userId: number;
  displayName: string;
  level: ProjectPermissionLevel;
  isOwner: boolean;
}

export const ProjectSettingsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId: string };
  const parsedProjectId = Number(projectId);
  const router = useRouter();
  const { user } = useAuth();
  const [selectedInitiativeId, setSelectedInitiativeId] = useState<string>("");
  const [initiativeMessage, setInitiativeMessage] = useState<string | null>(null);
  const [nameText, setNameText] = useState<string>("");
  const [iconText, setIconText] = useState<string>("");
  const [identityMessage, setIdentityMessage] = useState<string | null>(null);
  const [descriptionText, setDescriptionText] = useState<string>("");
  const [descriptionMessage, setDescriptionMessage] = useState<string | null>(null);
  const [templateMessage, setTemplateMessage] = useState<string | null>(null);
  const [duplicateMessage, setDuplicateMessage] = useState<string | null>(null);
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [selectedNewUserId, setSelectedNewUserId] = useState<string>("");
  const [selectedNewLevel, setSelectedNewLevel] = useState<ProjectPermissionLevel>("read");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [selectedMembers, setSelectedMembers] = useState<PermissionRow[]>([]);

  const projectQuery = useQuery<Project>({
    queryKey: ["project", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${parsedProjectId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: INITIATIVES_QUERY_KEY,
    enabled: user?.role === "admin",
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

  useEffect(() => {
    if (projectQuery.data) {
      setSelectedInitiativeId(String(projectQuery.data.initiative_id));
      setNameText(projectQuery.data.name);
      setIconText(projectQuery.data.icon ?? "");
      setDescriptionText(projectQuery.data.description ?? "");
      setAccessMessage(null);
      setAccessError(null);
      setInitiativeMessage(null);
      setIdentityMessage(null);
      setDescriptionMessage(null);
      setTemplateMessage(null);
    }
  }, [projectQuery.data]);

  const updateInitiativeOwnership = useMutation({
    mutationFn: async () => {
      if (!selectedInitiativeId) {
        throw new Error("Select an initiative");
      }
      const payload = { initiative_id: Number(selectedInitiativeId) };
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, payload);
      return response.data;
    },
    onSuccess: (data) => {
      setInitiativeMessage("Project initiative updated");
      setSelectedInitiativeId(String(data.initiative_id));
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const updateIdentity = useMutation({
    mutationFn: async () => {
      const trimmedIcon = iconText.trim();
      const payload = {
        name: nameText.trim() || projectQuery.data?.name || "",
        icon: trimmedIcon ? trimmedIcon : null,
      };
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, payload);
      return response.data;
    },
    onSuccess: (data) => {
      setIdentityMessage("Project details updated");
      setNameText(data.name);
      setIconText(data.icon ?? "");
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const archiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/archive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const unarchiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const updateDescription = useMutation({
    mutationFn: async () => {
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, {
        description: descriptionText,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setDescriptionMessage("Description updated");
      setDescriptionText(data.description ?? "");
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const duplicateProject = useMutation({
    mutationFn: async (name?: string) => {
      const response = await apiClient.post<Project>(`/projects/${parsedProjectId}/duplicate`, {
        name: name?.trim() || undefined,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setDuplicateMessage("Project duplicated");
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["project", data.id] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
      router.navigate({ to: "/projects/$projectId", params: { projectId: String(data.id) } });
    },
  });

  const toggleTemplateStatus = useMutation({
    mutationFn: async (nextStatus: boolean) => {
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, {
        is_template: nextStatus,
      });
      return response.data;
    },
    onSuccess: (data, nextStatus) => {
      setTemplateMessage(
        nextStatus ? "Project marked as template" : "Project removed from templates"
      );
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const deleteProject = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/projects/${parsedProjectId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
      router.navigate({ to: "/" });
    },
  });

  const addMember = useMutation({
    mutationFn: async ({ userId, level }: { userId: number; level: ProjectPermissionLevel }) => {
      await apiClient.post(`/projects/${parsedProjectId}/members`, {
        user_id: userId,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access granted");
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to grant access");
    },
  });

  const updateMemberLevel = useMutation({
    mutationFn: async ({ userId, level }: { userId: number; level: ProjectPermissionLevel }) => {
      await apiClient.patch(`/projects/${parsedProjectId}/members/${userId}`, {
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access updated");
      setAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to update access");
    },
  });

  const removeMember = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/projects/${parsedProjectId}/members/${userId}`);
    },
    onSuccess: () => {
      setAccessMessage("Access removed");
      setAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to remove access");
    },
  });

  const addAllMembers = useMutation({
    mutationFn: async (level: ProjectPermissionLevel) => {
      const userIds = availableMembers.map((member) => member.user.id);
      await apiClient.post(`/projects/${parsedProjectId}/members/bulk`, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access granted to all members");
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to grant access to all members");
    },
  });

  const bulkUpdateLevel = useMutation({
    mutationFn: async ({
      userIds,
      level,
    }: {
      userIds: number[];
      level: ProjectPermissionLevel;
    }) => {
      await apiClient.post(`/projects/${parsedProjectId}/members/bulk`, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access updated for selected members");
      setAccessError(null);
      setSelectedMembers([]);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to update access for selected members");
    },
  });

  const bulkRemoveMembers = useMutation({
    mutationFn: async (userIds: number[]) => {
      await apiClient.post(`/projects/${parsedProjectId}/members/bulk-delete`, {
        user_ids: userIds,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access removed for selected members");
      setAccessError(null);
      setSelectedMembers([]);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to remove access for selected members");
    },
  });

  const project = projectQuery.data;
  const initiativeMembers = useMemo(
    () => project?.initiative?.members ?? [],
    [project?.initiative?.members]
  );

  // Build permission rows with user info
  const permissionRows: PermissionRow[] = useMemo(
    () =>
      (project?.permissions ?? []).map((permission) => {
        const member = initiativeMembers.find((entry) => entry.user?.id === permission.user_id);
        const ownerInfo = project?.owner;
        const displayName =
          member?.user?.full_name?.trim() ||
          member?.user?.email ||
          (permission.user_id === project?.owner_id
            ? ownerInfo?.full_name?.trim() || ownerInfo?.email || "Project owner"
            : `User ${permission.user_id}`);
        return {
          userId: permission.user_id,
          displayName,
          level: permission.level,
          isOwner: permission.user_id === project?.owner_id,
        };
      }),
    [project?.permissions, project?.owner, project?.owner_id, initiativeMembers]
  );

  // Column definitions for the permissions table
  const permissionColumns: ColumnDef<PermissionRow>[] = useMemo(
    () => [
      {
        accessorKey: "displayName",
        header: "Name",
        cell: ({ row }) => <span className="font-medium">{row.original.displayName}</span>,
      },
      {
        accessorKey: "level",
        header: "Access",
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <span className="text-muted-foreground">Owner</span>;
          }
          return (
            <Select
              value={row.original.level}
              onValueChange={(value) => {
                setAccessMessage(null);
                setAccessError(null);
                updateMemberLevel.mutate({
                  userId: row.original.userId,
                  level: value as ProjectPermissionLevel,
                });
              }}
              disabled={updateMemberLevel.isPending}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{PERMISSION_LABELS.read}</SelectItem>
                <SelectItem value="write">{PERMISSION_LABELS.write}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">Actions</div>,
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
                Remove
              </Button>
            </div>
          );
        },
      },
    ],
    [updateMemberLevel, removeMember]
  );

  // Initiative members who don't have permissions yet
  const availableMembers = useMemo(
    () =>
      initiativeMembers.filter(
        (member) =>
          member.user &&
          !(project?.permissions ?? []).some((permission) => permission.user_id === member.user.id)
      ),
    [initiativeMembers, project?.permissions]
  );

  if (!Number.isFinite(parsedProjectId)) {
    return <p className="text-destructive">Invalid project id.</p>;
  }

  const initiativesLoading = user?.role === "admin" ? initiativesQuery.isLoading : false;

  if (projectQuery.isLoading || initiativesLoading) {
    return <p className="text-muted-foreground text-sm">Loading project settings...</p>;
  }

  if (projectQuery.isError || !project) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/projects">Back to projects</Link>
        </Button>
      </div>
    );
  }

  const isOwner = project.owner_id === user?.id;
  const userPermission = project.permissions.find((p) => p.user_id === user?.id);
  // Pure DAC: write access requires owner or write permission level
  const hasWriteAccess = userPermission?.level === "owner" || userPermission?.level === "write";
  // Pure DAC: write permission grants access to manage settings
  const canManageTaskStatuses = hasWriteAccess;
  const canManageAccess = hasWriteAccess;
  const canWriteProject = hasWriteAccess;

  if (!canManageAccess && !canWriteProject) {
    return (
      <div className="space-y-4">
        <Button asChild variant="link" className="px-0">
          <Link to="/projects/$projectId" params={{ projectId: String(project.id) }}>
            Back to project
          </Link>
        </Button>
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Project settings</CardTitle>
            <CardDescription>You do not have permission to manage this project.</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {project.initiative && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link
                    to="/initiatives/$initiativeId"
                    params={{ initiativeId: String(project.initiative.id) }}
                  >
                    {project.initiative.name}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/projects/$projectId" params={{ projectId: String(project.id) }}>
                {project.name}
              </Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Settings</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Project settings</h1>
        <p className="text-muted-foreground">
          Configure access, ownership, and archival status for{" "}
          {project.icon ? `${project.icon} ${project.name}` : project.name}.
        </p>
      </div>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Project details</CardTitle>
          <CardDescription>
            Update the icon, name, and description shown across the workspace.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-8">
          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-base font-medium">Identity</h3>
              <p className="text-muted-foreground text-sm">
                Give the project a recognizable name and emoji.
              </p>
            </div>
            {canWriteProject ? (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  setIdentityMessage(null);
                  updateIdentity.mutate();
                }}
              >
                <div className="flex flex-col gap-4 md:flex-row md:items-start">
                  <div className="w-full space-y-2 md:max-w-xs">
                    <Label htmlFor="project-icon">Icon</Label>
                    <EmojiPicker
                      id="project-icon"
                      value={iconText || undefined}
                      onChange={(emoji) => setIconText(emoji ?? "")}
                    />
                    <p className="text-muted-foreground text-sm">
                      Pick an emoji to make this project easy to spot.
                    </p>
                  </div>
                  <div className="w-full flex-1 space-y-2">
                    <Label htmlFor="project-name">Name</Label>
                    <Input
                      id="project-name"
                      value={nameText}
                      onChange={(event) => setNameText(event.target.value)}
                      placeholder="Product roadmap"
                      required
                    />
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  <Button type="submit" disabled={updateIdentity.isPending}>
                    {updateIdentity.isPending ? "Saving..." : "Save project details"}
                  </Button>
                  {identityMessage ? (
                    <p className="text-primary text-sm">{identityMessage}</p>
                  ) : null}
                  {updateIdentity.isError ? (
                    <p className="text-destructive text-sm">Unable to update project.</p>
                  ) : null}
                </div>
              </form>
            ) : (
              <p className="text-muted-foreground text-sm">
                You need write access to change the project name or icon.
              </p>
            )}
          </div>

          <div className="bg-border h-px" />

          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-base font-medium">Description</h3>
              <p className="text-muted-foreground text-sm">
                Share context to help collaborators understand the work.
              </p>
            </div>
            {canWriteProject ? (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  updateDescription.mutate();
                }}
              >
                <Textarea
                  rows={4}
                  value={descriptionText}
                  onChange={(event) => setDescriptionText(event.target.value)}
                  placeholder="What are we trying to accomplish?"
                />
                <div className="flex flex-col gap-2">
                  <Button type="submit" disabled={updateDescription.isPending}>
                    {updateDescription.isPending ? "Saving..." : "Save description"}
                  </Button>
                  {descriptionMessage ? (
                    <p className="text-primary text-sm">{descriptionMessage}</p>
                  ) : null}
                </div>
              </form>
            ) : (
              <p className="text-muted-foreground text-sm">
                You need write access to edit the description.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {user?.role === "admin" ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Initiative ownership</CardTitle>
            <CardDescription>Select which initiative owns this project.</CardDescription>
          </CardHeader>
          <CardContent>
            {initiativesQuery.isError ? (
              <p className="text-destructive text-sm">Unable to load initiatives.</p>
            ) : (
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  updateInitiativeOwnership.mutate();
                }}
              >
                <div className="min-w-[220px] flex-1">
                  <Label htmlFor="project-initiative">Owning initiative</Label>
                  <Select value={selectedInitiativeId} onValueChange={setSelectedInitiativeId}>
                    <SelectTrigger id="project-initiative" className="mt-2">
                      <SelectValue placeholder="Select initiative" />
                    </SelectTrigger>
                    <SelectContent>
                      {initiativesQuery.data?.map((initiative) => (
                        <SelectItem key={initiative.id} value={String(initiative.id)}>
                          {initiative.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-2">
                  <Button type="submit" disabled={updateInitiativeOwnership.isPending}>
                    {updateInitiativeOwnership.isPending ? "Saving..." : "Save initiative"}
                  </Button>
                  {initiativeMessage ? (
                    <p className="text-primary text-sm">{initiativeMessage}</p>
                  ) : null}
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      ) : null}

      {canManageAccess ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Project access</CardTitle>
            <CardDescription>Control who can view and edit this project.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Bulk action bar */}
            {selectedMembers.length > 0 && (
              <div className="bg-muted flex items-center gap-3 rounded-md p-3">
                <span className="text-sm font-medium">{selectedMembers.length} selected</span>
                <Select
                  onValueChange={(level) => {
                    const userIds = selectedMembers.filter((m) => !m.isOwner).map((m) => m.userId);
                    if (userIds.length > 0) {
                      bulkUpdateLevel.mutate({
                        userIds,
                        level: level as ProjectPermissionLevel,
                      });
                    }
                  }}
                  disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
                >
                  <SelectTrigger className="w-[150px]">
                    <SelectValue placeholder="Change access..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{PERMISSION_LABELS.read}</SelectItem>
                    <SelectItem value="write">{PERMISSION_LABELS.write}</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={() => {
                    const userIds = selectedMembers.filter((m) => !m.isOwner).map((m) => m.userId);
                    if (userIds.length > 0) {
                      bulkRemoveMembers.mutate(userIds);
                    }
                  }}
                  disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
                >
                  {bulkRemoveMembers.isPending ? "Removing..." : "Remove"}
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
              filterInputPlaceholder="Filter by name"
              enableRowSelection
              onRowSelectionChange={setSelectedMembers}
              onExitSelection={() => setSelectedMembers([])}
              getRowId={(row) => String(row.userId)}
            />

            {/* Add member form */}
            <div className="space-y-2 pt-2">
              <Label>Grant access</Label>
              {availableMembers.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  All initiative members already have access to this project.
                </p>
              ) : (
                <form
                  className="flex flex-wrap items-end gap-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!selectedNewUserId) {
                      setAccessError("Select a member");
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
                    placeholder="Select member"
                    emptyMessage="No members found"
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
                      <SelectItem value="read">{PERMISSION_LABELS.read}</SelectItem>
                      <SelectItem value="write">{PERMISSION_LABELS.write}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button type="submit" disabled={addMember.isPending || addAllMembers.isPending}>
                    {addMember.isPending ? "Adding..." : "Add"}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => addAllMembers.mutate(selectedNewLevel)}
                    disabled={addMember.isPending || addAllMembers.isPending}
                  >
                    {addAllMembers.isPending
                      ? "Adding all..."
                      : `Add all (${availableMembers.length})`}
                  </Button>
                </form>
              )}
              {accessMessage ? <p className="text-primary text-sm">{accessMessage}</p> : null}
              {accessError ? <p className="text-destructive text-sm">{accessError}</p> : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <ProjectTaskStatusesManager
        projectId={project.id}
        canManage={Boolean(canManageTaskStatuses)}
      />

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Template status</CardTitle>
          <CardDescription>
            Convert this project into a reusable template or revert it back to a standard project.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-muted-foreground text-sm">
            {project.is_template
              ? "This project is currently a template and appears on the Templates page."
              : "This project behaves like a standard project."}
          </p>
          {templateMessage ? <p className="text-primary text-sm">{templateMessage}</p> : null}
        </CardContent>
        <CardFooter className="flex flex-wrap gap-3">
          {canWriteProject ? (
            <Button
              type="button"
              variant={project.is_template ? "outline" : "default"}
              onClick={() => {
                setTemplateMessage(null);
                toggleTemplateStatus.mutate(!project.is_template);
              }}
              disabled={toggleTemplateStatus.isPending}
            >
              {project.is_template ? "Convert to standard project" : "Mark as template"}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">
              You need write access to change template status.
            </p>
          )}
          {project.is_template ? (
            <Button asChild variant="link" className="px-0">
              <Link to="/projects">View all templates</Link>
            </Button>
          ) : null}
        </CardFooter>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Duplicate project</CardTitle>
          <CardDescription>
            Clone this project, including its initiative and tasks, to jumpstart new work.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {duplicateMessage ? <p className="text-primary text-sm">{duplicateMessage}</p> : null}
        </CardContent>
        <CardFooter>
          {canWriteProject ? (
            <Button
              type="button"
              onClick={() => {
                const defaultName = `${project.name} copy`;
                const newName = window.prompt("Name for duplicated project", defaultName);
                if (newName === null) {
                  return;
                }
                setDuplicateMessage(null);
                duplicateProject.mutate(newName);
              }}
              disabled={duplicateProject.isPending}
            >
              {duplicateProject.isPending ? "Duplicating..." : "Duplicate project"}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">
              You need write access to duplicate this project.
            </p>
          )}
        </CardFooter>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Archive status</CardTitle>
          <CardDescription>
            {project.is_archived ? "This project is archived." : "This project is active."}
          </CardDescription>
        </CardHeader>
        <CardFooter>
          {canWriteProject ? (
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                project.is_archived ? unarchiveProject.mutate() : archiveProject.mutate()
              }
              disabled={archiveProject.isPending || unarchiveProject.isPending}
            >
              {project.is_archived ? "Unarchive project" : "Archive project"}
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">
              You need write access to change archive status.
            </p>
          )}
        </CardFooter>
      </Card>

      {isOwner ? (
        <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
          <CardHeader>
            <CardTitle className="text-destructive">Danger zone</CardTitle>
            <CardDescription className="text-destructive">
              Deleting a project removes all of its tasks permanently.
            </CardDescription>
          </CardHeader>
          <CardFooter>
            <Button
              type="button"
              variant="destructive"
              onClick={() => setShowDeleteConfirm(true)}
              disabled={deleteProject.isPending}
            >
              Delete project
            </Button>
          </CardFooter>
        </Card>
      ) : null}

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title="Delete project?"
        description="This will permanently delete the project and all of its tasks. This cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => {
          deleteProject.mutate();
          setShowDeleteConfirm(false);
        }}
        isLoading={deleteProject.isPending}
        destructive
      />
    </div>
  );
};
