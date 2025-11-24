import { Suspense, lazy } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ModeToggle } from "./components/ModeToggle";
import { LogoIcon } from "./components/LogoIcon";
import { MobileMenu, type NavItem } from "./components/MobileMenu";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { ProjectShortcutsSidebar } from "./components/projects/ProjectShortcutsSidebar";
import { ProjectTabsBar } from "./components/projects/ProjectTabsBar";
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
import { useInterfaceColors } from "./hooks/useInterfaceColors";
import { apiClient } from "./api/client";
import type { Project } from "./types/api";
const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((module) => ({ default: module.LoginPage }))
);
const RegisterPage = lazy(() =>
  import("./pages/RegisterPage").then((module) => ({
    default: module.RegisterPage,
  }))
);
const OidcCallbackPage = lazy(() =>
  import("./pages/OidcCallbackPage").then((module) => ({
    default: module.OidcCallbackPage,
  }))
);
const ProjectsPage = lazy(() =>
  import("./pages/ProjectsPage").then((module) => ({
    default: module.ProjectsPage,
  }))
);
const ProjectDetailPage = lazy(() =>
  import("./pages/ProjectDetailPage").then((module) => ({
    default: module.ProjectDetailPage,
  }))
);
const ProjectSettingsPage = lazy(() =>
  import("./pages/ProjectSettingsPage").then((module) => ({
    default: module.ProjectSettingsPage,
  }))
);
const TaskEditPage = lazy(() =>
  import("./pages/TaskEditPage").then((module) => ({
    default: module.TaskEditPage,
  }))
);
const MyTasksPage = lazy(() =>
  import("./pages/MyTasksPage").then((module) => ({
    default: module.MyTasksPage,
  }))
);
const UserSettingsPage = lazy(() =>
  import("./pages/UserSettingsPage").then((module) => ({
    default: module.UserSettingsPage,
  }))
);
const SettingsLayout = lazy(() =>
  import("./pages/SettingsLayout").then((module) => ({
    default: module.SettingsLayout,
  }))
);
const SettingsPage = lazy(() =>
  import("./pages/SettingsPage").then((module) => ({
    default: module.SettingsPage,
  }))
);
const SettingsAuthPage = lazy(() =>
  import("./pages/SettingsAuthPage").then((module) => ({
    default: module.SettingsAuthPage,
  }))
);
const SettingsApiKeysPage = lazy(() =>
  import("./pages/SettingsApiKeysPage").then((module) => ({
    default: module.SettingsApiKeysPage,
  }))
);
const SettingsInterfacePage = lazy(() =>
  import("./pages/SettingsInterfacePage").then((module) => ({
    default: module.SettingsInterfacePage,
  }))
);
const InitiativesPage = lazy(() =>
  import("./pages/InitiativesPage").then((module) => ({
    default: module.InitiativesPage,
  }))
);
const UsersPage = lazy(() =>
  import("./pages/UsersPage").then((module) => ({ default: module.UsersPage }))
);

const AppLayout = () => {
  const { user, logout } = useAuth();
  const userDisplayName = user?.full_name ?? user?.email ?? "Initiative member";
  const userEmail = user?.email ?? "";
  const userInitials =
    userDisplayName
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
      .slice(0, 2) || "PP";
  const avatarSrc = user?.avatar_url || user?.avatar_base64 || null;
  useRealtimeUpdates();
  useInterfaceColors();
  const navItems: NavItem[] = [
    { label: "Projects", to: "/", end: true },
    { label: "My Tasks", to: "/tasks" },
  ];

  const location = useLocation();
  const queryClient = useQueryClient();
  const showSidebarPref = !!user && (user.show_project_sidebar ?? true);
  const showTabsPref = !!user && (user.show_project_tabs ?? false);
  const shouldFetchFavorites = Boolean(user && showSidebarPref);
  const shouldFetchRecents = Boolean(user && (showSidebarPref || showTabsPref));

  const favoritesQuery = useQuery<Project[]>({
    queryKey: ["projects", "favorites"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/favorites");
      return response.data;
    },
    enabled: shouldFetchFavorites,
    staleTime: 60_000,
  });

  const recentQuery = useQuery<Project[]>({
    queryKey: ["projects", "recent"],
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/recent");
      return response.data;
    },
    enabled: shouldFetchRecents,
    staleTime: 30_000,
  });

  const clearRecent = useMutation({
    mutationFn: async (projectId: number) => {
      await apiClient.delete(`/projects/${projectId}/view`);
      return projectId;
    },
    onSuccess: (projectId) => {
      void queryClient.invalidateQueries({ queryKey: ["projects", "recent"] });
      if (projectId) {
        void queryClient.invalidateQueries({
          queryKey: ["projects", projectId],
        });
      }
    },
  });

  const handleClearRecent = (projectId: number) => {
    clearRecent.mutate(projectId);
  };

  const activeProjectMatch = location.pathname.match(/^\/projects\/(\d+)/);
  const activeProjectId = activeProjectMatch
    ? Number(activeProjectMatch[1])
    : null;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-40 border-b bg-card/80 backdrop-blur supports-[backdrop-filter]:bg-card/60">
        <div className="flex h-16 items-center gap-3 px-4 md:px-8">
          <MobileMenu navItems={navItems} user={user} onLogout={logout} />
          <Link
            to="/"
            className="flex items-center gap-3 text-lg font-semibold tracking-tight text-primary"
          >
            <LogoIcon
              className="h-8 w-8"
              aria-hidden="true"
              focusable="false"
            />
            initiative
          </Link>
          <nav className="hidden items-center gap-4 text-sm font-medium text-muted-foreground md:flex">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  isActive ? "text-foreground" : undefined
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-3 md:flex">
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
                    <Link to="/profile">User Settings</Link>
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
      {showTabsPref ? (
        <ProjectTabsBar
          projects={recentQuery.data}
          loading={recentQuery.isLoading}
          activeProjectId={activeProjectId}
          onClose={handleClearRecent}
        />
      ) : null}
      <div className="flex flex-1">
        {showSidebarPref ? (
          <ProjectShortcutsSidebar
            favorites={favoritesQuery.data}
            recent={recentQuery.data}
            loading={favoritesQuery.isLoading || recentQuery.isLoading}
            onClearRecent={handleClearRecent}
          />
        ) : null}
        <main className="flex-1 bg-muted/50 pb-20">
          <div className="container p-4 md:p-8">
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
              <Route path="/profile" element={<UserSettingsPage />} />
              <Route path="/settings/*" element={<SettingsLayout />}>
                <Route index element={<SettingsPage />} />
                <Route path="users" element={<UsersPage />} />
              <Route path="initiatives" element={<InitiativesPage />} />
                <Route path="auth" element={<SettingsAuthPage />} />
                <Route path="api-keys" element={<SettingsApiKeysPage />} />
                <Route path="interface" element={<SettingsInterfacePage />} />
              </Route>
            </Routes>
          </div>
        </main>
      </div>
    </div>
  );
};

export const App = () => (
  <BrowserRouter>
    <Suspense
      fallback={
        <div className="py-10 text-center text-muted-foreground">
          Loading...
        </div>
      }
    >
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/oidc/callback" element={<OidcCallbackPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/*" element={<AppLayout />} />
        </Route>
      </Routes>
    </Suspense>
  </BrowserRouter>
);
