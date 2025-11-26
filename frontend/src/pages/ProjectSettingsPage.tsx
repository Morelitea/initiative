import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import { Switch } from "../components/ui/switch";
import { EmojiPicker } from "../components/EmojiPicker";
import { useAuth } from "../hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "../hooks/useRoleLabels";
import { queryClient } from "../lib/queryClient";
import { Project, Initiative } from "../types/api";

const INITIATIVES_QUERY_KEY = ["initiatives"];

export const ProjectSettingsPage = () => {
  const { projectId } = useParams();
  const parsedProjectId = Number(projectId);
  const navigate = useNavigate();
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
  const [writerMessage, setWriterMessage] = useState<string | null>(null);
  const [writerError, setWriterError] = useState<string | null>(null);
  const [selectedWriterId, setSelectedWriterId] = useState<string>("");
  const [membersWriteMessage, setMembersWriteMessage] = useState<string | null>(null);
  const [membersWriteError, setMembersWriteError] = useState<string | null>(null);
  const { data: roleLabels } = useRoleLabels();
  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);

  const projectQuery = useQuery<Project>({
    queryKey: ["projects", parsedProjectId],
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
      setWriterMessage(null);
      setWriterError(null);
      setMembersWriteMessage(null);
      setMembersWriteError(null);
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
        queryKey: ["projects", parsedProjectId],
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
        queryKey: ["projects", parsedProjectId],
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
        queryKey: ["projects", parsedProjectId],
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
        queryKey: ["projects", parsedProjectId],
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
        queryKey: ["projects", parsedProjectId],
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
      void queryClient.invalidateQueries({ queryKey: ["projects", data.id] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
      navigate(`/projects/${data.id}`);
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
        queryKey: ["projects", parsedProjectId],
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
      navigate("/");
    },
  });

  const addWriter = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.post(`/projects/${parsedProjectId}/members`, {
        user_id: userId,
        level: "write",
      });
    },
    onSuccess: () => {
      setWriterMessage("Write access granted");
      setWriterError(null);
      setSelectedWriterId("");
      void queryClient.invalidateQueries({ queryKey: ["projects", parsedProjectId] });
    },
    onError: () => {
      setWriterMessage(null);
      setWriterError("Unable to update write access");
    },
  });

  const removeWriter = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/projects/${parsedProjectId}/members/${userId}`);
    },
    onSuccess: () => {
      setWriterMessage("Write access removed");
      setWriterError(null);
      void queryClient.invalidateQueries({ queryKey: ["projects", parsedProjectId] });
    },
    onError: () => {
      setWriterMessage(null);
      setWriterError("Unable to update write access");
    },
  });

  const updateMembersWrite = useMutation({
    mutationFn: async (allowAll: boolean) => {
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, {
        members_can_write: allowAll,
      });
      return response.data;
    },
    onSuccess: (_data, allowAll) => {
      setMembersWriteMessage(
        allowAll
          ? `Everyone with the ${memberLabel} role now has write access.`
          : `Write access limited to selected ${memberLabel} role holders.`
      );
      setMembersWriteError(null);
      void queryClient.invalidateQueries({ queryKey: ["projects", parsedProjectId] });
    },
    onError: () => {
      setMembersWriteMessage(null);
      setMembersWriteError(`Unable to update ${memberLabel} write access.`);
    },
  });

  if (!Number.isFinite(parsedProjectId)) {
    return <p className="text-destructive">Invalid project id.</p>;
  }

  const initiativesLoading = user?.role === "admin" ? initiativesQuery.isLoading : false;

  if (projectQuery.isLoading || initiativesLoading) {
    return <p className="text-sm text-muted-foreground">Loading project settings…</p>;
  }

  if (projectQuery.isError || !projectQuery.data) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  const project = projectQuery.data;
  const initiativeMembership = project.initiative?.members?.find(
    (member) => member.user.id === user?.id
  );
  const initiativeMembers = project.initiative?.members ?? [];
  const hasOwnerPermission = project.permissions.some(
    (permission) => permission.user_id === project.owner_id
  );
  const ownerFallbackName =
    project.owner?.full_name?.trim() || project.owner?.email || "Project owner";
  const effectivePermissions = hasOwnerPermission
    ? project.permissions
    : [
        {
          user_id: project.owner_id,
          level: "owner" as const,
          created_at: project.created_at,
          project_id: project.id,
        },
        ...project.permissions,
      ];
  const permissionRows = effectivePermissions.map((permission) => {
    const member = initiativeMembers.find((entry) => entry.user.id === permission.user_id);
    const displayName = member?.user.full_name?.trim() || member?.user.email || ownerFallbackName;
    return {
      permission,
      displayName,
      isOwner: permission.user_id === project.owner_id || permission.level === "owner",
    };
  });
  const availableMembers = initiativeMembers.filter(
    (member) =>
      member.user.id !== project.owner_id &&
      !project.permissions.some((permission) => permission.user_id === member.user.id)
  );
  const isOwner = project.owner_id === user?.id;
  const isInitiativePm = initiativeMembership?.role === "project_manager";
  const hasExplicitWrite = project.permissions.some(
    (permission) => permission.user_id === user?.id && permission.level === "write"
  );
  const canManageAccess = user?.role === "admin" || isOwner || isInitiativePm;
  const hasImplicitWrite = Boolean(project.members_can_write && initiativeMembership);
  const canWriteProject =
    user?.role === "admin" || isOwner || isInitiativePm || hasExplicitWrite || hasImplicitWrite;

  if (!canManageAccess && !canWriteProject) {
    return (
      <div className="space-y-4">
        <Button asChild variant="link" className="px-0">
          <Link to={`/projects/${project.id}`}>← Back to project</Link>
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
      <Button asChild variant="link" className="px-0">
        <Link to={`/projects/${project.id}`}>← Back to project</Link>
      </Button>
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
              <p className="text-sm text-muted-foreground">
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
                    <p className="text-sm text-muted-foreground">
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
                    {updateIdentity.isPending ? "Saving…" : "Save project details"}
                  </Button>
                  {identityMessage ? (
                    <p className="text-sm text-primary">{identityMessage}</p>
                  ) : null}
                  {updateIdentity.isError ? (
                    <p className="text-sm text-destructive">Unable to update project.</p>
                  ) : null}
                </div>
              </form>
            ) : (
              <p className="text-sm text-muted-foreground">
                You need write access to change the project name or icon.
              </p>
            )}
          </div>

          <div className="h-px bg-border" />

          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-base font-medium">Description</h3>
              <p className="text-sm text-muted-foreground">
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
                    {updateDescription.isPending ? "Saving…" : "Save description"}
                  </Button>
                  {descriptionMessage ? (
                    <p className="text-sm text-primary">{descriptionMessage}</p>
                  ) : null}
                </div>
              </form>
            ) : (
              <p className="text-sm text-muted-foreground">
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
              <p className="text-sm text-destructive">Unable to load initiatives.</p>
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
                    {updateInitiativeOwnership.isPending ? "Saving…" : "Save initiative"}
                  </Button>
                  {initiativeMessage ? (
                    <p className="text-sm text-primary">{initiativeMessage}</p>
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
            <CardTitle>Write access overrides</CardTitle>
            <CardDescription>
              People with the {projectManagerLabel} role can grant additional write access to
              specific {memberLabel} role holders.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex flex-col gap-3 rounded-md border px-3 py-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="font-medium">Allow everyone with the {memberLabel} role to write</p>
                  <p className="text-sm text-muted-foreground">
                    When enabled, everyone with the {memberLabel} role can create and update work in
                    this project without an individual override.
                  </p>
                </div>
                <Switch
                  id="members-can-write"
                  checked={project.members_can_write}
                  onCheckedChange={(checked) => {
                    setMembersWriteMessage(null);
                    setMembersWriteError(null);
                    updateMembersWrite.mutate(Boolean(checked));
                  }}
                  disabled={updateMembersWrite.isPending}
                />
              </div>
              {membersWriteMessage ? (
                <p className="text-sm text-primary">{membersWriteMessage}</p>
              ) : null}
              {membersWriteError ? (
                <p className="text-sm text-destructive">{membersWriteError}</p>
              ) : null}
            </div>
            <div className="space-y-2">
              {permissionRows.length === 0 ? (
                <p className="text-sm text-muted-foreground">No overrides yet.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {permissionRows.map(({ permission, displayName, isOwner }) => (
                    <li
                      key={`${permission.project_id ?? project.id}-${permission.user_id}`}
                      className="flex items-center justify-between rounded-md border px-3 py-2"
                    >
                      <div>
                        <p className="font-medium">{displayName}</p>
                        <p className="text-xs text-muted-foreground">
                          {isOwner ? "Owner" : "Write access"}
                        </p>
                      </div>
                      {!isOwner ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeWriter.mutate(permission.user_id)}
                          disabled={removeWriter.isPending}
                        >
                          Remove
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="writer-select">Grant write access</Label>
              {availableMembers.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Everyone with the {memberLabel} role already has write access.
                </p>
              ) : (
                <form
                  className="flex flex-wrap items-end gap-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!selectedWriterId) {
                      setWriterError(`Select a ${memberLabel}`);
                      return;
                    }
                    setWriterError(null);
                    addWriter.mutate(Number(selectedWriterId));
                  }}
                >
                  <Select value={selectedWriterId} onValueChange={setSelectedWriterId}>
                    <SelectTrigger id="writer-select" className="min-w-[220px]">
                      <SelectValue placeholder={`Select ${memberLabel}`} />
                    </SelectTrigger>
                    <SelectContent>
                      {availableMembers.map((member) => (
                        <SelectItem key={member.user.id} value={String(member.user.id)}>
                          {member.user.full_name?.trim() || member.user.email}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button type="submit" disabled={addWriter.isPending}>
                    {addWriter.isPending ? "Adding…" : `Add ${memberLabel}`}
                  </Button>
                </form>
              )}
              {writerMessage ? <p className="text-sm text-primary">{writerMessage}</p> : null}
              {writerError ? <p className="text-sm text-destructive">{writerError}</p> : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Template status</CardTitle>
          <CardDescription>
            Convert this project into a reusable template or revert it back to a standard project.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {project.is_template
              ? "This project is currently a template and appears on the Templates page."
              : "This project behaves like a standard project."}
          </p>
          {templateMessage ? <p className="text-sm text-primary">{templateMessage}</p> : null}
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
            <p className="text-sm text-muted-foreground">
              You need write access to change template status.
            </p>
          )}
          {project.is_template ? (
            <Button asChild variant="link" className="px-0">
              <Link to="/templates">View all templates</Link>
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
          {duplicateMessage ? <p className="text-sm text-primary">{duplicateMessage}</p> : null}
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
              {duplicateProject.isPending ? "Duplicating…" : "Duplicate project"}
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">
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
            <p className="text-sm text-muted-foreground">
              You need write access to change archive status.
            </p>
          )}
        </CardFooter>
      </Card>

      {user?.role === "admin" ? (
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
              onClick={() => {
                if (window.confirm("Delete this project? This cannot be undone.")) {
                  deleteProject.mutate();
                }
              }}
              disabled={deleteProject.isPending}
            >
              Delete project
            </Button>
          </CardFooter>
        </Card>
      ) : null}
    </div>
  );
};
