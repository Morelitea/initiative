import { useEffect } from "react";
import { createFileRoute, Outlet, redirect, useNavigate, useParams } from "@tanstack/react-router";
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
  const { guilds, activeGuildId, loading, syncGuildFromUrl } = useGuilds();
  const navigate = useNavigate();

  // Validate membership once guilds are loaded
  useEffect(() => {
    if (loading) return;

    const guild = guilds.find((g) => g.id === guildId);
    if (!guild) {
      // User is not a member of this guild - redirect to home
      void navigate({ to: "/" });
    }
  }, [loading, guilds, guildId, navigate]);

  // Sync guild context when URL guild ID changes
  useEffect(() => {
    if (Number.isFinite(guildId) && guildId !== activeGuildId) {
      void syncGuildFromUrl(guildId);
    }
  }, [guildId, activeGuildId, syncGuildFromUrl]);

  // Show loading state while guilds are loading
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="text-muted-foreground h-8 w-8 animate-spin" />
      </div>
    );
  }

  // Verify membership before rendering children
  const guild = guilds.find((g) => g.id === guildId);
  if (!guild) {
    return null; // Will redirect via useEffect
  }

  return <Outlet />;
}
