import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { User, UserRole } from '../types/api';

const USERS_QUERY_KEY = ['users'];
const ROLE_OPTIONS: UserRole[] = ['admin', 'project_manager', 'member'];

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
    if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) {
      return;
    }
    deleteUser.mutate(userId);
  };

  if (!isAdmin) {
    return <p>You need admin permissions to view this page.</p>;
  }

  if (usersQuery.isLoading) {
    return <p>Loading users...</p>;
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p>Unable to load users.</p>;
  }

  return (
    <div className="settings-section">
      <div className="card">
        <div className="list">
          {usersQuery.data.map((user) => (
            <div className="list-item" key={user.id}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
                <div>
                  <strong>{user.full_name ?? user.email}</strong>
                  <p>{user.email}</p>
                  <p>Status: {user.is_active ? 'Active' : 'Pending approval'}</p>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', minWidth: '200px' }}>
                  <label>
                    Role
                    <select
                      value={user.role}
                      onChange={(event) => handleRoleChange(user.id, event.target.value as UserRole)}
                      disabled={updateUser.isPending}
                    >
                      {ROLE_OPTIONS.map((roleOption) => (
                        <option key={roleOption} value={roleOption}>
                          {roleOption.replace('_', ' ')}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="secondary"
                    type="button"
                    onClick={() => handleResetPassword(user.id, user.email)}
                    disabled={updateUser.isPending}
                  >
                    Reset password
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    onClick={() => handleDeleteUser(user.id, user.email)}
                    disabled={deleteUser.isPending || currentUser?.id === user.id}
                    style={{ borderColor: '#dc2626', color: '#dc2626' }}
                  >
                    Delete user
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
