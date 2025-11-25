import { lazy } from "react";
import { Route, Routes } from "react-router-dom";

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
const SettingsUsersPage = lazy(() =>
  import("./pages/SettingsUsersPage").then((module) => ({
    default: module.SettingsUsersPage,
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
const InitiativesPage = lazy(() =>
  import("./pages/InitiativesPage").then((module) => ({
    default: module.InitiativesPage,
  }))
);

export const PageRoutes = () => (
  <Routes>
    <Route path="/" element={<ProjectsPage />} />
    <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
    <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
    <Route path="/tasks/:taskId/edit" element={<TaskEditPage />} />
    <Route path="/tasks" element={<MyTasksPage />} />
    <Route path="/profile" element={<UserSettingsPage />} />
    <Route path="/settings/*" element={<SettingsLayout />}>
      <Route index element={<SettingsUsersPage />} />
      <Route path="initiatives" element={<InitiativesPage />} />
      <Route path="auth" element={<SettingsAuthPage />} />
      <Route path="api-keys" element={<SettingsApiKeysPage />} />
      <Route path="branding" element={<SettingsBrandingPage />} />
      <Route path="email" element={<SettingsEmailPage />} />
    </Route>
  </Routes>
);
