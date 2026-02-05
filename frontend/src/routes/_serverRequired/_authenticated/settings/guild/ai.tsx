import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/guild/ai")({
  beforeLoad: ({ context }) => {
    const guildId = context.guilds?.activeGuildId;
    if (guildId) {
      throw redirect({
        to: "/g/$guildId/settings/ai",
        params: { guildId: String(guildId) },
      });
    }
    throw redirect({ to: "/" });
  },
});
