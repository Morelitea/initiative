import { FormEvent, useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { Markdown } from '../components/Markdown';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Team, User } from '../types/api';

const TEAMS_QUERY_KEY = ['teams'];

export const TeamsPage = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [teamName, setTeamName] = useState('');
  const [teamDescription, setTeamDescription] = useState('');
  const NO_USER_VALUE = 'none';
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
            next[team.id] = NO_USER_VALUE;
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
    if (nextValue === undefined || !nextValue.trim()) {
      return;
    }
    updateTeam.mutate({ teamId, data: { [field]: nextValue } });
  };

  const handleDeleteTeam = (teamId: number, name: string) => {
    const confirmation = window.prompt(
      `Deleting team "${name}" will permanently delete all of its projects and tasks.\n\nType "delete" to confirm.`
    );
    if (!confirmation || confirmation.trim().toLowerCase() !== 'delete') {
      return;
    }
    deleteTeam.mutate(teamId);
  };

  const handleAddMember = (teamId: number) => {
    const value = selectedUsers[teamId];
    if (!value || value === NO_USER_VALUE) {
      return;
    }
    addTeamMember.mutate({ teamId, userId: Number(value) });
    setSelectedUsers((prev) => ({ ...prev, [teamId]: NO_USER_VALUE }));
  };

  const handleRemoveMember = (teamId: number, userId: number, email: string) => {
    if (!window.confirm(`Remove ${email} from this team?`)) {
      return;
    }
    removeTeamMember.mutate({ teamId, userId });
  };

  if (!isAdmin) {
    return <p className="text-sm text-muted-foreground">You need admin permissions to manage teams.</p>;
  }

  if (teamsQuery.isLoading || usersQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading teams…</p>;
  }

  if (teamsQuery.isError || usersQuery.isError || !teamsQuery.data || !usersQuery.data) {
    return <p className="text-sm text-destructive">Unable to load teams.</p>;
  }

  const availableUsers = (team: Team) =>
    usersQuery.data?.filter((candidate) => !team.members.some((member) => member.id === candidate.id)) ?? [];

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Create team</CardTitle>
          <CardDescription>Add a new team to own projects and members.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleCreateTeam}>
            <Input
              placeholder="Team name"
              value={teamName}
              onChange={(event) => setTeamName(event.target.value)}
              required
            />
            <Textarea
              placeholder="Description (supports Markdown)"
              value={teamDescription}
              onChange={(event) => setTeamDescription(event.target.value)}
              rows={3}
            />
            <Button type="submit" disabled={createTeam.isPending}>
              {createTeam.isPending ? 'Creating…' : 'Create team'}
            </Button>
          </form>
        </CardContent>
      </Card>

      {teamsQuery.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No teams yet.</p>
      ) : (
        teamsQuery.data.map((team) => (
          <Card key={team.id} className="shadow-sm">
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <div>
                <CardTitle>{team.name}</CardTitle>
                {team.description ? (
                  <Markdown content={team.description} className="text-sm" />
                ) : (
                  <CardDescription>No description yet.</CardDescription>
                )}
              </div>
              <div className="flex flex-col items-end gap-2">
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleTeamFieldUpdate(team.id, 'name', team.name)}
                  >
                    Rename
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleTeamFieldUpdate(team.id, 'description', team.description ?? '')}
                  >
                    Edit description
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => handleDeleteTeam(team.id, team.name)}
                    disabled={deleteTeam.isPending}
                  >
                    Delete
                  </Button>
                </div>
                <p className="text-xs text-destructive">
                  Deleting a team removes all of its projects and tasks.
                </p>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-sm font-medium">Members</p>
                {team.members.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No members yet.</p>
                ) : (
                  <div className="space-y-2">
                    {team.members.map((member) => (
                      <div
                        key={member.id}
                        className="flex items-center justify-between rounded-md border bg-card p-2 text-sm"
                      >
                        <span>
                          {member.full_name ?? member.email} ({member.email})
                        </span>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleRemoveMember(team.id, member.id, member.email)}
                          disabled={removeTeamMember.isPending}
                        >
                          Remove
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-3">
                <Select
                  value={selectedUsers[team.id] ?? NO_USER_VALUE}
                  onValueChange={(value) => setSelectedUsers((prev) => ({ ...prev, [team.id]: value }))}
                >
                  <SelectTrigger className="min-w-[200px]">
                    <SelectValue placeholder="Select user" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_USER_VALUE}>Select user</SelectItem>
                    {availableUsers(team).map((candidate) => (
                      <SelectItem key={candidate.id} value={String(candidate.id)}>
                        {candidate.full_name ?? candidate.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  onClick={() => handleAddMember(team.id)}
                  disabled={addTeamMember.isPending}
                >
                  Add member
                </Button>
              </div>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
};
