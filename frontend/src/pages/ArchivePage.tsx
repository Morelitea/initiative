import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Project } from '../types/api';

export const ArchivePage = () => {
  const { user } = useAuth();
  const canManageProjects = user?.role === 'admin' || user?.role === 'project_manager';

  const archivedProjectsQuery = useQuery<Project[]>({
    queryKey: ['projects', 'archived'],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>('/projects/', { params: { archived: true } });
      return response.data;
    },
  });

  const unarchiveProject = useMutation({
    mutationFn: async (projectId: number) => {
      await apiClient.post(`/projects/${projectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['projects', 'archived'] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  if (archivedProjectsQuery.isLoading) {
    return <p>Loading archived projects...</p>;
  }

  if (archivedProjectsQuery.isError) {
    return <p>Unable to load archived projects.</p>;
  }

  const projects = archivedProjectsQuery.data ?? [];

  return (
    <div className="page">
      <h1>Archived projects</h1>
      {projects.length === 0 ? <p>No archived projects.</p> : null}

      <div className="list">
        {projects.map((project) => (
          <div className="list-item" key={project.id}>
            <h3>{project.name}</h3>
            <p>{project.description}</p>
            {project.team ? <p>Team: {project.team.name}</p> : null}
            <p>Archived at: {project.archived_at ? new Date(project.archived_at).toLocaleString() : '—'}</p>
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <Link to={`/projects/${project.id}`}>View details →</Link>
              {canManageProjects ? (
                <button
                  className="secondary"
                  type="button"
                  onClick={() => unarchiveProject.mutate(project.id)}
                  disabled={unarchiveProject.isPending}
                >
                  Unarchive
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
