import { createFileRoute, Link, Outlet, redirect, useLocation } from "@tanstack/react-router";
import { Loader2, LogOut, Plus, Settings, Ticket, UserCog } from "lucide-react";
import { Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildRead, RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { AppSidebar } from "@/components/AppSidebar";
import { ChooseHandle } from "@/components/ChooseHandle";
import { CommandCenter } from "@/components/CommandCenter";
import { CreateDocumentWizard } from "@/components/documents/CreateDocumentWizard";
import { GuildAccessBanner } from "@/components/guilds/GuildAccessBanner";
import { Galaxy } from "@/components/icons/Galaxy";
import { BottomNav } from "@/components/navigation/BottomNav";
import { CreateActionProvider } from "@/components/navigation/CreateActionContext";
import { PushPermissionPrompt } from "@/components/notifications/PushPermissionPrompt";
import { ProjectActivitySidebar } from "@/components/projects/ProjectActivitySidebar";
import { RecentTabsBar } from "@/components/recents/RecentTabsBar";
import { CreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarProvider } from "@/components/ui/sidebar";
import { VersionDialog } from "@/components/VersionDialog";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useBackButton } from "@/hooks/useBackButton";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useGuilds } from "@/hooks/useGuilds";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import {
  type ClearRecentTarget,
  useClearRecentView,
  useClearRecentViews,
  useRecents,
} from "@/hooks/useRecents";
import { useVersionCheck } from "@/hooks/useVersionCheck";
import { isJustSignedIn } from "@/lib/authTransition";
import { toast } from "@/lib/chesterToast";
import { chooseNoGuildLayout } from "@/lib/noGuildLayout";
import { canAccessPlatformAdmin } from "@/lib/permissions";
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
  beforeLoad: ({ context }) => {
    const { auth, server } = context;

    // If auth state is already determined and user is not authenticated,
    // redirect immediately (this handles direct navigation when auth is
    // cached). Skip during the brief just-signed-in window, when the auth
    // context hasn't committed the new user yet; logout clears the marker,
    // so a signed-out session always redirects.
    if (!isJustSignedIn() && !auth?.loading && !auth?.user) {
      const redirectTo = server?.isNativePlatform ? "/login" : "/welcome";
      throw redirect({ to: redirectTo });
    }
  },
  component: AppLayout,
});

function AppLayout() {
  // ALL hooks must be called before any conditional returns
  const { user, loading, logout } = useAuth();
  const { guilds, loading: guildsLoading, canCreateGuilds, createGuild } = useGuilds();
  const location = useLocation();
  const { updateAvailable, closeDialog } = useVersionCheck();

  useRealtimeUpdates();
  usePushNotifications();
  useBackButton();

  // No cross-tab guild convergence: each tab keeps the guild from its own URL,
  // so two tabs can sit in two different guilds at once.

  // The tabs bar is cross-guild by design (names only): one user-context
  // query, valid in any guild and in personal mode.
  const recentQuery = useRecents({
    enabled: !loading && !!user,
    staleTime: 30_000,
  });

  const clearRecent = useClearRecentView();
  const clearRecents = useClearRecentViews();

  // An account that was handed its handle rather than picking one chooses
  // here, before anything else: it is how everyone else will see them.
  if (!loading && user && !user.username_chosen) {
    return <ChooseHandle />;
  }

  // Now we can have conditional returns
  // Show loading state while auth or guild membership is being determined
  if (loading || guildsLoading) {
    return <FullScreenLoader />;
  }

  // Not authenticated: the redirect belongs to `beforeLoad` above, which
  // re-runs as soon as the auth context settles (``useRouteGuardSync``). Hold
  // the loader for the render or two before that lands rather than redirecting
  // from the render path — a rendered `<Navigate>` re-navigates on every render
  // and stops only because this layout unmounts. The just-signed-in window
  // covers the render before the auth context commits the new user; logout
  // clears it, so signing out always leaves the authenticated shell.
  if (!user && !isJustSignedIn()) {
    return <FullScreenLoader />;
  }

  // No-guild empty-state branch. The user-scoped settings routes
  // (``/profile/*``) and platform-admin settings (``/settings/admin/*``
  // for an admin) don't need guild context — the APIs they call work
  // without a server-held guild — and a user with zero
  // memberships would otherwise have no path to delete their account
  // or, for platform admins, configure system-wide settings. The
  // path-based decision lives in ``chooseNoGuildLayout`` so it can be
  // unit-tested without a router; see ``noGuildLayout.test.ts``.
  if (user) {
    const isPlatformAdmin = canAccessPlatformAdmin(user);
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

  const toClearTarget = (item: RecentItemRead): ClearRecentTarget => ({
    entityType: item.entity_type,
    entityId: item.entity_id,
    guildId: item.guild_id,
  });

  const handleClearRecent = (item: RecentItemRead) => {
    clearRecent.mutate(toClearTarget(item));
  };

  const handleCloseOtherRecents = (keep: RecentItemRead) => {
    const others = (recentQuery.data ?? []).filter(
      (item) =>
        !(
          item.guild_id === keep.guild_id &&
          item.entity_type === keep.entity_type &&
          item.entity_id === keep.entity_id
        )
    );
    if (others.length > 0) {
      clearRecents.mutate(others.map(toClearTarget));
    }
  };

  const handleCloseAllRecents = () => {
    const all = recentQuery.data ?? [];
    if (all.length > 0) {
      clearRecents.mutate(all.map(toClearTarget));
    }
  };

  // The backend already caps the list to the user's ``recent_tabs_limit``, but
  // slice client-side too so lowering the setting takes effect immediately
  // (before the 30s-stale recents query refetches).
  const recentItems = recentQuery.data?.slice(0, user?.recent_tabs_limit ?? 20);

  const activeRecentKey = getActiveRecentKey(location.pathname);
  // ProjectActivitySidebar still wants the active project directly — and the
  // initiative it sits in, since a task's URL names that too.
  const activeProjectId =
    activeRecentKey?.entityType === "project" ? activeRecentKey.entityId : null;
  const activeProjectInitiativeId =
    activeRecentKey?.entityType === "project" ? activeRecentKey.initiativeId : null;

  // const isDark = document.documentElement.classList.contains("dark");

  return (
    <CreateActionProvider>
      <CommandCenter />
      <CreateTaskWizard />
      <CreateDocumentWizard />
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
            <div className="flex min-w-0 flex-1 flex-col md:pl-0">
              <div
                className="sticky top-0 z-50 flex flex-col bg-card/70 backdrop-blur supports-backdrop-filter:bg-card/60 lg:border-b"
                style={{ paddingTop: "var(--safe-area-inset-top)" }}
              >
                {/* Mobile hamburger lives in BottomNav and search now lives in
                    the sidebar, so this desktop-only row is just recents — and
                    with nothing recent it takes up no room at all. */}
                {(recentQuery.isLoading || (recentItems?.length ?? 0) > 0) && (
                  <div className="hidden h-12 lg:flex">
                    <div className="min-w-0 flex-1">
                      <RecentTabsBar
                        items={recentItems}
                        loading={recentQuery.isLoading}
                        activeKey={activeRecentKey}
                        onClose={handleClearRecent}
                        onCloseOthers={handleCloseOtherRecents}
                        onCloseAll={handleCloseAllRecents}
                      />
                    </div>
                  </div>
                )}
                <GuildAccessBanner />
              </div>
              <div className="flex flex-1 justify-between">
                {/*<div
                  className="h-full w-full opacity-20 fixed"
                  style={{
                    backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
                    backgroundPosition: "center",
                    backgroundBlendMode: "screen",
                    backgroundSize: "37px 64px",
                  }}
                />*/}
                <main className="container mx-auto min-w-0 p-4 pb-24 md:p-8 md:pb-24">
                  <Suspense fallback={<PageLoader />}>
                    <Outlet />
                  </Suspense>
                </main>
              </div>
            </div>
            <ProjectActivitySidebar
              projectId={activeProjectId}
              initiativeId={activeProjectInitiativeId}
            />
            <BottomNav />
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
    </CreateActionProvider>
  );
}

function NoGuildState({
  canCreateGuilds,
  createGuild,
  logout,
  isPlatformAdmin,
}: {
  canCreateGuilds: boolean;
  createGuild: (input: { name: string; description?: string }) => Promise<GuildRead>;
  logout: () => void;
  isPlatformAdmin: boolean;
}) {
  const { t } = useTranslation("guilds");
  const { billing, openPortal, reserveTab } = useBillingPortal();
  const { communityDirectoryEnabled } = useAppConfig();
  const [guildName, setGuildName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    const trimmed = guildName.trim();
    if (!trimmed) return;
    setCreating(true);
    // Reserved inside the click gesture (null when the deployment has no
    // billing portal) so the hop below isn't treated as an unsolicited popup.
    const billingTab = reserveTab();
    try {
      const guild = await createGuild({ name: trimmed });
      if (billing) {
        toast.info(t("billingSetup.opening", { guild: guild.name }));
        await openPortal(guild.id, "upgrade", billingTab);
      }
    } catch {
      billingTab?.close();
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

        {/* The other way out of this screen: a guild that opened itself to
            the directory can be joined here and now, with no invite to wait
            for and nobody to ask. Only where the platform owner runs a
            directory — otherwise an invite is the only way in. */}
        {communityDirectoryEnabled && (
          <Button variant="outline" asChild className="w-full">
            <Link to="/communities">
              <Galaxy className="h-4 w-4" />
              {t("noGuild.browseCommunities")}
            </Link>
          </Button>
        )}

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
