import { useMutation, useQuery } from '@tanstack/react-query';
import { FormEvent, useEffect, useState } from 'react';

import { apiClient } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Team, User } from '../types/api';

const TEAMS_QUERY_KEY = ['teams'];

export const TeamsPage = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [teamName, setTeamName] = useState('');
  const [teamDescription, setTeamDescription] = useState('');
  const [selectedUsers, setSelectedUsers] = useState<Record<number, string>>({});

  const teamsQuery = useQuery<Team[]>({
    queryKey: TEAMS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<Team[]>('/teams/');
      return response.data;
    },
  });

  const usersQuery = useQuery<User[]>({
    queryKey: ['users'],
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<User[]>('/users/');
      return response.data;
    },
  });

  const createTeam = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<Team>('/teams/', { name: teamName, description: teamDescription });
      return response.data;
    },
    onSuccess: () => {
      setTeamName('');
      setTeamDescription('');
      void queryClient.invalidateQueries({ queryKey: TEAMS_QUERY_KEY });
    },
  });

  const updateTeam = useMutation({
    mutationFn: async ({ teamId, data }: { teamId: number; data: { name?: string; description?: string } }) => {
      const response = await apiClient.patch<Team>(`/teams/${teamId}`, data);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEAMS_QUERY_KEY });
    },
  });

  const deleteTeam = useMutation({
    mutationFn: async (teamId: number) => {
      await apiClient.delete(`/teams/${teamId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEAMS_QUERY_KEY });
    },
  });

  const addTeamMember = useMutation({
    mutationFn: async ({ teamId, userId }: { teamId: number; userId: number }) => {
      const response = await apiClient.post<Team>(`/teams/${teamId}/members`, { user_id: userId });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEAMS_QUERY_KEY });
    },
  });

  const removeTeamMember = useMutation({
    mutationFn: async ({ teamId, userId }: { teamId: number; userId: number }) => {
      const response = await apiClient.delete<Team>(`/teams/${teamId}/members/${userId}`);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEAMS_QUERY_KEY });
    },
  });

  useEffect(() => {
    if (teamsQuery.data) {
      setSelectedUsers((prev) => {
        const next = { ...prev };
        for (const team of teamsQuery.data) {
          if (!(team.id in next)) {
            next[team.id] = '';
          }
        }
        return next;
      });
    }
  }, [teamsQuery.data]);

  const handleCreateTeam = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!teamName.trim()) {
      return;
    }
    createTeam.mutate();
  };

  const handleTeamFieldUpdate = (teamId: number, field: 'name' | 'description', currentValue: string) => {
    const nextValue = window.prompt(`Update team ${field}`, currentValue) ?? undefined;
    if (nextValue === undefined) {
      return;
    }
    if (!nextValue.trim()) {
      return;
    }
    updateTeam.mutate({ teamId, data: { [field]: nextValue } });
  };

  const handleDeleteTeam = (teamId: number, name: string) => {
    if (!window.confirm(`Delete team "${name}"? This cannot be undone.`)) {
      return;
    }
    deleteTeam.mutate(teamId);
  };

  const handleAddMember = (teamId: number) => {
    const value = selectedUsers[teamId];
    if (!value) {
      return;
    }
    addTeamMember.mutate({ teamId, userId: Number(value) });
    setSelectedUsers((prev) => ({ ...prev, [teamId]: '' }));
  };

  const handleRemoveMember = (teamId: number, userId: number, email: string) => {
    if (!window.confirm(`Remove ${email} from this team?`)) {
      return;
    }
    removeTeamMember.mutate({ teamId, userId });
  };

  if (!isAdmin) {
    return <p>You need admin permissions to manage teams.</p>;
  }

  if (teamsQuery.isLoading || usersQuery.isLoading) {
    return <p>Loading teams...</p>;
  }

  if (teamsQuery.isError || usersQuery.isError || !teamsQuery.data || !usersQuery.data) {
    return <p>Unable to load teams.</p>;
  }

  const availableUsers = (team: Team) =>
    usersQuery.data?.filter((candidate) => !team.members.some((member) => member.id === candidate.id)) ?? [];

  return (
    <div className="settings-section">
      <div className="card">
        <h2>Create team</h2>
        <form onSubmit={handleCreateTeam}>
          <input
            placeholder="Team name"
            value={teamName}
            onChange={(event) => setTeamName(event.target.value)}
            required
          />
          <input
            placeholder="Description"
            value={teamDescription}
            onChange={(event) => setTeamDescription(event.target.value)}
          />
          <button className="primary" type="submit" disabled={createTeam.isPending}>
            {createTeam.isPending ? 'Creating...' : 'Create team'}
          </button>
        </form>
      </div>

      {teamsQuery.data.length === 0 ? <p>No teams yet.</p> : null}

      {teamsQuery.data.map((team) => (
        <div className="card" key={team.id}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
            <div>
              <h3>{team.name}</h3>
              <p>{team.description}</p>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button className="secondary" type="button" onClick={() => handleTeamFieldUpdate(team.id, 'name', team.name)}>
                Rename
              </button>
              <button
                className="secondary"
                type="button"
                onClick={() => handleTeamFieldUpdate(team.id, 'description', team.description ?? '')}
              >
                Edit description
              </button>
              <button
                className="secondary"
                type="button"
                onClick={() => handleDeleteTeam(team.id, team.name)}
                style={{ borderColor: '#dc2626', color: '#dc2626' }}
              >
                Delete
              </button>
            </div>
          </div>

          <div style={{ marginTop: '1rem' }}>
            <strong>Members</strong>
            {team.members.length === 0 ? <p>No members yet.</p> : null}
            <div className="list">
              {team.members.map((member) => (
                <div className="list-item" key={member.id} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>
                    {member.full_name ?? member.email} ({member.email})
                  </span>
                  <button
                    className="secondary"
                    type="button"
                    onClick={() => handleRemoveMember(team.id, member.id, member.email)}
                    disabled={removeTeamMember.isPending}
                    style={{ borderColor: '#dc2626', color: '#dc2626' }}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
            <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
              <select
                value={selectedUsers[team.id] ?? ''}
                onChange={(event) => setSelectedUsers((prev) => ({ ...prev, [team.id]: event.target.value }))}
              >
                <option value="">Select user</option>
                {availableUsers(team).map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.full_name ?? candidate.email}
                  </option>
                ))}
              </select>
              <button
                className="primary"
                type="button"
                onClick={() => handleAddMember(team.id)}
                disabled={addTeamMember.isPending}
              >
                Add member
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};
