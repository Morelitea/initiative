import { Suspense, useState } from "react";
import {
  createFileRoute,
  Link,
  Navigate,
  Outlet,
  redirect,
  useLocation,
  useSearch,
} from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Loader2, LogOut, Menu, Plus, Ticket } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { CommandCenter } from "@/components/CommandCenter";
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
import { useRecentProjects, useClearProjectView } from "@/hooks/useProjects";
import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";

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
  const { token, loading, logout } = useAuth();
  const { isNativePlatform } = useServer();
  const {
    activeGuildId,
    guilds,
    loading: guildsLoading,
    canCreateGuilds,
    createGuild,
  } = useGuilds();
  const location = useLocation();
  const search = useSearch({ strict: false }) as { authenticated?: string };
  // Check if we just authenticated (search param passed via navigation)
  const justAuthenticated = search?.authenticated === "1";
  const { updateAvailable, closeDialog } = useVersionCheck();

  useRealtimeUpdates();
  usePushNotifications();
  useBackButton();

  const recentQuery = useRecentProjects({
    enabled: activeGuildId !== null && !loading && !!token,
    staleTime: 30_000,
  });

  const clearRecent = useClearProjectView();

  // Now we can have conditional returns
  // Show loading state while auth or guild membership is being determined
  if (loading || guildsLoading) {
    return <FullScreenLoader />;
  }

  // Redirect to login/welcome if not authenticated (and we didn't just authenticate)
  if (!token && !justAuthenticated) {
    const redirectTo = isNativePlatform ? "/login" : "/welcome";
    return <Navigate to={redirectTo} replace />;
  }

  // Show no-guild empty state if user has no guild memberships
  if (guilds.length === 0 && token) {
    return (
      <NoGuildState canCreateGuilds={canCreateGuilds} createGuild={createGuild} logout={logout} />
    );
  }

  const handleClearRecent = (projectId: number) => {
    clearRecent.mutate(projectId);
  };

  // Match both old /projects/:id and new /g/:guildId/projects/:id patterns
  const activeProjectMatch =
    location.pathname.match(/^\/g\/\d+\/projects\/(\d+)/) ||
    location.pathname.match(/^\/projects\/(\d+)/);
  const activeProjectId = activeProjectMatch ? Number(activeProjectMatch[1]) : null;

  return (
    <>
      <CommandCenter />
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
                    projects={recentQuery.data as ProjectRead[] | undefined}
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
    </>
  );
}

function NoGuildState({
  canCreateGuilds,
  createGuild,
  logout,
}: {
  canCreateGuilds: boolean;
  createGuild: (input: { name: string; description?: string }) => Promise<unknown>;
  logout: () => void;
}) {
  const { t } = useTranslation("guilds");
  const [guildName, setGuildName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    const trimmed = guildName.trim();
    if (!trimmed) return;
    setCreating(true);
    try {
      await createGuild({ name: trimmed });
    } catch {
      setCreating(false);
    }
  };

  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <div className="mx-auto w-full max-w-md space-y-6 text-center">
        <h1 className="text-2xl font-bold">{t("noGuild.title")}</h1>
        <p className="text-muted-foreground">{t("noGuild.description")}</p>

        {canCreateGuilds && (
          <div className="flex gap-2">
            <Input
              placeholder={t("noGuild.guildNamePlaceholder")}
              value={guildName}
              onChange={(e) => setGuildName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleCreate();
              }}
            />
            <Button onClick={() => void handleCreate()} disabled={creating || !guildName.trim()}>
              <Plus className="h-4 w-4" />
              {t("noGuild.create")}
            </Button>
          </div>
        )}

        <div className="flex gap-2">
          <Input
            placeholder={t("noGuild.inviteCodePlaceholder")}
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
          />
          <Button variant="outline" asChild disabled={!inviteCode.trim()}>
            <Link
              to="/invite/$code"
              params={{ code: inviteCode.trim() }}
              disabled={!inviteCode.trim()}
            >
              <Ticket className="h-4 w-4" />
              {t("noGuild.redeem")}
            </Link>
          </Button>
        </div>

        <Button variant="ghost" onClick={logout}>
          <LogOut className="h-4 w-4" />
          {t("noGuild.logOut")}
        </Button>
      </div>
    </div>
  );
}
