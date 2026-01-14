import { lazy, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

const PAGE_TRANSITION_DURATION_MS = 300;

type TransitionStage = "fadeIn" | "fadeOut";

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
const DocumentsPage = lazy(() =>
  import("./pages/DocumentsPage").then((module) => ({
    default: module.DocumentsPage,
  }))
);
const InitiativesPage = lazy(() =>
  import("./pages/InitiativesPage").then((module) => ({
    default: module.InitiativesPage,
  }))
);
const InitiativeDetailPage = lazy(() =>
  import("./pages/InitiativeDetailPage").then((module) => ({
    default: module.InitiativeDetailPage,
  }))
);
const InitiativeSettingsPage = lazy(() =>
  import("./pages/InitiativeSettingsPage").then((module) => ({
    default: module.InitiativeSettingsPage,
  }))
);
const DocumentDetailPage = lazy(() =>
  import("./pages/DocumentDetailPage").then((module) => ({
    default: module.DocumentDetailPage,
  }))
);
const DocumentSettingsPage = lazy(() =>
  import("./pages/DocumentSettingsPage").then((module) => ({
    default: module.DocumentSettingsPage,
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
const GuildSettingsLayout = lazy(() =>
  import("./pages/GuildSettingsLayout").then((module) => ({
    default: module.GuildSettingsLayout,
  }))
);
const AdminSettingsLayout = lazy(() =>
  import("./pages/AdminSettingsLayout").then((module) => ({
    default: module.AdminSettingsLayout,
  }))
);
const SettingsUsersPage = lazy(() =>
  import("./pages/SettingsUsersPage").then((module) => ({
    default: module.SettingsUsersPage,
  }))
);
const SettingsPlatformUsersPage = lazy(() =>
  import("./pages/SettingsPlatformUsersPage").then((module) => ({
    default: module.SettingsPlatformUsersPage,
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
const SettingsBrandingPage = lazy(() =>
  import("./pages/SettingsBrandingPage").then((module) => ({
    default: module.SettingsBrandingPage,
  }))
);
const SettingsEmailPage = lazy(() =>
  import("./pages/SettingsEmailPage").then((module) => ({
    default: module.SettingsEmailPage,
  }))
);
const SettingsGuildPage = lazy(() =>
  import("./pages/SettingsGuildPage").then((module) => ({
    default: module.SettingsGuildPage,
  }))
);
const UserSettingsLayout = lazy(() =>
  import("./pages/UserSettingsLayout").then((module) => ({
    default: module.UserSettingsLayout,
  }))
);
const UserSettingsProfilePage = lazy(() =>
  import("./pages/UserSettingsProfilePage").then((module) => ({
    default: module.UserSettingsProfilePage,
  }))
);
const UserSettingsInterfacePage = lazy(() =>
  import("./pages/UserSettingsInterfacePage").then((module) => ({
    default: module.UserSettingsInterfacePage,
  }))
);
const UserSettingsNotificationsPage = lazy(() =>
  import("./pages/UserSettingsNotificationsPage").then((module) => ({
    default: module.UserSettingsNotificationsPage,
  }))
);
const UserSettingsDangerZonePage = lazy(() =>
  import("./pages/UserSettingsDangerZonePage").then((module) => ({
    default: module.UserSettingsDangerZonePage,
  }))
);
const UserSettingsImportPage = lazy(() =>
  import("./pages/UserSettingsImportPage").then((module) => ({
    default: module.UserSettingsImportPage,
  }))
);
const UserStatsPage = lazy(() =>
  import("./pages/UserStatsPage").then((module) => ({
    default: module.UserStatsPage,
  }))
);

export const PageRoutes = () => {
  const location = useLocation();
  const { user, refreshUser, logout } = useAuth();
  // Keep rendering the previous route until the fade-out completes.
  const [displayLocation, setDisplayLocation] = useState(location);
  const [transitionStage, setTransitionStage] = useState<TransitionStage>("fadeIn");
  const locationKey = location.key ?? `${location.pathname}${location.search}${location.hash}`;
  const displayKey =
    displayLocation.key ??
    `${displayLocation.pathname}${displayLocation.search}${displayLocation.hash}`;

  useEffect(() => {
    if (locationKey !== displayKey) {
      setTransitionStage("fadeOut");
    }
  }, [locationKey, displayKey]);

  useEffect(() => {
    if (transitionStage !== "fadeOut") {
      return;
    }

    const timeout = window.setTimeout(() => {
      setDisplayLocation(location);
      setTransitionStage("fadeIn");
    }, PAGE_TRANSITION_DURATION_MS);

    return () => window.clearTimeout(timeout);
  }, [transitionStage, location]);

  return (
    <div
      className={cn(
        "mt-0 opacity-100",
        "motion-safe:transition-all motion-safe:duration-300 motion-safe:ease-in-out",
        transitionStage === "fadeIn"
          ? "motion-safe:mt-0 motion-safe:opacity-100"
          : "motion-safe:pointer-events-none motion-safe:mt-2 motion-safe:opacity-0"
      )}
    >
      <Routes location={displayLocation} key={displayKey}>
        <Route path="/" element={<MyTasksPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
        <Route path="/tasks" element={<Navigate to="/" replace />} />
        <Route path="/tasks/:taskId" element={<TaskEditPage />} />
        <Route path="/initiatives" element={<InitiativesPage />} />
        <Route path="/initiatives/:initiativeId" element={<InitiativeDetailPage />} />
        <Route path="/initiatives/:initiativeId/settings" element={<InitiativeSettingsPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
        <Route path="/documents/:documentId/settings" element={<DocumentSettingsPage />} />
        <Route path="/profile/*" element={<UserSettingsLayout />}>
          {user && (
            <>
              <Route
                index
                element={<UserSettingsProfilePage user={user} refreshUser={refreshUser} />}
              />
              <Route
                path="interface"
                element={<UserSettingsInterfacePage user={user} refreshUser={refreshUser} />}
              />
              <Route
                path="notifications"
                element={<UserSettingsNotificationsPage user={user} refreshUser={refreshUser} />}
              />
              <Route path="import" element={<UserSettingsImportPage />} />
              <Route path="api-keys" element={<SettingsApiKeysPage />} />
              <Route
                path="danger"
                element={<UserSettingsDangerZonePage user={user} logout={logout} />}
              />
            </>
          )}
        </Route>
        <Route path="/user-stats" element={<UserStatsPage />} />
        <Route path="/settings" element={<Navigate to="/settings/guild" replace />} />
        <Route path="/settings/guild/*" element={<GuildSettingsLayout />}>
          <Route index element={<SettingsGuildPage />} />
          <Route path="users" element={<SettingsUsersPage />} />
        </Route>
        <Route path="/settings/admin/*" element={<AdminSettingsLayout />}>
          <Route index element={<SettingsAuthPage />} />
          <Route path="auth" element={<SettingsAuthPage />} />
          <Route path="branding" element={<SettingsBrandingPage />} />
          <Route path="email" element={<SettingsEmailPage />} />
          <Route path="users" element={<SettingsPlatformUsersPage />} />
        </Route>
      </Routes>
    </div>
  );
};
