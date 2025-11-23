import { Outlet, useLocation, useNavigate } from 'react-router-dom';

import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs';
import { useAuth } from '../hooks/useAuth';

const settingsTabs = [
  { value: 'registration', label: 'Registration', path: '/settings' },
  { value: 'users', label: 'Users', path: '/settings/users' },
  { value: 'teams', label: 'Teams', path: '/settings/teams' },
  { value: 'auth', label: 'Auth', path: '/settings/auth' },
  { value: 'api-keys', label: 'API Keys', path: '/settings/api-keys' },
  { value: 'interface', label: 'Interface', path: '/settings/interface' },
];

export const SettingsLayout = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const location = useLocation();
  const navigate = useNavigate();

  if (!isAdmin) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">You need admin permissions to view this page.</p>
      </div>
    );
  }

  const normalizedPath = location.pathname.replace(/\/+$/, '') || '/';
  const tabsBySpecificity = [...settingsTabs].sort((a, b) => b.path.length - a.path.length);
  const activeTab =
    tabsBySpecificity.find(
      (tab) => normalizedPath === tab.path || normalizedPath.startsWith(`${tab.path}/`)
    )?.value ?? 'registration';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage workspace access, teams, and authentication.</p>
      </div>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          const tab = settingsTabs.find((item) => item.value === value);
          if (tab) {
            navigate(tab.path);
          }
        }}
      >
        <div className="-mx-4 overflow-x-auto pb-2 md:mx-0 md:overflow-visible">
          <TabsList className="w-full min-w-max justify-start gap-2 px-1 md:min-w-0">
            {settingsTabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="shrink-0">
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </Tabs>
      <Outlet />
    </div>
  );
};
