import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom';

import { ModeToggle } from './components/ModeToggle';
import { ProtectedRoute } from './components/ProtectedRoute';
import { Button } from './components/ui/button';
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
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b bg-card/80 backdrop-blur supports-[backdrop-filter]:bg-card/60">
        <div className="container flex h-16 items-center gap-6">
          <Link to="/" className="text-lg font-semibold tracking-tight text-foreground">
            Pour Priority
          </Link>
          <nav className="flex items-center gap-4 text-sm font-medium text-muted-foreground">
            <NavLink
              to="/"
              end
              className={({ isActive }) => (isActive ? 'text-foreground' : undefined)}
            >
              Projects
            </NavLink>
            <NavLink
              to="/archive"
              className={({ isActive }) => (isActive ? 'text-foreground' : undefined)}
            >
              Archive
            </NavLink>
            {user?.role === 'admin' ? (
              <NavLink
                to="/settings"
                className={({ isActive }) => (isActive ? 'text-foreground' : undefined)}
              >
                Settings
              </NavLink>
            ) : null}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <ModeToggle />
            {user ? (
              <>
                <span className="text-sm text-muted-foreground">{user.full_name ?? user.email}</span>
                <Button variant="outline" onClick={logout}>
                  Sign out
                </Button>
              </>
            ) : null}
          </div>
        </div>
      </header>
      <main className="flex-1 bg-muted/50">
        <div className="container py-8">
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
        </div>
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
