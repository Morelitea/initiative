import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Checkbox } from '../components/ui/checkbox';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import { Input } from '../components/ui/input';
import { EmojiPicker } from '../components/EmojiPicker';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Project, ProjectRole, Initiative } from '../types/api';

const INITIATIVES_QUERY_KEY = ['initiatives'];
const NO_INITIATIVE_VALUE = 'none';

export const ProjectSettingsPage = () => {
  const { projectId } = useParams();
  const parsedProjectId = Number(projectId);
  const navigate = useNavigate();
  const { user } = useAuth();
  const [readRoles, setReadRoles] = useState<ProjectRole[]>([]);
  const [writeRoles, setWriteRoles] = useState<ProjectRole[]>([]);
  const [selectedInitiativeId, setSelectedInitiativeId] = useState<string>(NO_INITIATIVE_VALUE);
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [initiativeMessage, setInitiativeMessage] = useState<string | null>(null);
  const [nameText, setNameText] = useState<string>('');
  const [iconText, setIconText] = useState<string>('');
  const [identityMessage, setIdentityMessage] = useState<string | null>(null);
  const [descriptionText, setDescriptionText] = useState<string>('');
  const [descriptionMessage, setDescriptionMessage] = useState<string | null>(null);
  const [templateMessage, setTemplateMessage] = useState<string | null>(null);
  const [duplicateMessage, setDuplicateMessage] = useState<string | null>(null);

  const projectQuery = useQuery<Project>({
    queryKey: ['projects', parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${parsedProjectId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: INITIATIVES_QUERY_KEY,
    enabled: user?.role === 'admin',
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>('/initiatives/');
      return response.data;
    },
  });

  useEffect(() => {
    if (projectQuery.data) {
      setReadRoles(projectQuery.data.read_roles);
      setWriteRoles(projectQuery.data.write_roles);
      setSelectedInitiativeId(projectQuery.data.initiative_id ? String(projectQuery.data.initiative_id) : NO_INITIATIVE_VALUE);
      setNameText(projectQuery.data.name);
      setIconText(projectQuery.data.icon ?? '');
      setDescriptionText(projectQuery.data.description ?? '');
      setAccessMessage(null);
      setInitiativeMessage(null);
      setIdentityMessage(null);
      setDescriptionMessage(null);
      setTemplateMessage(null);
    }
  }, [projectQuery.data]);

  const updateAccess = useMutation({
    mutationFn: async () => {
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, {
        read_roles: readRoles,
        write_roles: writeRoles,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setAccessMessage('Access settings updated');
      setReadRoles(data.read_roles);
      setWriteRoles(data.write_roles);
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
    },
  });

  const updateInitiativeOwnership = useMutation({
    mutationFn: async () => {
      const payload =
        selectedInitiativeId === NO_INITIATIVE_VALUE
          ? { initiative_id: null }
          : { initiative_id: Number(selectedInitiativeId) };
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, payload);
      return response.data;
    },
    onSuccess: (data) => {
      setInitiativeMessage('Project initiative updated');
      setSelectedInitiativeId(data.initiative_id ? String(data.initiative_id) : NO_INITIATIVE_VALUE);
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
    },
  });

  const updateIdentity = useMutation({
    mutationFn: async () => {
      const trimmedIcon = iconText.trim();
      const payload = {
        name: nameText.trim() || projectQuery.data?.name || '',
        icon: trimmedIcon ? trimmedIcon : null,
      };
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, payload);
      return response.data;
    },
    onSuccess: (data) => {
      setIdentityMessage('Project details updated');
      setNameText(data.name);
      setIconText(data.icon ?? '');
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
    },
  });

  const archiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/archive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
    },
  });

  const unarchiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
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
      setDescriptionMessage('Description updated');
      setDescriptionText(data.description ?? '');
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
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
      setDuplicateMessage('Project duplicated');
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void queryClient.invalidateQueries({ queryKey: ['projects', data.id] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
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
      setTemplateMessage(nextStatus ? 'Project marked as template' : 'Project removed from templates');
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
    },
  });

  const deleteProject = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/projects/${parsedProjectId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      void queryClient.invalidateQueries({ queryKey: ['projects', 'templates'] });
      navigate('/');
    },
  });

  if (!Number.isFinite(parsedProjectId)) {
    return <p className="text-destructive">Invalid project id.</p>;
  }

  const initiativesLoading = user?.role === 'admin' ? initiativesQuery.isLoading : false;

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
  const membershipRole = project.members.find((member) => member.user_id === user?.id)?.role;
  const userProjectRole = (user?.role as ProjectRole | undefined) ?? undefined;
  const canManageAccess =
    user?.role === 'admin' || membershipRole === 'admin' || membershipRole === 'project_manager';
  const canWriteProject =
    user?.role === 'admin' ||
    (membershipRole ? project.write_roles.includes(membershipRole) : false) ||
    (userProjectRole ? project.write_roles.includes(userProjectRole) : false);

  const projectRoleOptions: ProjectRole[] = ['admin', 'project_manager', 'member'];

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
          Configure access, ownership, and archival status for{' '}
          {project.icon ? `${project.icon} ${project.name}` : project.name}.
        </p>
      </div>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Project details</CardTitle>
          <CardDescription>Update the icon, name, and description shown across the workspace.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-8">
          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-base font-medium">Identity</h3>
              <p className="text-sm text-muted-foreground">Give the project a recognizable name and emoji.</p>
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
                      onChange={(emoji) => setIconText(emoji ?? '')}
                    />
                    <p className="text-sm text-muted-foreground">Pick an emoji to make this project easy to spot.</p>
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
                    {updateIdentity.isPending ? 'Saving…' : 'Save project details'}
                  </Button>
                  {identityMessage ? <p className="text-sm text-primary">{identityMessage}</p> : null}
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
              <p className="text-sm text-muted-foreground">Share context to help collaborators understand the work.</p>
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
                    {updateDescription.isPending ? 'Saving…' : 'Save description'}
                  </Button>
                  {descriptionMessage ? <p className="text-sm text-primary">{descriptionMessage}</p> : null}
                </div>
              </form>
            ) : (
              <p className="text-sm text-muted-foreground">You need write access to edit the description.</p>
            )}
          </div>
        </CardContent>
      </Card>

      {project.initiative ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Project initiative</CardTitle>
            <CardDescription>The initiative currently assigned to this project.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="font-medium">{project.initiative.name}</p>
            {project.initiative.members.length ? (
              <ul className="space-y-2 text-sm text-muted-foreground">
                {project.initiative.members.map((member) => (
                  <li key={member.id}>{member.full_name ?? member.email}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No initiative members yet.</p>
            )}
          </CardContent>
        </Card>
      ) : null}

      {user?.role === 'admin' ? (
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
                className="flex flex-wrap gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  updateInitiativeOwnership.mutate();
                }}
              >
                <div className="min-w-[220px] flex-1">
                  <Label htmlFor="project-initiative">Owning initiative</Label>
                  <Select value={selectedInitiativeId} onValueChange={setSelectedInitiativeId}>
                    <SelectTrigger id="project-initiative" className="mt-2">
                      <SelectValue placeholder="No initiative" />
                    </SelectTrigger>
                        <SelectContent>
                      <SelectItem value={NO_INITIATIVE_VALUE}>No initiative</SelectItem>
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
                    {updateInitiativeOwnership.isPending ? 'Saving…' : 'Save initiative'}
                  </Button>
                  {initiativeMessage ? <p className="text-sm text-primary">{initiativeMessage}</p> : null}
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
            <CardDescription>Choose which project roles can read or update this project.</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-6"
              onSubmit={(event) => {
                event.preventDefault();
                setAccessMessage(null);
                updateAccess.mutate();
              }}
            >
              <div className="space-y-3">
                <Label>Read access</Label>
                <div className="flex flex-wrap gap-4">
                  {projectRoleOptions.map((role) => (
                    <label key={`read-${role}`} className="flex items-center gap-2 text-sm capitalize">
                      <Checkbox
                        checked={readRoles.includes(role)}
                        onCheckedChange={() =>
                          setReadRoles((prev) =>
                            prev.includes(role) ? prev.filter((value) => value !== role) : [...prev, role]
                          )
                        }
                      />
                      {role.replace('_', ' ')}
                    </label>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                <Label>Write access</Label>
                <div className="flex flex-wrap gap-4">
                  {projectRoleOptions.map((role) => (
                    <label key={`write-${role}`} className="flex items-center gap-2 text-sm capitalize">
                      <Checkbox
                        checked={writeRoles.includes(role)}
                        onCheckedChange={() =>
                          setWriteRoles((prev) =>
                            prev.includes(role) ? prev.filter((value) => value !== role) : [...prev, role]
                          )
                        }
                      />
                      {role.replace('_', ' ')}
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <Button type="submit" disabled={updateAccess.isPending}>
                  {updateAccess.isPending ? 'Saving…' : 'Save access'}
                </Button>
                {accessMessage ? <p className="text-sm text-primary">{accessMessage}</p> : null}
              </div>
            </form>
      </CardContent>
    </Card>
  ) : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Template status</CardTitle>
          <CardDescription>Convert this project into a reusable template or revert it back to a standard project.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {project.is_template
              ? 'This project is currently a template and appears on the Templates page.'
              : 'This project behaves like a standard project.'}
          </p>
          {templateMessage ? <p className="text-sm text-primary">{templateMessage}</p> : null}
        </CardContent>
        <CardFooter className="flex flex-wrap gap-3">
          {canWriteProject ? (
            <Button
              type="button"
              variant={project.is_template ? 'outline' : 'default'}
              onClick={() => {
                setTemplateMessage(null);
                toggleTemplateStatus.mutate(!project.is_template);
              }}
              disabled={toggleTemplateStatus.isPending}
            >
              {project.is_template ? 'Convert to standard project' : 'Mark as template'}
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
        <CardDescription>Clone this project, including its initiative and tasks, to jumpstart new work.</CardDescription>
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
                const newName = window.prompt('Name for duplicated project', defaultName);
                if (newName === null) {
                  return;
                }
                setDuplicateMessage(null);
                duplicateProject.mutate(newName);
              }}
              disabled={duplicateProject.isPending}
            >
              {duplicateProject.isPending ? 'Duplicating…' : 'Duplicate project'}
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">You need write access to duplicate this project.</p>
          )}
        </CardFooter>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Archive status</CardTitle>
          <CardDescription>
            {project.is_archived ? 'This project is archived.' : 'This project is active.'}
          </CardDescription>
        </CardHeader>
        <CardFooter>
          {canWriteProject ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => (project.is_archived ? unarchiveProject.mutate() : archiveProject.mutate())}
              disabled={archiveProject.isPending || unarchiveProject.isPending}
            >
              {project.is_archived ? 'Unarchive project' : 'Archive project'}
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">You need write access to change archive status.</p>
          )}
        </CardFooter>
      </Card>

      {user?.role === 'admin' ? (
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
                if (window.confirm('Delete this project? This cannot be undone.')) {
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
