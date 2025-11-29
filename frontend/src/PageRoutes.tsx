import { lazy, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
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
const SettingsInitiativesPage = lazy(() =>
  import("./pages/SettingsInitiativesPage").then((module) => ({
    default: module.SettingsInitiativesPage,
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

export const PageRoutes = () => {
  const location = useLocation();
  const { user, refreshUser } = useAuth();
  const prefersReducedMotion = usePrefersReducedMotion();
  // Keep rendering the previous route until the fade-out completes.
  const [displayLocation, setDisplayLocation] = useState(location);
  const [transitionStage, setTransitionStage] = useState<TransitionStage>("fadeIn");
  const locationKey = location.key ?? `${location.pathname}${location.search}${location.hash}`;
  const displayKey =
    displayLocation.key ??
    `${displayLocation.pathname}${displayLocation.search}${displayLocation.hash}`;

  useEffect(() => {
    if (prefersReducedMotion) {
      setDisplayLocation(location);
      setTransitionStage("fadeIn");
      return;
    }

    if (locationKey !== displayKey) {
      setTransitionStage("fadeOut");
    }
  }, [prefersReducedMotion, location, locationKey, displayKey]);

  useEffect(() => {
    if (prefersReducedMotion || transitionStage !== "fadeOut") {
      return;
    }

    const timeout = window.setTimeout(() => {
      setDisplayLocation(location);
      setTransitionStage("fadeIn");
    }, PAGE_TRANSITION_DURATION_MS);

    return () => window.clearTimeout(timeout);
  }, [prefersReducedMotion, transitionStage, location]);

  return (
    <div
      className={cn(
        !prefersReducedMotion && "transition-all duration-300 ease-in-out",
        transitionStage === "fadeIn" ? "opacity-100 mt-0" : "pointer-events-none opacity-0 mt-2"
      )}
    >
      <Routes location={displayLocation} key={displayKey}>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
        <Route path="/tasks/:taskId/edit" element={<TaskEditPage />} />
        <Route path="/tasks" element={<MyTasksPage />} />
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
            </>
          )}
        </Route>
        <Route path="/settings" element={<Navigate to="/settings/guild" replace />} />
        <Route path="/settings/guild/*" element={<GuildSettingsLayout />}>
          <Route index element={<SettingsGuildPage />} />
          <Route path="users" element={<SettingsUsersPage />} />
          <Route path="initiatives" element={<SettingsInitiativesPage />} />
          <Route path="api-keys" element={<SettingsApiKeysPage />} />
        </Route>
        <Route path="/settings/admin/*" element={<AdminSettingsLayout />}>
          <Route index element={<SettingsAuthPage />} />
          <Route path="auth" element={<SettingsAuthPage />} />
          <Route path="branding" element={<SettingsBrandingPage />} />
          <Route path="email" element={<SettingsEmailPage />} />
        </Route>
      </Routes>
    </div>
  );
};
