import { Suspense, lazy } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppHeader } from "@/components/AppHeader";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ProjectShortcutsSidebar } from "@/components/projects/ProjectShortcutsSidebar";
import { ProjectTabsBar } from "@/components/projects/ProjectTabsBar";
import { useAuth } from "@/hooks/useAuth";
import { useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import { useInterfaceColors } from "@/hooks/useInterfaceColors";
import { apiClient } from "@/api/client";
import type { Project } from "@/types/api";
import { PageRoutes } from "@/PageRoutes";

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

const AppLayout = () => {
  const { user } = useAuth();
  useRealtimeUpdates();
  useInterfaceColors();

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
  const activeProjectId = activeProjectMatch ? Number(activeProjectMatch[1]) : null;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader />
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
        <main className="flex-1 min-w-0 bg-muted/50 pb-20">
          <div className="container min-w-0 p-4 md:p-8">
            <PageRoutes />
          </div>
        </main>
      </div>
    </div>
  );
};

export const App = () => (
  <BrowserRouter>
    <Suspense fallback={<div className="py-10 text-center text-muted-foreground">Loading...</div>}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/oidc/callback" element={<OidcCallbackPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/*" element={<AppLayout />} />
        </Route>
      </Routes>
    </Suspense>
  </BrowserRouter>
);
