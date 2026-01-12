import { Suspense, lazy } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
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
import { apiClient } from "@/api/client";
import type { Project } from "@/types/api";
import { PageRoutes } from "@/PageRoutes";
import { AppSidebar } from "./components/AppSidebar";
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

const AppLayout = () => {
  const { activeGuildId } = useGuilds();
  useRealtimeUpdates();
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
  return (
    <BrowserRouter>
      <Suspense
        fallback={<div className="text-muted-foreground py-10 text-center">Loading...</div>}
      >
        <Routes>
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
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};
