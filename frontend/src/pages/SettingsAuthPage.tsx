import { useMutation, useQuery } from '@tanstack/react-query';
import { FormEvent, useEffect, useState } from 'react';

import { apiClient } from '../api/client';

interface OidcSettings {
  enabled: boolean;
  discovery_url?: string | null;
  client_id?: string | null;
  redirect_uri?: string | null;
  post_login_redirect?: string | null;
  provider_name?: string | null;
  scopes: string[];
}

export const SettingsAuthPage = () => {
  const [clientSecret, setClientSecret] = useState('');
  const [formState, setFormState] = useState({
    enabled: false,
    discovery_url: '',
    client_id: '',
    provider_name: '',
    scopes: 'openid profile email',
  });

  const oidcQuery = useQuery<OidcSettings>({
    queryKey: ['settings', 'oidc'],
    queryFn: async () => {
      const response = await apiClient.get<OidcSettings>('/settings/auth');
      return response.data;
    },
  });

  const updateOidcSettings = useMutation({
    mutationFn: async (payload: OidcSettings & { client_secret?: string }) => {
      const response = await apiClient.put<OidcSettings>('/settings/auth', payload);
      return response.data;
    },
    onSuccess: () => {
      void oidcQuery.refetch();
      setClientSecret('');
    },
  });

  useEffect(() => {
    if (oidcQuery.data) {
      const settings = oidcQuery.data;
      setFormState({
        enabled: settings.enabled,
        discovery_url: settings.discovery_url ?? '',
        client_id: settings.client_id ?? '',
        provider_name: settings.provider_name ?? '',
        scopes: settings.scopes.join(' '),
      });
    }
  }, [oidcQuery.data]);

  if (oidcQuery.isLoading) {
    return <p>Loading auth settings...</p>;
  }

  if (oidcQuery.isError || !oidcQuery.data) {
    return <p>Unable to load auth settings.</p>;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateOidcSettings.mutate({
      enabled: formState.enabled,
      discovery_url: formState.discovery_url || null,
      client_id: formState.client_id || null,
      provider_name: formState.provider_name || null,
      scopes: formState.scopes.split(/[\s,]+/).filter(Boolean),
      client_secret: clientSecret || undefined,
    });
  };

  return (
    <div className="settings-section">
      <div className="card">
        <h2>OIDC authentication</h2>
        <form onSubmit={handleSubmit}>
          <label>
            <span>Enabled</span>
            <input
              type="checkbox"
              checked={formState.enabled}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  enabled: event.target.checked,
                }))
              }
            />
          </label>
          <label>
            <span>Discovery URL</span>
            <input
              type="url"
              value={formState.discovery_url}
              onChange={(event) => setFormState((prev) => ({ ...prev, discovery_url: event.target.value }))}
            />
          </label>
          <label>
            <span>Client ID</span>
            <input
              value={formState.client_id}
              onChange={(event) => setFormState((prev) => ({ ...prev, client_id: event.target.value }))}
            />
          </label>
          <label>
            <span>Client secret</span>
            <input value={clientSecret} onChange={(event) => setClientSecret(event.target.value)} type="password" />
            <small>Leave blank to keep existing secret.</small>
          </label>
          <label>
            <span>Provider name</span>
            <input
              value={formState.provider_name}
              onChange={(event) => setFormState((prev) => ({ ...prev, provider_name: event.target.value }))}
            />
          </label>
          <label>
            <span>Scopes</span>
            <input
              value={formState.scopes}
              onChange={(event) => setFormState((prev) => ({ ...prev, scopes: event.target.value }))}
            />
          </label>
          <button className="primary" type="submit" disabled={updateOidcSettings.isPending}>
            {updateOidcSettings.isPending ? 'Saving...' : 'Save auth settings'}
          </button>
        </form>
        <div style={{ marginTop: '1rem', fontSize: '0.9rem' }}>
          <p>
            Authorization callback:{' '}
            <code>{oidcQuery.data.redirect_uri}</code>
          </p>
          <p>
            Post-login redirect:{' '}
            <code>{oidcQuery.data.post_login_redirect}</code>
          </p>
        </div>
      </div>
    </div>
  );
};
