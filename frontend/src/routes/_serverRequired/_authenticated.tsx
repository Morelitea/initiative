import { createFileRoute, Link, Outlet, redirect, useLocation } from "@tanstack/react-router";
import { Loader2, LogOut, Plus, Settings, Ticket, UserCog } from "lucide-react";
import { Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildRead, RecentItemRead } from "@/api/generated/initiativeAPI.schemas";
import { AppSidebar } from "@/components/AppSidebar";
import { AnnouncementCenter } from "@/components/announcements/AnnouncementCenter";
import { UpdateAnnouncementDialog } from "@/components/announcements/UpdateAnnouncementDialog";
import { ChooseHandle } from "@/components/ChooseHandle";
import { CommandCenter } from "@/components/CommandCenter";
import { ConfirmAge } from "@/components/ConfirmAge";
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
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useBackButton } from "@/hooks/useBackButton";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useGuilds } from "@/hooks/useGuilds";
import { useCollectMessagesWhereRegistered } from "@/hooks/useMyMessages";
import { useNotificationStream } from "@/hooks/useNotificationStream";
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
  // Personal, cross-guild, and mounted here rather than beside the bell so it
  // survives the bell unmounting with a collapsed sidebar.
  useNotificationStream();
  usePushNotifications();
  useBackButton();
  // Mail is fetched wherever you are, so a message that arrives while you are
  // on another page is noticed rather than waiting to be discovered. Only for a
  // browser that has already been set up for messages — this never sets one up.
  useCollectMessagesWhereRegistered();

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

  // Already in a community the whole deployment can browse, without having
  // said how old they are. Every way into a listed guild that had nobody at a
  // keyboard to ask lands here — and so does anyone who was already a member
  // when their guild listed itself.
  if (!loading && user && user.age_confirmation_required) {
    return <ConfirmAge />;
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
      {/* A real height rather than a minimum: `min-h-screen` leaves every
          descendant sizing to its own content, so a page cannot ask for the
          height of what it is in. Scrolling moves from the document into
          `main` with it -- which is what lets a page keep a header or a
          composer against an edge instead of measuring where that edge fell. */}
      {/* `clip` rather than `hidden`: both hide what overruns, but `hidden`
          leaves a scrollport behind -- one with no scrollbar, which a reader
          cannot get back from and which anything at all can move. Focus moving
          to a grown textarea, a `scrollIntoView`, a devtools panel in the flow:
          each parks the whole app, chrome included, somewhere it cannot be
          scrolled back from. `clip` makes it what it reads as: not a scroller. */}
      <div className="flex h-screen flex-col overflow-clip bg-background">
        <PushPermissionPrompt />
        <div className="flex min-h-0 flex-1">
          <SidebarProvider
            defaultOpen={true}
            // The provider's own wrapper asks for `min-h-svh`, which is a floor
            // for a page that grows and a trap for one that does not: anything
            // above it here -- a permission prompt, a banner -- makes the row
            // it sits in shorter than a screen, and the wrapper refuses to
            // follow. Everything below then measures itself against a box
            // taller than the one on screen, and the app scrolls into space
            // that was never there. The shell has a real height; take it.
            className="h-full min-h-0"
            style={
              {
                "--sidebar-width": "20rem",
                "--sidebar-width-mobile": "90vw",
              } as React.CSSProperties
            }
          >
            <AppSidebar />
            <div className="flex min-h-0 min-w-0 flex-1 flex-col md:pl-0">
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
              <div className="flex min-h-0 flex-1 justify-between">
                {/*<div
                  className="h-full w-full opacity-20 fixed"
                  style={{
                    backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
                    backgroundPosition: "center",
                    backgroundBlendMode: "screen",
                    backgroundSize: "37px 64px",
                  }}
                />*/}
                {/* The app's scroller. Named twice over: the router restores
                    this element's position across navigations rather than the
                    window's, and pull-to-refresh asks it how far down it is.

                    It spans the row and holds the page's width inside it,
                    rather than being that width itself. A scrollbar renders at
                    the edge of its own scrollport, so a scroller that was also
                    `container mx-auto` put the bar in the middle of the window
                    — floating beside the centred column instead of down the
                    side of the app.

                    `overflow-x-clip` because `overflow-y: auto` alone does not
                    stay on one axis: with the other left `visible`, CSS
                    computes that one to `auto` too, quietly making the shell a
                    horizontal scroller. Anything anywhere that overran then
                    dragged the whole app sideways. Wide content owns its own
                    scroller here — the tool rail and every table already do —
                    so the shell says no to the axis rather than offering a bar
                    nothing should need. */}
                <main
                  data-app-scroll=""
                  data-scroll-restoration-id="app-main"
                  className="min-w-0 flex-1 overflow-y-auto overflow-x-clip"
                >
                  {/* A grid, and `min-h-full` rather than `h-full`, because
                      this sits between the scrollport and the page and must
                      pass a height through without capping one.

                      `h-full` would fix it at the scrollport's height, and a
                      page taller than that would spill past its own bottom
                      padding. `min-h-full` alone grows correctly but leaves
                      `height: auto`, and a percentage height resolves against
                      the parent's *height* — so `h-full` on a page would
                      silently become `auto`. Three pages depend on that chain
                      (My Messages, a document, an app surface): each pins
                      something to an edge and needs a real height to do it.

                      A grid row is definite either way. It is at least the
                      scrollport, grows with a long page, and gives a child's
                      `h-full` an area to resolve against. */}
                  <div className="container mx-auto grid min-h-full grid-rows-[1fr] p-4 pb-24 md:p-8 md:pb-24">
                    <Suspense fallback={<PageLoader />}>
                      <Outlet />
                    </Suspense>
                  </div>
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
        <UpdateAnnouncementDialog
          open={updateAvailable.show}
          version={updateAvailable.version}
          onClose={closeDialog}
        />
        {/* Server-side notices queue behind the update prompt: an update is
            about the page the reader is looking at, so it goes first. */}
        <AnnouncementCenter enabled={!updateAvailable.show} />
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
