import { useMutation, useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';

import { apiClient } from '../api/client';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { User, UserRole } from '../types/api';

const USERS_QUERY_KEY = ['users'];
const ROLE_OPTIONS: UserRole[] = ['admin', 'project_manager', 'member'];
const SUPER_USER_ID = 1;

export const UsersPage = () => {
  const { user: currentUser } = useAuth();
  const isAdmin = currentUser?.role === 'admin';

  const usersQuery = useQuery<User[]>({
    queryKey: USERS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<User[]>('/users/');
      return response.data;
    },
  });

  const updateUser = useMutation({
    mutationFn: async ({ userId, data }: { userId: number; data: Partial<User> & { password?: string } }) => {
      const response = await apiClient.patch<User>(`/users/${userId}`, data);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });
    },
  });

  const deleteUser = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/users/${userId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });
    },
  });

  const handleRoleChange = (userId: number, role: UserRole) => {
    if (userId === SUPER_USER_ID) {
      toast.error("You can't change the super user's role");
      return;
    }
    updateUser.mutate({ userId, data: { role } });
  };

  const handleResetPassword = (userId: number, email: string) => {
    const nextPassword = window.prompt(`Enter a new password for ${email}`);
    if (!nextPassword) {
      return;
    }
    updateUser.mutate({ userId, data: { password: nextPassword } });
  };

  const handleDeleteUser = (userId: number, email: string) => {
    if (userId === SUPER_USER_ID) {
      toast.error("You can't delete the super user");
      return;
    }
    if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) {
      return;
    }
    deleteUser.mutate(userId);
  };

  if (!isAdmin) {
    return <p className="text-sm text-muted-foreground">You need admin permissions to view this page.</p>;
  }

  if (usersQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading users…</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-sm text-destructive">Unable to load users.</p>;
  }

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Workspace users</CardTitle>
        <CardDescription>Update roles, reset passwords, or remove accounts.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {usersQuery.data.map((user) => {
          const isSuperUser = user.id === SUPER_USER_ID;
          return (
          <div
            className="flex flex-wrap items-center justify-between gap-4 rounded-lg border bg-card p-4"
            key={user.id}
          >
            <div>
              <p className="font-medium">{user.full_name ?? user.email}</p>
              <p className="text-sm text-muted-foreground">{user.email}</p>
              <p className="text-xs text-muted-foreground">
                Status: {user.is_active ? 'Active' : 'Pending approval'}
              </p>
            </div>
            <div className="flex flex-col gap-2 min-w-[220px]">
              <Select
                value={user.role}
                onValueChange={(value) => handleRoleChange(user.id, value as UserRole)}
                disabled={isSuperUser}
              >
                <SelectTrigger disabled={isSuperUser}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.map((roleOption) => (
                    <SelectItem key={roleOption} value={roleOption}>
                      {roleOption.replace('_', ' ')}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleResetPassword(user.id, user.email)}
                disabled={updateUser.isPending}
              >
                Reset password
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => handleDeleteUser(user.id, user.email)}
                disabled={
                  isSuperUser || deleteUser.isPending || currentUser?.id === user.id
                }
              >
                Delete user
              </Button>
            </div>
          </div>
        );
        })}
      </CardContent>
    </Card>
  );
};
