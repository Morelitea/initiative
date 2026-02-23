import { useEffect } from "react";
import { createFileRoute, Outlet, redirect, useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Loader2, ShieldAlert } from "lucide-react";
import { setCurrentGuildId } from "@/api/client";
import { StatusMessage } from "@/components/StatusMessage";
import { useGuilds } from "@/hooks/useGuilds";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId")({
  beforeLoad: ({ context, params }) => {
    const guildId = Number(params.guildId);
    const { guilds } = context;

    // Validate guildId is a valid number
    if (!Number.isFinite(guildId) || guildId <= 0) {
      throw redirect({ to: "/" });
    }

    // Skip membership validation while guilds are still loading
    // The component will handle validation once data is available
    // Don't set the guild ID yet — it may be invalid and would poison
    // the API client header if the user isn't a member.
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

    // Sync API client header to ensure requests go to correct guild
    setCurrentGuildId(guildId);

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
        <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
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
