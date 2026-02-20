import { useEffect } from "react";
import { createFileRoute, Navigate, Outlet, redirect, useParams } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
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

    // Skip membership validation while guilds are still loading
    // The component will handle validation once data is available
    if (guilds?.loading) {
      setCurrentGuildId(guildId);
      return { urlGuildId: guildId, urlGuild: null };
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
  const { guilds, loading, syncGuildFromUrl } = useGuilds();

  // Sync guild context when URL guild ID changes.
  // syncGuildFromUrl is stable (no deps) and checks the ref internally,
  // so we only need guildId here to fire when the URL changes.
  useEffect(() => {
    if (Number.isFinite(guildId)) {
      void syncGuildFromUrl(guildId);
    }
  }, [guildId, syncGuildFromUrl]);

  // Show loading state while guilds are loading
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
      </div>
    );
  }

  // Verify membership synchronously before rendering children
  const guild = guilds.find((g) => g.id === guildId);
  if (!guild) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
