import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Project, Team } from '../types/api';

const NO_TEAM_VALUE = 'none';

export const ProjectsPage = () => {
  const { user } = useAuth();
  const canManageProjects = user?.role === 'admin' || user?.role === 'project_manager';
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [teamId, setTeamId] = useState<string>(NO_TEAM_VALUE);

  const projectsQuery = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>('/projects/');
      return response.data;
    },
  });

  const teamsQuery = useQuery<Team[]>({
    queryKey: ['teams'],
    enabled: user?.role === 'admin',
    queryFn: async () => {
      const response = await apiClient.get<Team[]>('/teams/');
      return response.data;
    },
  });

  const createProject = useMutation({
    mutationFn: async () => {
      const payload: { name: string; description: string; team_id?: number } = { name, description };
      if (user?.role === 'admin' && teamId !== NO_TEAM_VALUE) {
        payload.team_id = Number(teamId);
      }
      const response = await apiClient.post<Project>('/projects/', payload);
      return response.data;
    },
    onSuccess: () => {
      setName('');
      setDescription('');
      setTeamId(NO_TEAM_VALUE);
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createProject.mutate();
  };

  if (projectsQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading projects…</p>;
  }

  if (projectsQuery.isError) {
    return <p className="text-sm text-destructive">Unable to load projects.</p>;
  }

  const projects = projectsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Projects</h1>
        <p className="text-muted-foreground">Track initiatives, collaborate with your team, and move work forward.</p>
      </div>

      {canManageProjects ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Create project</CardTitle>
            <CardDescription>Give the project a name, optional description, and owning team.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="project-name">Name</Label>
                <Input
                  id="project-name"
                  placeholder="Foundation refresh"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="project-description">Description</Label>
                <Textarea
                  id="project-description"
                  placeholder="Share context to help the team prioritize."
                  rows={3}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </div>
              {user?.role === 'admin' ? (
                <div className="space-y-2">
                  <Label>Team (optional)</Label>
                  {teamsQuery.isLoading ? (
                    <p className="text-sm text-muted-foreground">Loading teams…</p>
                  ) : teamsQuery.isError ? (
                    <p className="text-sm text-destructive">Unable to load teams.</p>
                  ) : (
                    <Select value={teamId} onValueChange={setTeamId}>
                      <SelectTrigger>
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
                  )}
                </div>
              ) : null}
              <div className="flex flex-col gap-2">
                <Button type="submit" disabled={createProject.isPending}>
                  {createProject.isPending ? 'Creating…' : 'Create project'}
                </Button>
                {createProject.isError ? (
                  <p className="text-sm text-destructive">Unable to create project.</p>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        {projects.map((project) => (
          <Card key={project.id} className="shadow-sm">
            <CardHeader>
              <CardTitle className="text-xl">{project.name}</CardTitle>
              {project.description ? <CardDescription>{project.description}</CardDescription> : null}
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              {project.team ? <p>Team: {project.team.name}</p> : <p>No team yet</p>}
            </CardContent>
            <CardFooter>
              <Button asChild variant="secondary">
                <Link to={`/projects/${project.id}`}>Open board</Link>
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>

      {projects.length === 0 ? (
        <p className="text-sm text-muted-foreground">No projects yet. Create one to get started.</p>
      ) : null}
    </div>
  );
};
