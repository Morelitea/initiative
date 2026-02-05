import { useEffect } from "react";
import { createFileRoute, Outlet, redirect, useParams } from "@tanstack/react-router";
import { setCurrentGuildId } from "@/api/client";
import { useGuilds } from "@/hooks/useGuilds";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId")({
  beforeLoad: ({ context, params }) => {
    const guildId = Number(params.guildId);
    const { guilds } = context;

    // Validate guildId is a valid number
    if (!Number.isFinite(guildId) || guildId <= 0) {
      throw redirect({ to: "/" });
    }

    // Validate membership
    const guildList = guilds?.guilds ?? [];
    const guild = guildList.find((g) => g.id === guildId);
    if (!guild) {
      // User is not a member of this guild - redirect to home
      throw redirect({ to: "/" });
    }

    // Sync API client header to ensure requests go to correct guild
    setCurrentGuildId(guildId);

    // Provide validated guild info to child routes via route context
    return { urlGuildId: guildId, urlGuild: guild };
  },
  component: GuildLayout,
});

function GuildLayout() {
  const params = useParams({ from: "/_serverRequired/_authenticated/g/$guildId" });
  const guildId = Number(params.guildId);
  const { activeGuildId, syncGuildFromUrl } = useGuilds();

  // Sync guild context when URL guild ID changes
  useEffect(() => {
    if (Number.isFinite(guildId) && guildId !== activeGuildId) {
      void syncGuildFromUrl(guildId);
    }
  }, [guildId, activeGuildId, syncGuildFromUrl]);

  return <Outlet />;
}
