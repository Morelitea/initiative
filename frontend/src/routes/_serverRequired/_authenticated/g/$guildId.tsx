import { createFileRoute, Outlet, redirect, useParams } from "@tanstack/react-router";
import { Loader2, ShieldAlert } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import { useGuilds } from "@/hooks/useGuilds";

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

function GuildLayout() {
  const { t } = useTranslation("guilds");
  const params = useParams({ from: "/_serverRequired/_authenticated/g/$guildId" });
  const guildId = Number(params.guildId);
  const { guilds, loading, syncGuildFromUrl } = useGuilds();

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
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
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

  return <Outlet />;
}
