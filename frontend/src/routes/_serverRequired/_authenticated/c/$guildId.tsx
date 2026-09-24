import { createFileRoute, Outlet, redirect, useLocation, useParams } from "@tanstack/react-router";
import { Lock, ShieldAlert } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { GuildStatusNotice, guildStatusNoticeApplies } from "@/components/guilds/GuildStatusNotice";
import { StatusMessage } from "@/components/StatusMessage";
import { GuildHomeSkeleton, PageSkeleton } from "@/components/skeletons/PageSkeletons";
import { useGuilds } from "@/hooks/useGuilds";
import { guildIsClosed } from "@/lib/permissions";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId")({
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

    // A closed community is never adopted as this tab's guild: nothing inside
    // it answers, so nothing should be asked of it. The component says so.
    if (guildIsClosed(guild)) {
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
    // guild itself travels in each request's /c/{guildId} path.
    await guilds?.syncGuildFromUrl(guildId);

    // Provide validated guild info to child routes via route context
    return { urlGuildId: guildId, urlGuild: guild };
  },
  component: GuildLayout,
});

/** The guild subtree's waiting state — shown while the guild list is still
 *  arriving, and while this tab is catching up to the URL's guild. The front
 *  page gets its own outline; anything deeper gets a page's. */
function GuildLoading({ guildId }: { guildId: number }) {
  const { pathname } = useLocation();
  const atHome = pathname === `/c/${guildId}` || pathname === `/c/${guildId}/`;
  return atHome ? <GuildHomeSkeleton /> : <PageSkeleton />;
}

export function GuildLayout() {
  const { t } = useTranslation("guilds");
  const params = useParams({ from: "/_serverRequired/_authenticated/c/$guildId" });
  const guildId = Number(params.guildId);
  const { guilds, activeGuildId, loading, syncGuildFromUrl } = useGuilds();

  // Verify membership — must happen before syncing guild context
  const guild = !loading ? guilds.find((g) => g.id === guildId) : undefined;
  const isMember = Boolean(guild);
  const closed = guildIsClosed(guild);

  // Sync guild context only after membership is confirmed.
  // This prevents setting an invalid guild ID on the API client,
  // which would cause "unable to load" errors on the redirect target.
  useEffect(() => {
    if (isMember && !closed && Number.isFinite(guildId)) {
      void syncGuildFromUrl(guildId);
    }
  }, [guildId, isMember, closed, syncGuildFromUrl]);

  if (loading) {
    return <GuildLoading guildId={guildId} />;
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

  // A suspended community is in time out: nobody in it reaches anything,
  // settings included, until the platform lifts it. Its administrators still
  // see it listed, and land here rather than on a page of refusals.
  if (closed) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <StatusMessage
          icon={<Lock />}
          title={t("closed.title")}
          description={`${t("closed.description")} ${
            guild.contact_email
              ? t("closed.contact", { email: guild.contact_email })
              : t("closed.contactNobody")
          }`}
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
    return <GuildLoading guildId={guildId} />;
  }

  const notice = guildStatusNoticeApplies(guild) ? (
    <GuildStatusNotice key={`${guild.id}:${guild.status}`} guild={guild} />
  ) : null;

  return (
    <>
      {notice}
      <Outlet />
    </>
  );
}
