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
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Project, ProjectRole, Team } from '../types/api';

const TEAMS_QUERY_KEY = ['teams'];
const NO_TEAM_VALUE = 'none';

export const ProjectSettingsPage = () => {
  const { projectId } = useParams();
  const parsedProjectId = Number(projectId);
  const navigate = useNavigate();
  const { user } = useAuth();
  const [readRoles, setReadRoles] = useState<ProjectRole[]>([]);
  const [writeRoles, setWriteRoles] = useState<ProjectRole[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<string>(NO_TEAM_VALUE);
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [teamMessage, setTeamMessage] = useState<string | null>(null);
  const [descriptionText, setDescriptionText] = useState<string>('');
  const [descriptionMessage, setDescriptionMessage] = useState<string | null>(null);

  const projectQuery = useQuery<Project>({
    queryKey: ['projects', parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${parsedProjectId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const teamsQuery = useQuery<Team[]>({
    queryKey: TEAMS_QUERY_KEY,
    enabled: user?.role === 'admin',
    queryFn: async () => {
      const response = await apiClient.get<Team[]>('/teams/');
      return response.data;
    },
  });

  useEffect(() => {
    if (projectQuery.data) {
      setReadRoles(projectQuery.data.read_roles);
      setWriteRoles(projectQuery.data.write_roles);
      setSelectedTeamId(projectQuery.data.team_id ? String(projectQuery.data.team_id) : NO_TEAM_VALUE);
      setDescriptionText(projectQuery.data.description ?? '');
      setAccessMessage(null);
      setTeamMessage(null);
      setDescriptionMessage(null);
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
    },
  });

  const updateTeamOwnership = useMutation({
    mutationFn: async () => {
      const payload = selectedTeamId === NO_TEAM_VALUE ? { team_id: null } : { team_id: Number(selectedTeamId) };
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, payload);
      return response.data;
    },
    onSuccess: (data) => {
      setTeamMessage('Project team updated');
      setSelectedTeamId(data.team_id ? String(data.team_id) : NO_TEAM_VALUE);
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
    },
  });

  const archiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/archive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  const unarchiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects', parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
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
    },
  });

  const deleteProject = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/projects/${parsedProjectId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate('/');
    },
  });

  if (!Number.isFinite(parsedProjectId)) {
    return <p className="text-destructive">Invalid project id.</p>;
  }

  const teamsLoading = user?.role === 'admin' ? teamsQuery.isLoading : false;

  if (projectQuery.isLoading || teamsLoading) {
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
          Configure access, ownership, and archival status for {project.name}.
        </p>
      </div>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Description</CardTitle>
          <CardDescription>Share more context with collaborators.</CardDescription>
        </CardHeader>
        <CardContent>
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
        </CardContent>
      </Card>

      {project.team ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Project team</CardTitle>
            <CardDescription>The team currently assigned to this project.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="font-medium">{project.team.name}</p>
            {project.team.members.length ? (
              <ul className="space-y-2 text-sm text-muted-foreground">
                {project.team.members.map((member) => (
                  <li key={member.id}>{member.full_name ?? member.email}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No team members yet.</p>
            )}
          </CardContent>
        </Card>
      ) : null}

      {user?.role === 'admin' ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Team ownership</CardTitle>
            <CardDescription>Select which team owns this project.</CardDescription>
          </CardHeader>
          <CardContent>
            {teamsQuery.isError ? (
              <p className="text-sm text-destructive">Unable to load teams.</p>
            ) : (
              <form
                className="flex flex-wrap gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  updateTeamOwnership.mutate();
                }}
              >
                <div className="min-w-[220px] flex-1">
                  <Label htmlFor="project-team">Owning team</Label>
                  <Select value={selectedTeamId} onValueChange={setSelectedTeamId}>
                    <SelectTrigger id="project-team" className="mt-2">
                      <SelectValue placeholder="No team" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_TEAM_VALUE}>No team</SelectItem>
                      {teamsQuery.data?.map((team) => (
                        <SelectItem key={team.id} value={String(team.id)}>
                          {team.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-2">
                  <Button type="submit" disabled={updateTeamOwnership.isPending}>
                    {updateTeamOwnership.isPending ? 'Saving…' : 'Save team'}
                  </Button>
                  {teamMessage ? <p className="text-sm text-primary">{teamMessage}</p> : null}
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
