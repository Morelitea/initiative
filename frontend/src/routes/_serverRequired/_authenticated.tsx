import {
  createFileRoute,
  Link,
  Navigate,
  Outlet,
  redirect,
  useLocation,
  useSearch,
} from "@tanstack/react-router";
import { Loader2, LogOut, Menu, Plus, Search, Settings, Ticket, UserCog } from "lucide-react";
import { Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { AppSidebar } from "@/components/AppSidebar";
import { CommandCenter, getOpenCommandCenter } from "@/components/CommandCenter";
import { PushPermissionPrompt } from "@/components/notifications/PushPermissionPrompt";
import { ProjectActivitySidebar } from "@/components/projects/ProjectActivitySidebar";
import { RecentTabsBar } from "@/components/recents/RecentTabsBar";
import { CreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { VersionDialog } from "@/components/VersionDialog";
import { useAuth } from "@/hooks/useAuth";
import { useBackButton } from "@/hooks/useBackButton";
import { useGuilds } from "@/hooks/useGuilds";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import { useClearRecentView, useRecents } from "@/hooks/useRecents";
import { useServer } from "@/hooks/useServer";
import { useVersionCheck } from "@/hooks/useVersionCheck";
import { chooseNoGuildLayout } from "@/lib/noGuildLayout";
import { getActiveRecentKey } from "@/lib/recentRoute";

/**
 * Loading fallback for lazy-loaded pages inside the main layout.
 */
const PageLoader = () => (
  <div className="flex items-center justify-center py-20">
    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
  </div>
);

/**
 * Full-screen loading state shown while auth is being determined.
 */
const FullScreenLoader = () => (
  <div className="flex min-h-screen items-center justify-center">
    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
  </div>
);

export const Route = createFileRoute("/_serverRequired/_authenticated")({
  beforeLoad: ({ context, search }) => {
    const { auth, server } = context;
    const justAuthenticated = (search as { authenticated?: string })?.authenticated === "1";

    // If auth state is already determined and user is not authenticated,
    // redirect immediately (this handles direct navigation when auth is cached)
    // Skip if we just authenticated (search param indicates state is updating)
    if (!justAuthenticated && !auth?.loading && !auth?.user) {
      const redirectTo = server?.isNativePlatform ? "/login" : "/welcome";
      throw redirect({ to: redirectTo });
    }
  },
  component: AppLayout,
});

function AppLayout() {
  // ALL hooks must be called before any conditional returns
  const { t } = useTranslation("command");
  const { user, loading, logout } = useAuth();
  const { isNativePlatform } = useServer();
  const isMac = useMemo(
    () => typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent),
    []
  );
  const shortcutLabel = isMac ? "\u2318K" : "Ctrl+K";
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

  const recentQuery = useRecents({
    enabled: activeGuildId !== null && !loading && !!user,
    staleTime: 30_000,
  });

  const clearRecent = useClearRecentView();

  // Now we can have conditional returns
  // Show loading state while auth or guild membership is being determined
  if (loading || guildsLoading) {
    return <FullScreenLoader />;
  }

  // Redirect to login/welcome if not authenticated (and we didn't just authenticate)
  if (!user && !justAuthenticated) {
    const redirectTo = isNativePlatform ? "/login" : "/welcome";
    return <Navigate to={redirectTo} replace />;
  }

  // No-guild empty-state branch. The user-scoped settings routes
  // (``/profile/*``) and platform-admin settings (``/settings/admin/*``
  // for an admin) don't need guild context — the APIs they call don't
  // require an ``X-Guild-ID`` header — and a user with zero
  // memberships would otherwise have no path to delete their account
  // or, for platform admins, configure system-wide settings. The
  // path-based decision lives in ``chooseNoGuildLayout`` so it can be
  // unit-tested without a router; see ``noGuildLayout.test.ts``.
  if (user) {
    const isPlatformAdmin = user.role === "admin";
    const layout = chooseNoGuildLayout({
      hasGuilds: guilds.length > 0,
      pathname: location.pathname,
      isPlatformAdmin,
    });
    if (layout === "shell") {
      return <NoGuildSettingsShell logout={logout} />;
    }
    if (layout === "empty") {
      return (
        <NoGuildState
          canCreateGuilds={canCreateGuilds}
          createGuild={createGuild}
          logout={logout}
          isPlatformAdmin={isPlatformAdmin}
        />
      );
    }
    // layout === "main" → fall through to the standard sidebar layout.
  }

  const handleClearRecent = (item: RecentItemRead) => {
    clearRecent.mutate({ entityType: item.entity_type, entityId: item.entity_id });
  };

  const activeRecentKey = getActiveRecentKey(location.pathname);
  // ProjectActivitySidebar still wants the active project id directly.
  const activeProjectId =
    activeRecentKey?.entityType === "project" ? activeRecentKey.entityId : null;

  return (
    <>
      <CommandCenter />
      <CreateTaskWizard />
      <div className="flex min-h-screen flex-col bg-background">
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
            <div className="min-w-0 flex-1 bg-muted/50 md:pl-0">
              <div
                className="sticky top-0 z-50 flex flex-col border-b bg-card/70 backdrop-blur supports-backdrop-filter:bg-card/60"
                style={{ paddingTop: "var(--safe-area-inset-top)" }}
              >
                <div className="flex h-12">
                  <SidebarTrigger
                    icon={<Menu />}
                    className="h-12 w-12 shrink-0 rounded-none border-r lg:hidden"
                  />
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-12 w-12 shrink-0 rounded-none border-r"
                        onClick={() => getOpenCommandCenter()?.()}
                        aria-label={t("shortcutTooltip", { shortcut: shortcutLabel })}
                      >
                        <Search className="h-5 w-5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>{shortcutLabel}</TooltipContent>
                  </Tooltip>
                  <div className="min-w-0 flex-1">
                    <RecentTabsBar
                      items={recentQuery.data}
                      loading={recentQuery.isLoading}
                      activeKey={activeRecentKey}
                      onClose={handleClearRecent}
                    />
                  </div>
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
  isPlatformAdmin,
}: {
  canCreateGuilds: boolean;
  createGuild: (input: { name: string; description?: string }) => Promise<unknown>;
  logout: () => void;
  isPlatformAdmin: boolean;
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
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="mx-auto w-full max-w-md space-y-6 text-center">
        <h1 className="font-bold text-2xl">{t("noGuild.title")}</h1>
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

        {/* Direct entry points to the user/platform settings pages so a
            user with no memberships can still manage their account
            (e.g. delete it) or, for platform admins, system-wide
            configuration. Without these the only paths off this screen
            are create/join/logout. */}
        <div className="flex flex-col gap-2">
          <Button variant="outline" asChild>
            <Link to="/profile">
              <UserCog className="h-4 w-4" />
              {t("noGuild.accountSettings")}
            </Link>
          </Button>
          {isPlatformAdmin && (
            <Button variant="outline" asChild>
              <Link to="/settings/admin">
                <Settings className="h-4 w-4" />
                {t("noGuild.platformSettings")}
              </Link>
            </Button>
          )}
        </div>

        <Button variant="ghost" onClick={logout}>
          <LogOut className="h-4 w-4" />
          {t("noGuild.logOut")}
        </Button>
      </div>
    </div>
  );
}

/**
 * Minimal layout shown when the user has zero guild memberships but
 * is on a route that doesn't need guild context (``/profile/*``,
 * ``/settings/admin/*``). Renders the matched outlet inside a
 * narrow container with just enough chrome (Back-to-start + logout)
 * to navigate away.
 */
function NoGuildSettingsShell({ logout }: { logout: () => void }) {
  const { t } = useTranslation("guilds");
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div
        className="sticky top-0 z-50 flex flex-col border-b bg-card/70 backdrop-blur supports-backdrop-filter:bg-card/60"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 items-center justify-between px-4">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/">{t("noGuild.shellBackToStart")}</Link>
          </Button>
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut className="h-4 w-4" />
            {t("noGuild.logOut")}
          </Button>
        </div>
      </div>
      <main className="container mx-auto min-w-0 p-4 pb-20 md:p-8 md:pb-20">
        <Suspense fallback={<PageLoader />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
