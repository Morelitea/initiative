import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';

import { ProtectedRoute } from './components/ProtectedRoute';
import { useAuth } from './hooks/useAuth';
import { ArchivePage } from './pages/ArchivePage';
import { LoginPage } from './pages/LoginPage';
import { OidcCallbackPage } from './pages/OidcCallbackPage';
import { ProjectDetailPage } from './pages/ProjectDetailPage';
import { ProjectSettingsPage } from './pages/ProjectSettingsPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { RegisterPage } from './pages/RegisterPage';
import { SettingsAuthPage } from './pages/SettingsAuthPage';
import { SettingsLayout } from './pages/SettingsLayout';
import { SettingsPage } from './pages/SettingsPage';
import { TeamsPage } from './pages/TeamsPage';
import { UsersPage } from './pages/UsersPage';

const AppLayout = () => {
  const { user, logout } = useAuth();

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="logo">
          Pour Priority
        </Link>
        <nav className="app-nav">
          <Link to="/">Projects</Link>
          <Link to="/archive">Archive</Link>
          {user?.role === 'admin' ? <Link to="/settings">Settings</Link> : null}
        </nav>
        <div className="spacer" />
        {user ? (
          <div className="user-meta">
            <span>{user.full_name ?? user.email}</span>
            <button onClick={logout}>Sign out</button>
          </div>
        ) : null}
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
          <Route path="/archive" element={<ArchivePage />} />
          <Route path="/settings/*" element={<SettingsLayout />}>
            <Route index element={<SettingsPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="teams" element={<TeamsPage />} />
            <Route path="auth" element={<SettingsAuthPage />} />
          </Route>
        </Routes>
      </main>
    </div>
  );
};

export const App = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/oidc/callback" element={<OidcCallbackPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/*" element={<AppLayout />} />
      </Route>
    </Routes>
  </BrowserRouter>
);
