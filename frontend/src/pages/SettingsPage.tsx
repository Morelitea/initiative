import { FormEvent, useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { RegistrationSettings } from '../types/api';

const REGISTRATION_SETTINGS_QUERY_KEY = ['registration-settings'];

export const SettingsPage = () => {
  const { user } = useAuth();
  const [domainsInput, setDomainsInput] = useState('');

  const isAdmin = user?.role === 'admin';

  const settingsQuery = useQuery<RegistrationSettings>({
    queryKey: REGISTRATION_SETTINGS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<RegistrationSettings>('/settings/registration');
      return response.data;
    },
  });

  useEffect(() => {
    if (settingsQuery.data) {
      setDomainsInput(settingsQuery.data.auto_approved_domains.join(', '));
    }
  }, [settingsQuery.data]);

  const updateAllowList = useMutation({
    mutationFn: async (domains: string[]) => {
      const response = await apiClient.put<RegistrationSettings>('/settings/registration', {
        auto_approved_domains: domains,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setDomainsInput(data.auto_approved_domains.join(', '));
      queryClient.setQueryData(REGISTRATION_SETTINGS_QUERY_KEY, data);
    },
  });

  const approveUser = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.post(`/users/${userId}/approve`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: REGISTRATION_SETTINGS_QUERY_KEY });
    },
  });

  if (!isAdmin) {
    return <p>You need admin permissions to view this page.</p>;
  }

  if (settingsQuery.isLoading) {
    return <p>Loading settings...</p>;
  }

  if (settingsQuery.isError || !settingsQuery.data) {
    return <p>Unable to load settings.</p>;
  }

  const handleDomainsSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const domains = domainsInput
      .split(',')
      .map((domain) => domain.trim().toLowerCase())
      .filter(Boolean);
    updateAllowList.mutate(domains);
  };

  return (
    <div className="settings-section">
      <div className="card">
        <h2>Auto-approved email domains</h2>
        <p>Enter a comma-separated list of domains that should be auto-approved when users register.</p>
        <form onSubmit={handleDomainsSubmit}>
          <input
            type="text"
            value={domainsInput}
            onChange={(event) => setDomainsInput(event.target.value)}
            placeholder="example.com, company.org"
          />
          <button className="primary" type="submit" disabled={updateAllowList.isPending}>
            {updateAllowList.isPending ? 'Saving...' : 'Save allow list'}
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Pending users</h2>
        {settingsQuery.data.pending_users.length === 0 ? (
          <p>No pending accounts.</p>
        ) : (
          <div className="list">
            {settingsQuery.data.pending_users.map((pendingUser) => (
              <div className="list-item" key={pendingUser.id}>
                <strong>{pendingUser.full_name ?? pendingUser.email}</strong>
                <p>{pendingUser.email}</p>
                <button
                  className="primary"
                  type="button"
                  onClick={() => approveUser.mutate(pendingUser.id)}
                  disabled={approveUser.isPending}
                >
                  Approve
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
