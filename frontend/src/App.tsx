import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";

import { ModeToggle } from "./components/ModeToggle";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Avatar, AvatarFallback, AvatarImage } from "./components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./components/ui/dropdown-menu";
import { useAuth } from "./hooks/useAuth";
import { useRealtimeUpdates } from "./hooks/useRealtimeUpdates";
import { LoginPage } from "./pages/LoginPage";
import { OidcCallbackPage } from "./pages/OidcCallbackPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectSettingsPage } from "./pages/ProjectSettingsPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { MyTasksPage } from "./pages/MyTasksPage";
import { RegisterPage } from "./pages/RegisterPage";
import { SettingsAuthPage } from "./pages/SettingsAuthPage";
import { SettingsLayout } from "./pages/SettingsLayout";
import { SettingsPage } from "./pages/SettingsPage";
import { TeamsPage } from "./pages/TeamsPage";
import { UsersPage } from "./pages/UsersPage";
import { TaskEditPage } from "./pages/TaskEditPage";
import { UserProfilePage } from "./pages/UserProfilePage";

const AppLayout = () => {
  const { user, logout } = useAuth();
  const userDisplayName = user?.full_name ?? user?.email ?? "Team member";
  const userEmail = user?.email ?? "";
  const userInitials =
    userDisplayName
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
      .slice(0, 2) || "PP";
  const avatarSrc = user?.avatar_url || user?.avatar_base64 || null;
  useRealtimeUpdates();

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b bg-card/80 backdrop-blur supports-[backdrop-filter]:bg-card/60">
        <div className="container flex h-16 items-center gap-6">
          <Link
            to="/"
            className="flex items-center gap-3 text-lg font-semibold tracking-tight text-foreground"
          >
            <img src="/icons/logo.svg" alt="" className="h-8 w-8" />
            Pour Priority
          </Link>
          <nav className="flex items-center gap-4 text-sm font-medium text-muted-foreground">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                isActive ? "text-foreground" : undefined
              }
            >
              Projects
            </NavLink>
            <NavLink
              to="/tasks"
              className={({ isActive }) =>
                isActive ? "text-foreground" : undefined
              }
            >
              My Tasks
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <ModeToggle />
            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="rounded-full border bg-card p-0.5 transition hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    aria-label="Account menu"
                  >
                    <Avatar>
                      {avatarSrc ? (
                        <AvatarImage src={avatarSrc} alt={userDisplayName} />
                      ) : null}
                      <AvatarFallback>{userInitials}</AvatarFallback>
                    </Avatar>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel className="font-normal">
                    <div className="flex flex-col space-y-1">
                      <p className="text-sm font-medium leading-none">
                        {userDisplayName}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {userEmail}
                      </p>
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link to="/profile">Profile Settings</Link>
                  </DropdownMenuItem>
                  {user?.role === "admin" ? (
                    <DropdownMenuItem asChild>
                      <Link to="/settings">Admin Settings</Link>
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => logout()}>
                    Sign out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        </div>
      </header>
      <main className="flex-1 bg-muted/50">
        <div className="container py-8">
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route
              path="/projects/:projectId"
              element={<ProjectDetailPage />}
            />
            <Route
              path="/projects/:projectId/settings"
              element={<ProjectSettingsPage />}
            />
            <Route path="/tasks/:taskId/edit" element={<TaskEditPage />} />
            <Route path="/tasks" element={<MyTasksPage />} />
            <Route path="/profile" element={<UserProfilePage />} />
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
