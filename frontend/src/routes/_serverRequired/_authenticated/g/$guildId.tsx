import {
  createFileRoute,
  Navigate,
  Outlet,
  redirect,
  useLocation,
  useParams,
} from "@tanstack/react-router";
import { Loader2, ShieldAlert } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import { useGuilds } from "@/hooks/useGuilds";
import { guildPath } from "@/lib/guildUrl";

/**
 * Whether a suspended guild's layout should redirect this location to the
 * guild's settings page.
 *
 * Scoped to THIS guild's subtree on purpose: the router publishes the pending
 * target location at the START of a navigation while the old layout is still
 * mounted, so an unscoped "not under /settings" check would fire on any
 * attempt to leave (home, another guild) and the Navigate would cancel it —
 * trapping the admin on the settings page.
 */
export function shouldPinSuspendedGuildToSettings(pathname: string, guildId: number): boolean {
  const settingsRoot = guildPath(guildId, "/settings");
  const withinThisGuild = pathname === `/g/${guildId}` || pathname.startsWith(`/g/${guildId}/`);
  const withinSettings = pathname === settingsRoot || pathname.startsWith(`${settingsRoot}/`);
  return withinThisGuild && !withinSettings;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId")({
  beforeLoad: async ({ context, params, cause }) => {
    const guildId = Number(params.guildId);
    const { guilds } = context;

    // Validate guildId is a valid number
    if (!Number.isFinite(guildId) || guildId <= 0) {
      throw redirect({ to: "/" });
    }

    // Skip membership validation while guilds are still loading
    // The component will handle validation once data is available
    // Don't set the guild ID yet — it may be invalid and would poison
    // the SPA's guild state if the user isn't a member.
    if (guilds?.loading) {
      return { urlGuildId: guildId, urlGuild: null };
    }

    // Validate membership
    const guildList = guilds?.guilds ?? [];
    const guild = guildList.find((g) => g.id === guildId);
    if (!guild) {
      // Let the component render a "not a member" message
      return { urlGuildId: guildId, urlGuild: null };
    }

    // beforeLoad ALSO runs for link PRELOADS (defaultPreload: "intent" —
    // hovering any cross-guild link, e.g. a recents tab). A preload must be
    // side-effect free: resetting caches on hover would ping-pong the app
    // between guilds. Only a real navigation adopts the guild.
    if (cause === "preload") {
      return { urlGuildId: guildId, urlGuild: guild };
    }

    // Adopt this tab's guild from the URL into local state (rail highlight,
    // query keys) before child routes render. Per-tab and local only — the
    // guild itself travels in each request's /g/{guildId} path.
    await guilds?.syncGuildFromUrl(guildId);

    // Provide validated guild info to child routes via route context
    return { urlGuildId: guildId, urlGuild: guild };
  },
  component: GuildLayout,
});

/** The guild subtree's waiting state — shown while the guild list is still
 *  arriving, and while this tab is catching up to the URL's guild. */
function GuildLoading() {
  const { t } = useTranslation("common");
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2
        role="status"
        aria-label={t("loading")}
        className="h-8 w-8 animate-spin text-muted-foreground"
      />
    </div>
  );
}

export function GuildLayout() {
  const { t } = useTranslation("guilds");
  const params = useParams({ from: "/_serverRequired/_authenticated/g/$guildId" });
  const guildId = Number(params.guildId);
  const { guilds, activeGuildId, loading, syncGuildFromUrl } = useGuilds();
  const location = useLocation();

  // Verify membership — must happen before syncing guild context
  const guild = !loading ? guilds.find((g) => g.id === guildId) : undefined;
  const isMember = Boolean(guild);

  // Sync guild context only after membership is confirmed.
  // This prevents setting an invalid guild ID on the API client,
  // which would cause "unable to load" errors on the redirect target.
  useEffect(() => {
    if (isMember && Number.isFinite(guildId)) {
      void syncGuildFromUrl(guildId);
    }
  }, [guildId, isMember, syncGuildFromUrl]);

  if (loading) {
    return <GuildLoading />;
  }

  if (!guild) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("notMember.title")}
          description={t("notMember.description")}
          backTo="/"
          backLabel={t("notMember.backToHome")}
        />
      </div>
    );
  }

  // Everything below reads this tab's active guild for its query keys, and that
  // value adopts the URL in the effect above — which runs a render AFTER the
  // guild list arrives, so `beforeLoad` had nothing to adopt on a cold load.
  // Holding the subtree until the two agree is what keeps a fresh tab opened
  // straight onto another guild's URL from issuing a page of guild-scoped
  // requests against the guild this tab started on and then repeating them.
  if (activeGuildId !== guildId) {
    return <GuildLoading />;
  }

  // A suspended guild only stays listed for its guild admins (members lose
  // the entry entirely and hit the not-a-member screen above), and every
  // content endpoint refuses it — only the settings surface (billing / data
  // ownership / danger zone) still works. Keep the admin out of a wall of
  // 403s by pinning them to settings.
  //
  // PAM/break-glass grantees are exempt: the backend's grant path never
  // consults the lifecycle status (a grantee browses a suspended guild exactly
  // like an active one — that's what keeps operators from being locked out),
  // so their content requests succeed and the pin would only strand them on a
  // settings page their synthesized role can't view.
  if (
    guild.status === "suspended" &&
    guild.accessType !== "grant" &&
    shouldPinSuspendedGuildToSettings(location.pathname, guildId)
  ) {
    return <Navigate to={guildPath(guildId, "/settings")} replace />;
  }

  return <Outlet />;
}
