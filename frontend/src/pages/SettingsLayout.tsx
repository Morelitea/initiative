import { NavLink, Outlet } from 'react-router-dom';

import { useAuth } from '../hooks/useAuth';

export const SettingsLayout = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  if (!isAdmin) {
    return (
      <div className="page">
        <h1>Settings</h1>
        <p>You need admin permissions to view this page.</p>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>Settings</h1>
      <div className="settings-nav">
        <NavLink to="/settings" end>
          Registration
        </NavLink>
        <NavLink to="/settings/users">Users</NavLink>
        <NavLink to="/settings/teams">Teams</NavLink>
        <NavLink to="/settings/auth">Auth</NavLink>
      </div>
      <Outlet />
    </div>
  );
};
