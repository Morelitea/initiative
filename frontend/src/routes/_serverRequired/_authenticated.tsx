import { Suspense } from "react";
import {
  createFileRoute,
  Navigate,
  Outlet,
  redirect,
  useLocation,
  useSearch,
} from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Menu } from "lucide-react";

import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { ProjectTabsBar } from "@/components/projects/ProjectTabsBar";
import { ProjectActivitySidebar } from "@/components/projects/ProjectActivitySidebar";
import { VersionDialog } from "@/components/VersionDialog";
import { PushPermissionPrompt } from "@/components/notifications/PushPermissionPrompt";
import { useGuilds } from "@/hooks/useGuilds";
import { useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import { useVersionCheck } from "@/hooks/useVersionCheck";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useBackButton } from "@/hooks/useBackButton";
import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";
import { apiClient } from "@/api/client";
import type { Project } from "@/types/api";

/**
 * Loading fallback for lazy-loaded pages inside the main layout.
 */
const PageLoader = () => (
  <div className="flex items-center justify-center py-20">
    <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
  </div>
);

/**
 * Full-screen loading state shown while auth is being determined.
 */
const FullScreenLoader = () => (
  <div className="flex min-h-screen items-center justify-center">
    <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
  </div>
);

export const Route = createFileRoute("/_serverRequired/_authenticated")({
  beforeLoad: ({ context, search }) => {
    const { auth, server } = context;
    const justAuthenticated = (search as { authenticated?: string })?.authenticated === "1";

    // If auth state is already determined and user is not authenticated,
    // redirect immediately (this handles direct navigation when auth is cached)
    // Skip if we just authenticated (search param indicates state is updating)
    if (!justAuthenticated && !auth?.loading && !auth?.token) {
      const redirectTo = server?.isNativePlatform ? "/login" : "/welcome";
      throw redirect({ to: redirectTo });
    }
  },
  component: AppLayout,
});

function AppLayout() {
  // ALL hooks must be called before any conditional returns
  const { token, loading } = useAuth();
  const { isNativePlatform } = useServer();
  const { activeGuildId } = useGuilds();
  const location = useLocation();
  const search = useSearch({ strict: false }) as { authenticated?: string };
  const queryClient = useQueryClient();

  // Check if we just authenticated (search param passed via navigation)
  const justAuthenticated = search?.authenticated === "1";
  const { updateAvailable, closeDialog } = useVersionCheck();

  useRealtimeUpdates();
  usePushNotifications();
  useBackButton();

  const recentQueryKey = ["projects", activeGuildId, "recent"] as const;

  const recentQuery = useQuery<Project[]>({
    queryKey: recentQueryKey,
    queryFn: async () => {
      const response = await apiClient.get<Project[]>("/projects/recent");
      return response.data;
    },
    enabled: activeGuildId !== null && !loading && !!token,
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

  // Now we can have conditional returns
  // Show loading state while auth is being determined
  if (loading) {
    return <FullScreenLoader />;
  }

  // Redirect to login/welcome if not authenticated (and we didn't just authenticate)
  if (!token && !justAuthenticated) {
    const redirectTo = isNativePlatform ? "/login" : "/welcome";
    return <Navigate to={redirectTo} replace />;
  }

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
            <div className="bg-card/70 supports-backdrop-filter:bg-card/60 sticky top-0 z-50 flex border-b backdrop-blur">
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
                <Suspense fallback={<PageLoader />}>
                  <Outlet />
                </Suspense>
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
}
