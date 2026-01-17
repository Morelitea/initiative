import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ProjectTabsBar } from "@/components/projects/ProjectTabsBar";
import { ProjectActivitySidebar } from "@/components/projects/ProjectActivitySidebar";
import { VersionDialog } from "@/components/VersionDialog";
import { useGuilds } from "@/hooks/useGuilds";
import { useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import { useInterfaceColors } from "@/hooks/useInterfaceColors";
import { useVersionCheck } from "@/hooks/useVersionCheck";
import { useServer } from "@/hooks/useServer";
import { useSafeArea } from "@/hooks/useSafeArea";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { apiClient } from "@/api/client";
import type { Project } from "@/types/api";
import { PageRoutes } from "@/PageRoutes";
import { AppSidebar } from "./components/AppSidebar";
import { PushPermissionPrompt } from "@/components/notifications/PushPermissionPrompt";
import { Menu } from "lucide-react";

const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((module) => ({ default: module.LoginPage }))
);
const RegisterPage = lazy(() =>
  import("./pages/RegisterPage").then((module) => ({
    default: module.RegisterPage,
  }))
);
const ForgotPasswordPage = lazy(() =>
  import("./pages/ForgotPasswordPage").then((module) => ({
    default: module.ForgotPasswordPage,
  }))
);
const ResetPasswordPage = lazy(() =>
  import("./pages/ResetPasswordPage").then((module) => ({
    default: module.ResetPasswordPage,
  }))
);
const VerifyEmailPage = lazy(() =>
  import("./pages/VerifyEmailPage").then((module) => ({
    default: module.VerifyEmailPage,
  }))
);
const OidcCallbackPage = lazy(() =>
  import("./pages/OidcCallbackPage").then((module) => ({
    default: module.OidcCallbackPage,
  }))
);
const GuildInvitePage = lazy(() =>
  import("./pages/GuildInvitePage").then((module) => ({
    default: module.GuildInvitePage,
  }))
);
const NavigatePage = lazy(() =>
  import("./pages/NavigatePage").then((module) => ({
    default: module.NavigatePage,
  }))
);
const LandingPage = lazy(() =>
  import("./pages/LandingPage").then((module) => ({
    default: module.LandingPage,
  }))
);
const ConnectServerPage = lazy(() =>
  import("./pages/ConnectServerPage").then((module) => ({
    default: module.ConnectServerPage,
  }))
);

/**
 * Route guard that requires a server to be configured on native platforms.
 * On web, this passes through. On mobile without a configured server, redirects to /connect.
 */
const ServerRequiredRoute = () => {
  const { isNativePlatform, isServerConfigured, loading } = useServer();

  if (loading) {
    return <div className="text-muted-foreground py-10 text-center">Loading...</div>;
  }

  // On native, if no server is configured, redirect to connect page
  if (isNativePlatform && !isServerConfigured) {
    return <Navigate to="/connect" replace />;
  }

  return <Outlet />;
};

const AppLayout = () => {
  const { activeGuildId } = useGuilds();
  useRealtimeUpdates();
  usePushNotifications(); // Initialize push notifications
  const { updateAvailable, closeDialog } = useVersionCheck();

  const location = useLocation();
  const queryClient = useQueryClient();
  const recentQueryKey = ["projects", activeGuildId, "recent"] as const;

  const recentQuery = useQuery<Project[]>({
    queryKey: recentQueryKey,
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/recent");
      return response.data;
    },
    enabled: activeGuildId !== null,
    staleTime: 30_000,
  });

  const clearRecent = useMutation({
    mutationFn: async (projectId: number) => {
      await apiClient.delete(`/projects/${projectId}/view`);
      return projectId;
    },
    onSuccess: (projectId) => {
      void queryClient.invalidateQueries({ queryKey: recentQueryKey });
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
  const activeProjectId = activeProjectMatch ? Number(activeProjectMatch[1]) : null;

  return (
    <div className="bg-background flex min-h-screen flex-col">
      <PushPermissionPrompt />
      <div className="flex flex-1">
        <SidebarProvider
          defaultOpen={true}
          style={
            {
              "--sidebar-width": "20rem",
              "--sidebar-width-mobile": "90vw",
            } as React.CSSProperties
          }
        >
          <AppSidebar />
          <div className="bg-muted/50 min-w-0 flex-1 md:pl-0">
            <div className="bg-card/70 supports-backdrop-filter:bg-card/60 sticky top-0 z-10 flex border-b backdrop-blur">
              <SidebarTrigger
                icon={<Menu />}
                className="h-12 w-12 shrink-0 rounded-none border-r lg:hidden"
              />
              <div className="min-w-0 flex-1">
                <ProjectTabsBar
                  projects={recentQuery.data}
                  loading={recentQuery.isLoading}
                  activeProjectId={activeProjectId}
                  onClose={handleClearRecent}
                />
              </div>
            </div>
            <div className="flex justify-between">
              <main className="container mx-auto min-w-0 p-4 pb-20 md:p-8 md:pb-20">
                <PageRoutes />
              </main>
            </div>
          </div>
          <ProjectActivitySidebar projectId={activeProjectId} />
        </SidebarProvider>
      </div>
      <VersionDialog
        mode="update"
        open={updateAvailable.show}
        currentVersion={updateAvailable.version}
        newVersion={updateAvailable.version}
        onClose={closeDialog}
      />
    </div>
  );
};

export const App = () => {
  useInterfaceColors();
  useSafeArea();
  return (
    <BrowserRouter>
      <Suspense
        fallback={<div className="text-muted-foreground py-10 text-center">Loading...</div>}
      >
        <Routes>
          {/* Server connection page for mobile - doesn't require server to be configured */}
          <Route path="/connect" element={<ConnectServerPage />} />

          {/* All other routes require server to be configured on mobile */}
          <Route element={<ServerRequiredRoute />}>
            <Route path="/welcome" element={<LandingPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/verify-email" element={<VerifyEmailPage />} />
            <Route path="/oidc/callback" element={<OidcCallbackPage />} />
            <Route path="/invite/:code" element={<GuildInvitePage />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/navigate" element={<NavigatePage />} />
              <Route path="/*" element={<AppLayout />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};
