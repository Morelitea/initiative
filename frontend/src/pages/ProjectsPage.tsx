import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { FormEvent, useState } from 'react';

import { apiClient } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Project, Team } from '../types/api';

export const ProjectsPage = () => {
  const { user } = useAuth();
  const canManageProjects = user?.role === 'admin' || user?.role === 'project_manager';
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [teamId, setTeamId] = useState('');

  const projectsQuery = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>('/projects/');
      return response.data;
    },
  });

  const createProject = useMutation({
    mutationFn: async () => {
      const payload: { name: string; description: string; team_id?: number } = { name, description };
      if (user?.role === 'admin' && teamId) {
        payload.team_id = Number(teamId);
      }
      const response = await apiClient.post<Project>('/projects/', payload);
      return response.data;
    },
    onSuccess: () => {
      setName('');
      setDescription('');
      setTeamId('');
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
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

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createProject.mutate();
  };

  if (projectsQuery.isLoading) {
    return <p>Loading projects...</p>;
  }

  if (projectsQuery.isError) {
    return <p>Unable to load projects.</p>;
  }

  return (
    <div className="page">
      <h1>Projects</h1>

      {canManageProjects ? (
        <div className="card" style={{ marginBottom: '2rem' }}>
          <h2>Create project</h2>
          <form onSubmit={handleSubmit}>
            <input placeholder="Name" value={name} onChange={(event) => setName(event.target.value)} required />
            <textarea
              placeholder="Description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
            />
            {user?.role === 'admin' ? (
              <>
                <label>
                  Team (optional)
                  {teamsQuery.isLoading ? (
                    <p>Loading teams...</p>
                  ) : teamsQuery.isError ? (
                    <p>Unable to load teams.</p>
                  ) : (
                    <select value={teamId} onChange={(event) => setTeamId(event.target.value)}>
                      <option value="">No team</option>
                      {teamsQuery.data?.map((team) => (
                        <option key={team.id} value={team.id}>
                          {team.name}
                        </option>
                      ))}
                    </select>
                  )}
                </label>
              </>
            ) : null}
            <button className="primary" type="submit" disabled={createProject.isPending}>
              {createProject.isPending ? 'Creating...' : 'Create project'}
            </button>
            {createProject.isError ? <p style={{ color: 'tomato' }}>Unable to create project</p> : null}
          </form>
        </div>
      ) : null}

      <div className="list">
        {projectsQuery.data?.map((project) => (
          <div className="list-item" key={project.id}>
            <h3>{project.name}</h3>
            <p>{project.description}</p>
            {project.team ? <p>Team: {project.team.name}</p> : null}
            <Link to={`/projects/${project.id}`}>Open board →</Link>
          </div>
        ))}
      </div>
    </div>
  );
};
